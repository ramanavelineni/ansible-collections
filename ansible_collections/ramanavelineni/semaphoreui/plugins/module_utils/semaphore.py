# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""HTTP client and shared helpers for the ramanavelineni.semaphoreui modules."""

import json
import re
import socket
import time

from http.cookiejar import CookieJar
from urllib.error import HTTPError, URLError

from ansible.module_utils.basic import env_fallback
from ansible.module_utils.common.text.converters import to_text
from ansible.module_utils.urls import open_url

# Major.minor releases the modules are tested against. Any other version
# gets a warning, not a failure: the API has been additive-only between
# these releases, but that is verified per release, not assumed.
TESTED_VERSIONS = ('2.18', '2.19')

# Statuses worth retrying: a proxy or the server itself was briefly unable
# to answer. Anything else is the server's real answer.
RETRY_STATUSES = (502, 503, 504)

# Semaphore caps some list endpoints (projects among them) at this many rows
# and has no paging for them. A list that comes back exactly this long may be
# missing rows, so lookups on it fail rather than create a duplicate.
LIST_CAP = 200


def semaphore_argument_spec():
    """Connection options shared by every module (see doc fragment auth)."""
    return dict(
        url=dict(type='str', required=True, fallback=(env_fallback, ['SEMAPHORE_URL'])),
        api_token=dict(type='str', no_log=True, fallback=(env_fallback, ['SEMAPHORE_API_TOKEN'])),
        username=dict(type='str', fallback=(env_fallback, ['SEMAPHORE_USERNAME'])),
        password=dict(type='str', no_log=True, fallback=(env_fallback, ['SEMAPHORE_PASSWORD'])),
        validate_certs=dict(type='bool', default=True, fallback=(env_fallback, ['SEMAPHORE_VALIDATE_CERTS'])),
        ca_path=dict(type='path', fallback=(env_fallback, ['SEMAPHORE_CA_PATH'])),
        timeout=dict(type='int', default=30),
        retries=dict(type='int', default=3),
        retry_delay=dict(type='int', default=2),
    )


def semaphore_module_kwargs():
    """AnsibleModule keyword arguments that go with semaphore_argument_spec()."""
    return dict(
        mutually_exclusive=[('api_token', 'username'), ('api_token', 'password')],
        required_together=[('username', 'password')],
        required_one_of=[('api_token', 'username')],
    )


def base_url(url):
    """Server base URL without a trailing slash or /api suffix."""
    url = url.rstrip('/')
    if url.endswith('/api'):
        url = url[:-len('/api')]
    return url


def version_is_tested(version):
    """True when a reported version ("v2.19.12", "2.18.30") is in TESTED_VERSIONS."""
    match = re.match(r'^v?(\d+)\.(\d+)(\.|$)', version or '')
    if not match:
        return False
    return '%s.%s' % (match.group(1), match.group(2)) in TESTED_VERSIONS


class SemaphoreError(Exception):
    """A request failed. Carries everything needed to see why."""

    def __init__(self, method, url, status=None, response=None, request=None, reason=None):
        self.method = method
        self.url = url
        self.status = status
        self.response = response
        self.request = request
        self.reason = reason
        super(SemaphoreError, self).__init__(self.message())

    def message(self):
        if self.status is None:
            return '%s %s failed without an HTTP response: %s' % (self.method, self.url, self.reason)
        # Semaphore answers some rejected writes with a bare 400 and an empty
        # body. That is never its validation error (those carry a JSON body):
        # the body could not be decoded or the write hit a database constraint.
        body = self.response if self.response else '(empty body)'
        msg = '%s %s returned HTTP %s: %s' % (self.method, self.url, self.status, body)
        if self.reason:
            msg += ' (%s)' % self.reason
        return msg

    def details(self):
        return dict(
            method=self.method,
            url=self.url,
            status=self.status,
            response=self.response,
            request=self.request,
        )


class SemaphoreClient(object):
    """Talks to the Semaphore API on behalf of one module run.

    With username/password the client logs in on first use and logs out in
    close(); with an API token every request carries it as a Bearer token.
    """

    def __init__(self, module):
        self.module = module
        params = module.params
        self.url = base_url(params['url'])
        self.api_token = params.get('api_token')
        self.username = params.get('username')
        self.password = params.get('password')
        self.validate_certs = params['validate_certs']
        self.ca_path = params.get('ca_path')
        self.timeout = params['timeout']
        self.retries = max(params['retries'], 0)
        self.retry_delay = max(params['retry_delay'], 0)
        self.cookies = CookieJar()
        self.logged_in = False
        self._info = None

    # -- session -----------------------------------------------------------

    def login(self):
        if self.api_token or self.logged_in:
            return
        # A login only opens a session, so it is safe to retry.
        self._request('POST', '/auth/login',
                      body={'auth': self.username, 'password': self.password},
                      expected=(204,), retry=True)
        self.logged_in = True

    def close(self):
        """Log out if this client logged in. Never raises."""
        if not self.logged_in:
            return
        try:
            self._request('POST', '/auth/logout', expected=(204,), retry=False)
        except SemaphoreError:
            pass
        self.logged_in = False

    # -- requests ----------------------------------------------------------

    def get(self, path):
        return self.request('GET', path, expected=(200,), retry=True)

    def post(self, path, body):
        return self.request('POST', path, body=body, expected=(201,), retry=False)

    def put(self, path, body):
        return self.request('PUT', path, body=body, expected=(204,), retry=True)

    def delete(self, path):
        return self.request('DELETE', path, expected=(204,), retry=False)

    def request(self, method, path, body=None, expected=(200,), retry=False):
        self.login()
        return self._request(method, path, body=body, expected=expected, retry=retry)

    def _request(self, method, path, body=None, expected=(200,), retry=False):
        url = '%s/api%s' % (self.url, path)
        headers = {'Accept': 'application/json'}
        data = None
        if body is not None:
            data = json.dumps(body)
            headers['Content-Type'] = 'application/json'
        if self.api_token:
            headers['Authorization'] = 'Bearer %s' % self.api_token

        attempts = 1 + (self.retries if retry else 0)
        for attempt in range(1, attempts + 1):
            status = None
            try:
                response = open_url(
                    url,
                    data=data,
                    headers=headers,
                    method=method,
                    timeout=self.timeout,
                    validate_certs=self.validate_certs,
                    ca_path=self.ca_path,
                    cookies=self.cookies,
                    follow_redirects='none',
                    use_proxy=True,
                    use_netrc=False,
                )
                status = response.getcode()
                raw = to_text(response.read(), errors='surrogate_or_strict')
            except HTTPError as e:
                status = e.code
                try:
                    raw = to_text(e.read(), errors='surrogate_or_strict')
                except Exception:
                    raw = ''
                if status in RETRY_STATUSES and attempt < attempts:
                    time.sleep(self.retry_delay)
                    continue
                raise SemaphoreError(method, url, status=status, response=raw.strip(), request=data)
            except (URLError, socket.timeout, ConnectionError, OSError) as e:
                if attempt < attempts:
                    time.sleep(self.retry_delay)
                    continue
                raise SemaphoreError(method, url, request=data, reason=to_text(e))

            if status not in expected:
                raise SemaphoreError(method, url, status=status, response=raw.strip(), request=data)
            if not raw.strip():
                return None
            try:
                return json.loads(raw)
            except ValueError:
                raise SemaphoreError(method, url, status=status, response=raw.strip(), request=data,
                                     reason='response is not JSON')

    # -- server ------------------------------------------------------------

    def info(self):
        """GET /api/info, cached for the module run."""
        if self._info is None:
            self._info = self.get('/info') or {}
        return self._info

    def warn_if_untested(self):
        version = self.info().get('version', '')
        if not version_is_tested(version):
            self.module.warn(
                'Semaphore reports version %r, which this collection has not been tested with '
                '(tested: %s). Continuing.' % (version, ', '.join(TESTED_VERSIONS)))

    # -- lookups -----------------------------------------------------------

    def list(self, path, capped=False):
        items = self.get(path) or []
        if capped and len(items) >= LIST_CAP:
            raise ValueError(
                'GET %s/api%s returned %d rows, the most Semaphore returns for this list. Rows past '
                'the cap are invisible, so looking up by name could miss an existing object and '
                'create a duplicate. Refusing to continue.' % (self.url, path, len(items)))
        return items


def find_by_name(items, name, what, field='name'):
    """The single item whose `field` equals `name`, or None.

    Semaphore does not enforce unique names, so two matches is an error the
    caller has to fix by hand: picking one would be a guess.
    """
    matches = [item for item in items if item.get(field) == name]
    if len(matches) > 1:
        raise ValueError(
            'More than one %s is named %r (ids %s). Names must be unique for this module to '
            'manage them; rename or delete the extra ones in Semaphore.'
            % (what, name, ', '.join(str(m.get('id')) for m in matches)))
    return matches[0] if matches else None


def resolve_project(client, name):
    """Id of the project named `name`; fails when there is none."""
    project = find_by_name(client.list('/projects', capped=True), name, 'project')
    if project is None:
        raise ValueError(
            'Project %r does not exist, or the user this module logs in as cannot see it.' % name)
    return project['id']


def refuse_delete_if_used(client, path, what, name):
    """Fail with what still uses the object at `path` (via its /refs), if anything.

    Semaphore refuses such a delete itself, but its answer is misleading:
    2.19 always blames templates and 2.18 sends an empty body.
    """
    refs = client.get(path + '/refs') or {}
    used = ['%s %s' % (kind.replace('_', ' '), ', '.join(sorted(r.get('name') or str(r.get('id')) for r in items)))
            for kind, items in sorted(refs.items()) if items]
    if used:
        raise ValueError('Cannot delete %s %r: it is still used by %s. Change or delete those first.'
                         % (what, name, '; '.join(used)))


def diff_fields(desired, current):
    """Keys of `desired` whose value differs from `current`. None means "not managed"."""
    return sorted(k for k, v in desired.items() if v is not None and current.get(k) != v)


def fail_from_error(module, error, **result):
    """fail_json with a SemaphoreError's full request/response details.

    Values of no_log options are masked by Ansible in everything returned.
    """
    module.fail_json(msg=error.message(), request_details=error.details(), **result)


def run_module(module, handler):
    """Run handler(client) with login/logout and uniform error reporting."""
    client = SemaphoreClient(module)
    try:
        result = handler(client)
    except SemaphoreError as e:
        client.close()
        fail_from_error(module, e)
    except ValueError as e:
        client.close()
        module.fail_json(msg=to_text(e))
    client.close()
    module.exit_json(**result)
