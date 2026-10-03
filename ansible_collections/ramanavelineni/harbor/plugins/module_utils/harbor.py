# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""HTTP client and shared helpers for the ramanavelineni.harbor modules."""

import base64
import json
import re
import socket
import ssl
import time
import traceback

from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode

from ansible.module_utils.basic import env_fallback
from ansible.module_utils.common.text.converters import to_bytes, to_text
from ansible.module_utils.urls import open_url

# Major.minor releases the modules are tested against. Any other version
# gets a warning, not a failure.
TESTED_VERSIONS = ('2.14', '2.15')

# Statuses worth retrying: a proxy or the server itself was briefly unable
# to answer. Anything else is the server's real answer.
RETRY_STATUSES = (502, 503, 504)

# Harbor locks a username for 1.5 s after a failed login (frozenTime in
# src/core/auth/authenticator.go, 2.14 and 2.15). A request for that user
# during the lock, even with the right password, is handled as anonymous:
# endpoints that need a login answer 401, /systeminfo leaves out
# harbor_version. It happens when another client fails to log in as the same
# user at the same moment, so one retry after the lock has passed is enough.
LOGIN_LOCK_WAIT = 2

# Harbor pages every list; 100 is the most a page may hold.
PAGE_SIZE = 100
# No list the modules read comes near this. It only stops an endpoint that
# never runs out of pages.
MAX_PAGES = 1000

API_PREFIX = '/api/v2.0'

GIB = 1024 ** 3

# Request bodies are shown in failures. Values under keys like these, and any
# value of a no_log option, are replaced first: Ansible's own masking only
# finds a secret that appears exactly as it was passed, and an update also
# sends back secrets read from Harbor (a webhook's auth header).
SECRET_KEYS = re.compile(r'secret|password|token|auth_header', re.IGNORECASE)
MASK = '********'


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
        warn_untested_version=dict(type='bool', default=True,
                                   fallback=(env_fallback, ['HARBOR_WARN_UNTESTED_VERSION'])),
    )


def base_url(url):
    """Server base URL without a trailing slash or /api/v2.0 suffix."""
    url = url.rstrip('/')
    for suffix in (API_PREFIX, '/api'):
        if url.endswith(suffix):
            url = url[:-len(suffix)]
            break
    return url


def redact(value, secrets=(), key=''):
    """A copy of a request body that is safe to show: secret strings replaced by MASK."""
    if isinstance(value, dict):
        return dict((k, redact(v, secrets, k)) for k, v in value.items())
    if isinstance(value, list):
        return [redact(v, secrets, key) for v in value]
    if isinstance(value, str) and value and (SECRET_KEYS.search(key) or value in secrets):
        return MASK
    return value


def version_is_tested(version):
    """True when a reported version ("v2.15.2-4b2c1e3a") is in TESTED_VERSIONS."""
    match = re.match(r'^v?(\d+)\.(\d+)(\.|-|$)', version or '')
    if not match:
        return False
    return '%s.%s' % (match.group(1), match.group(2)) in TESTED_VERSIONS


def permanent_failure(error):
    """True for a failure without an HTTP response that asking again cannot cure.

    A certificate that does not verify, a ca_path that is not there and a host
    name that does not resolve are settings to fix, not moments to wait out.
    open_url hands on a missing CA file as it is and wraps the other two in a
    URLError. A refused or reset connection and a timeout stay worth a retry:
    a server that is restarting answers like that.
    """
    cause = error
    if isinstance(error, URLError) and isinstance(error.reason, BaseException):
        cause = error.reason
    if isinstance(cause, (ssl.SSLCertVerificationError, FileNotFoundError)):
        return True
    if isinstance(cause, socket.gaierror):
        # EAI_AGAIN is the resolver saying "try again later".
        return cause.errno != socket.EAI_AGAIN
    return False


def older_than(minor, needed):
    """True when the server's major.minor (see server_minor) is known and below `needed`.

    A version that cannot be read (None) is not called older: the option is
    sent and Harbor decides. A build with a version string of its own is more
    likely new than old, and warn_if_untested() has already said so.
    """
    return minor is not None and minor < needed


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
        self.warn_untested_version = params.get('warn_untested_version', True)
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
        sent = None
        if body is not None:
            data = json.dumps(body)
            sent = redact(body, self.module.no_log_values)
            send_headers['Content-Type'] = 'application/json'

        attempts = 1 + (self.retries if retry else 0)
        attempt = 0
        waited_for_lock = False
        while True:
            attempt += 1
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
                if e.code == 401 and not waited_for_lock:
                    # A 401 is answered before the request is handled, so
                    # even a create can be sent again. Doesn't use up an
                    # attempt.
                    waited_for_lock = True
                    attempt -= 1
                    time.sleep(LOGIN_LOCK_WAIT)
                    continue
                if e.code in RETRY_STATUSES and attempt < attempts:
                    time.sleep(self.retry_delay)
                    continue
                raise HarborError(method, url, status=e.code, response=raw.strip(), request=sent)
            except (URLError, socket.timeout, ConnectionError, OSError, HTTPException) as e:
                # HTTPException: the answer was cut short or isn't HTTP at all
                # (IncompleteRead, BadStatusLine). Neither is an OSError.
                if attempt < attempts and not permanent_failure(e):
                    time.sleep(self.retry_delay)
                    continue
                raise HarborError(method, url, request=sent, reason=to_text(e))

            if status not in expected:
                raise HarborError(method, url, status=status, response=raw.strip(), request=sent)
            if not raw.strip():
                return None, resp_headers
            try:
                return json.loads(raw), resp_headers
            except ValueError:
                raise HarborError(method, url, status=status, response=raw.strip(), request=sent,
                                  reason='response is not JSON')

    def list(self, path, params=None):
        """Every item of a paged list endpoint, following all pages.

        X-Total-Count decides when it is there: a server or proxy that caps the
        page size below PAGE_SIZE answers with short pages that are not the
        last. Without the header a short page is the last one. A page that
        repeats the one before comes from an endpoint that ignores `page`; its
        items are already there, so the list ends without them.
        """
        items = []
        page = 1
        previous = None
        while True:
            query = dict(params or {})
            query.update(page=page, page_size=PAGE_SIZE)
            chunk, headers = self.request('GET', path, params=query, expected=(200,), retry=True)
            chunk = chunk or []
            if not chunk or chunk == previous:
                return items
            items.extend(chunk)
            previous = chunk
            total = to_text(headers.get('x-total-count') or '').strip()
            if total.isdigit():
                if len(items) >= int(total):
                    return items
            elif len(chunk) < PAGE_SIZE:
                return items
            if page >= MAX_PAGES:
                raise ValueError(
                    'GET %s%s%s did not end after %d pages. Stopping instead of reading it for ever.'
                    % (self.url, API_PREFIX, path, MAX_PAGES))
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

        Harbor answers the same way for a moment after another client failed
        to log in as this user (see LOGIN_LOCK_WAIT), so it asks once more
        before giving up.
        """
        if 'harbor_version' not in self.info():
            time.sleep(LOGIN_LOCK_WAIT)
            self._info = None
        if 'harbor_version' not in self.info():
            raise ValueError(
                'Harbor did not accept the credentials for %r at %s: it answered as for an anonymous '
                'user, also when asked again %d seconds later. Check username and password.'
                % (self.module.params['username'], self.url, LOGIN_LOCK_WAIT))

    def warn_if_untested(self):
        if not self.warn_untested_version:
            return
        version = self.info().get('harbor_version', '')
        if not version_is_tested(version):
            self.module.warn(
                'Harbor reports version %r, which this collection has not been tested with '
                '(tested: %s). Continuing. Set warn_untested_version to false to silence this.'
                % (version, ', '.join(TESTED_VERSIONS)))


def server_minor(client):
    """The server's major.minor as a tuple of ints, e.g. (2, 15), or None."""
    match = re.match(r'^v?(\d+)\.(\d+)', client.info().get('harbor_version', ''))
    return (int(match.group(1)), int(match.group(2))) if match else None


def id_from_location(headers):
    """The id at the end of a create response's Location header."""
    location = headers.get('location') or ''
    tail = location.rstrip('/').rsplit('/', 1)[-1]
    return int(tail) if tail.isdigit() else None


def find_by_name(items, name, what, field='name'):
    """The single item whose `field` equals `name`, or None; two matches fail."""
    matches = [item for item in items if item.get(field) == name]
    if len(matches) > 1:
        raise ValueError(
            'More than one %s is named %r; names must be unique for this module to manage them.'
            % (what, name))
    return matches[0] if matches else None


def fail_from_error(module, error, **result):
    """fail_json with a HarborError's request/response details; the request is already redacted."""
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
    except Exception as e:
        # Anything else is a bug here or an answer in a form the module doesn't
        # expect. The message names the exception; the traceback goes into
        # `exception`, which Ansible shows only with -vvv.
        module.fail_json(msg='Unexpected %s: %s. Harbor may have answered in a form this module does not '
                             'expect.' % (type(e).__name__, to_text(e)), exception=traceback.format_exc())
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
    Harbor's factory default. Any other failure is reported: guessing the
    prefix would make robots unfindable on a server with its own.
    """
    try:
        config = client.get('/configurations') or {}
    except HarborError as e:
        if e.status not in (401, 403):
            raise
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


def webhook_view(policy, project):
    """A webhook as the webhook modules return it: first target flattened, auth header hidden."""
    targets = policy.get('targets') or []
    target = targets[0] if targets else {}
    return dict(
        id=policy.get('id'), name=policy.get('name'), project=project, project_id=policy.get('project_id'),
        description=policy.get('description') or '', enabled=bool(policy.get('enabled', False)),
        event_types=sorted(policy.get('event_types') or []),
        notify_type=target.get('type'), address=target.get('address'),
        auth_header_set=bool(target.get('auth_header')),
        skip_cert_verify=bool(target.get('skip_cert_verify', False)),
        payload_format=target.get('payload_format') or None,
    )


def project_by_name(client, name):
    """The project named `name` (read on its own, so its metadata is complete); fails when missing."""
    found = find_by_name(client.list('/projects'), name, 'project')
    if found is None:
        raise ValueError('Project %r does not exist, or the user this module logs in as cannot see it.' % name)
    return client.get('/projects/%d' % found['project_id'])


# -- tag retention and tag immutability ---------------------------------------
#
# Both use Harbor's selector shape: a doublestar pattern with a decoration.
# The UI and the modules say "matches" / "excludes"; the API spells the
# repository ones repoMatches / repoExcludes.

TAG_DECORATIONS = dict(matches='matches', excludes='excludes')
REPO_DECORATIONS = dict(matches='repoMatches', excludes='repoExcludes')
# Retention rule templates and the unit of the number each one takes
# (None: the template takes no number).
RETENTION_TEMPLATES = dict(latestPushedK='count', latestPulledN='count', nDaysSinceLastPush='days',
                           nDaysSinceLastPull='days', always=None)


def _decoration(api_value, table):
    for option, api in table.items():
        if api == api_value:
            return option
    return api_value


def _untagged(extras):
    if not extras:
        return False
    try:
        return bool(json.loads(extras).get('untagged', False))
    except (ValueError, AttributeError):
        return False


def selectors_view(rule):
    """The repository and tag selectors of a retention or immutability rule, as module options."""
    repo = ((rule.get('scope_selectors') or {}).get('repository') or [{}])[0]
    tag = (rule.get('tag_selectors') or [{}])[0]
    return dict(
        repositories=repo.get('pattern', '**'), repositories_decoration=_decoration(repo.get('decoration'), REPO_DECORATIONS),
        tags=tag.get('pattern', '**'), tags_decoration=_decoration(tag.get('decoration'), TAG_DECORATIONS),
        untagged=_untagged(tag.get('extras')),
    )


def selectors_body(options, with_untagged):
    """Harbor's tag_selectors / scope_selectors for module-style options."""
    tag = dict(kind='doublestar', decoration=TAG_DECORATIONS[options['tags_decoration']], pattern=options['tags'])
    if with_untagged:
        tag['extras'] = json.dumps(dict(untagged=bool(options['untagged'])))
    return dict(
        tag_selectors=[tag],
        scope_selectors=dict(repository=[dict(kind='doublestar', decoration=REPO_DECORATIONS[options['repositories_decoration']],
                                              pattern=options['repositories'])]),
    )


def retention_rule_view(rule):
    view = selectors_view(rule)
    template = rule.get('template')
    value = (rule.get('params') or {}).get(template)
    view.update(template=template, value=int(value) if isinstance(value, (int, float)) or str(value).isdigit() else value,
                disabled=bool(rule.get('disabled', False)))
    return view


def retention_view(policy, project_name):
    """A retention policy as the tag_retention modules return it."""
    return dict(
        id=policy.get('id'), project=project_name,
        schedule=((policy.get('trigger') or {}).get('settings') or {}).get('cron') or '',
        rules=[retention_rule_view(r) for r in policy.get('rules') or []],
    )


def immutability_rule_view(rule, project_name):
    """An immutability rule as the tag_immutability modules return it."""
    view = selectors_view(rule)
    view.pop('untagged')
    view.update(id=rule.get('id'), project=project_name, disabled=bool(rule.get('disabled', False)))
    return view
