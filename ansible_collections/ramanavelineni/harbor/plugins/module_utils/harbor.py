# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""HTTP client and shared helpers for the ramanavelineni.harbor modules."""

import base64
import json
import re
import socket
import time

from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode

from ansible.module_utils.basic import env_fallback
from ansible.module_utils.common.text.converters import to_bytes, to_text
from ansible.module_utils.urls import open_url

# Major.minor releases the modules are tested against. Any other version
# gets a warning, not a failure.
TESTED_VERSIONS = ('2.14', '2.15')

# Statuses worth retrying: a proxy or the server itself was briefly unable
# to answer. Anything else is the server's real answer.
RETRY_STATUSES = (502, 503, 504)

# Harbor pages every list; 100 is the most a page may hold.
PAGE_SIZE = 100

API_PREFIX = '/api/v2.0'

GIB = 1024 ** 3


def harbor_argument_spec():
    """Connection options shared by every module (see doc fragment auth)."""
    return dict(
        url=dict(type='str', required=True, fallback=(env_fallback, ['HARBOR_URL'])),
        username=dict(type='str', required=True, fallback=(env_fallback, ['HARBOR_USERNAME'])),
        password=dict(type='str', required=True, no_log=True, fallback=(env_fallback, ['HARBOR_PASSWORD'])),
        validate_certs=dict(type='bool', default=True, fallback=(env_fallback, ['HARBOR_VALIDATE_CERTS'])),
        ca_path=dict(type='path', fallback=(env_fallback, ['HARBOR_CA_PATH'])),
        timeout=dict(type='int', default=30),
        retries=dict(type='int', default=3),
        retry_delay=dict(type='int', default=2),
    )


def base_url(url):
    """Server base URL without a trailing slash or /api/v2.0 suffix."""
    url = url.rstrip('/')
    for suffix in (API_PREFIX, '/api'):
        if url.endswith(suffix):
            url = url[:-len(suffix)]
            break
    return url


def version_is_tested(version):
    """True when a reported version ("v2.15.2-4b2c1e3a") is in TESTED_VERSIONS."""
    match = re.match(r'^v?(\d+)\.(\d+)(\.|-|$)', version or '')
    if not match:
        return False
    return '%s.%s' % (match.group(1), match.group(2)) in TESTED_VERSIONS


class HarborError(Exception):
    """A request failed. Carries everything needed to see why."""

    def __init__(self, method, url, status=None, response=None, request=None, reason=None):
        self.method = method
        self.url = url
        self.status = status
        self.response = response
        self.request = request
        self.reason = reason
        super(HarborError, self).__init__(self.message())

    def message(self):
        if self.status is None:
            return '%s %s failed without an HTTP response: %s' % (self.method, self.url, self.reason)
        body = self.response if self.response else '(empty body)'
        msg = '%s %s returned HTTP %s: %s' % (self.method, self.url, self.status, body)
        if self.reason:
            msg += ' (%s)' % self.reason
        return msg

    def details(self):
        return dict(method=self.method, url=self.url, status=self.status, response=self.response,
                    request=self.request)


class HarborClient(object):
    """Talks to the Harbor v2.0 API on behalf of one module run."""

    def __init__(self, module):
        self.module = module
        params = module.params
        self.url = base_url(params['url'])
        self.validate_certs = params['validate_certs']
        self.ca_path = params.get('ca_path')
        self.timeout = params['timeout']
        self.retries = max(params['retries'], 0)
        self.retry_delay = max(params['retry_delay'], 0)
        credentials = '%s:%s' % (params['username'], params['password'])
        self.auth = 'Basic %s' % to_text(base64.b64encode(to_bytes(credentials, errors='surrogate_or_strict')))
        self._info = None

    # -- requests ----------------------------------------------------------

    def get(self, path, params=None):
        return self.request('GET', path, params=params, expected=(200,), retry=True)[0]

    def post(self, path, body, expected=(201,)):
        return self.request('POST', path, body=body, expected=expected, retry=False)

    def put(self, path, body, expected=(200,)):
        return self.request('PUT', path, body=body, expected=expected, retry=True)[0]

    def delete(self, path, expected=(200,)):
        return self.request('DELETE', path, expected=expected, retry=False)[0]

    def request(self, method, path, params=None, body=None, expected=(200,), retry=False, headers=None):
        """(parsed JSON or None, response headers) for one request."""
        url = '%s%s%s' % (self.url, API_PREFIX, path)
        if params:
            url += '?' + urlencode(params)
        send_headers = {'Accept': 'application/json', 'Authorization': self.auth}
        send_headers.update(headers or {})
        data = None
        if body is not None:
            data = json.dumps(body)
            send_headers['Content-Type'] = 'application/json'

        attempts = 1 + (self.retries if retry else 0)
        for attempt in range(1, attempts + 1):
            try:
                response = open_url(
                    url,
                    data=data,
                    headers=send_headers,
                    method=method,
                    timeout=self.timeout,
                    validate_certs=self.validate_certs,
                    ca_path=self.ca_path,
                    follow_redirects='none',
                    use_proxy=True,
                    use_netrc=False,
                )
                status = response.getcode()
                raw = to_text(response.read(), errors='surrogate_or_strict')
                resp_headers = dict((k.lower(), v) for k, v in response.headers.items())
            except HTTPError as e:
                try:
                    raw = to_text(e.read(), errors='surrogate_or_strict')
                except Exception:
                    raw = ''
                if e.code in RETRY_STATUSES and attempt < attempts:
                    time.sleep(self.retry_delay)
                    continue
                raise HarborError(method, url, status=e.code, response=raw.strip(), request=data)
            except (URLError, socket.timeout, ConnectionError, OSError) as e:
                if attempt < attempts:
                    time.sleep(self.retry_delay)
                    continue
                raise HarborError(method, url, request=data, reason=to_text(e))

            if status not in expected:
                raise HarborError(method, url, status=status, response=raw.strip(), request=data)
            if not raw.strip():
                return None, resp_headers
            try:
                return json.loads(raw), resp_headers
            except ValueError:
                raise HarborError(method, url, status=status, response=raw.strip(), request=data,
                                  reason='response is not JSON')

    def list(self, path, params=None):
        """Every item of a paged list endpoint, following all pages."""
        items = []
        page = 1
        while True:
            query = dict(params or {})
            query.update(page=page, page_size=PAGE_SIZE)
            chunk, headers = self.request('GET', path, params=query, expected=(200,), retry=True)
            chunk = chunk or []
            items.extend(chunk)
            total = headers.get('x-total-count')
            if not chunk or len(chunk) < PAGE_SIZE or (total is not None and len(items) >= int(total)):
                return items
            page += 1

    # -- server ------------------------------------------------------------

    def info(self):
        """GET /systeminfo, cached for the module run."""
        if self._info is None:
            self._info = self.get('/systeminfo') or {}
        return self._info

    def check_login(self):
        """Fail unless the credentials were accepted.

        Harbor does not reject bad credentials on every endpoint: it serves
        the request anonymously instead (/systeminfo answers 200, /projects
        lists only public projects). Only an authenticated /systeminfo
        carries harbor_version, so its absence means the login failed.
        """
        if 'harbor_version' not in self.info():
            raise ValueError(
                'Harbor did not accept the credentials for %r at %s: it answered as for an anonymous '
                'user. Check username and password.' % (self.module.params['username'], self.url))

    def warn_if_untested(self):
        version = self.info().get('harbor_version', '')
        if not version_is_tested(version):
            self.module.warn(
                'Harbor reports version %r, which this collection has not been tested with '
                '(tested: %s). Continuing.' % (version, ', '.join(TESTED_VERSIONS)))


def server_minor(client):
    """The server's major.minor as a tuple of ints, e.g. (2, 15), or None."""
    match = re.match(r'^v?(\d+)\.(\d+)', client.info().get('harbor_version', ''))
    return (int(match.group(1)), int(match.group(2))) if match else None


def id_from_location(headers):
    """The id at the end of a create response's Location header."""
    location = headers.get('location') or ''
    tail = location.rstrip('/').rsplit('/', 1)[-1]
    return int(tail) if tail.isdigit() else None


def name_path(name):
    """A path segment for a resource named `name` (URL-quoted)."""
    return quote(name, safe='')


def find_by_name(items, name, what, field='name'):
    """The single item whose `field` equals `name`, or None; two matches fail."""
    matches = [item for item in items if item.get(field) == name]
    if len(matches) > 1:
        raise ValueError(
            'More than one %s is named %r; names must be unique for this module to manage them.'
            % (what, name))
    return matches[0] if matches else None


def fail_from_error(module, error, **result):
    """fail_json with a HarborError's full request/response details."""
    module.fail_json(msg=error.message(), request_details=error.details(), **result)


def run_module(module, handler):
    """Run handler(client) with uniform error reporting."""
    client = HarborClient(module)
    try:
        client.check_login()
        result = handler(client)
    except HarborError as e:
        fail_from_error(module, e)
    except ValueError as e:
        module.fail_json(msg=to_text(e))
    module.exit_json(**result)


def storage_to_gb(storage):
    if storage is None:
        return None
    if storage == -1:
        return -1
    return storage // GIB if storage % GIB == 0 else round(float(storage) / GIB, 3)


def project_view(project, quota, registries):
    """A project as the project modules return it."""
    metadata = dict(project.get('metadata') or {})
    public = metadata.pop('public', 'false') == 'true'
    return dict(
        project_id=project.get('project_id'), name=project.get('name'), public=public,
        metadata=metadata, registry_id=project.get('registry_id') or None,
        proxy_registry=registries.get(project.get('registry_id')),
        quota_gb=storage_to_gb(((quota or {}).get('hard') or {}).get('storage')),
        repo_count=project.get('repo_count', 0),
    )


# -- robot accounts ------------------------------------------------------------

DEFAULT_ROBOT_PREFIX = 'robot$'


def robot_prefix(client):
    """The robot name prefix Harbor puts in front of every robot account's name.

    Only a system administrator can read the configuration; anyone else gets
    Harbor's factory default.
    """
    try:
        config = client.get('/configurations') or {}
    except HarborError:
        return DEFAULT_ROBOT_PREFIX
    value = (config.get('robot_name_prefix') or {}).get('value')
    return value if value else DEFAULT_ROBOT_PREFIX


def canonical_permissions(permissions):
    """Robot permissions in a stable, comparable form (Harbor returns them in any order)."""
    merged = {}
    for perm in permissions or []:
        key = (perm.get('kind') or 'project', perm.get('namespace') or '')
        access = merged.setdefault(key, set())
        for item in perm.get('access') or []:
            access.add((item.get('resource'), item.get('action')))
    return [dict(kind=kind, namespace=namespace,
                 access=[dict(resource=r, action=a) for r, a in sorted(access)])
            for (kind, namespace), access in sorted(merged.items())]


def robot_short_name(full_name, project, prefix):
    """A robot account's name without the prefix and, for a project robot, the <project>+ part."""
    name = full_name or ''
    if project is not None and ('%s+' % project) in name:
        return name.rsplit('%s+' % project, 1)[1]
    return name[len(prefix):] if prefix and name.startswith(prefix) else name


def robot_account_view(robot, project, name=None, prefix=DEFAULT_ROBOT_PREFIX):
    """A robot account as the robot account modules return it (never a secret)."""
    return dict(
        id=robot.get('id'),
        name=name if name is not None else robot_short_name(robot.get('name'), project, prefix),
        full_name=robot.get('name'), level=robot.get('level'), project=project,
        description=robot.get('description') or '', duration=robot.get('duration'),
        expires_at=robot.get('expires_at'), disable=bool(robot.get('disable', False)),
        permissions=canonical_permissions(robot.get('permissions')),
    )
