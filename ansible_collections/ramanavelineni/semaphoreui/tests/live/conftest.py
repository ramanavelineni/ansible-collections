# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""Live test harness: runs the modules, in this process, against a real Semaphore.

Nothing here is a unit test. `ansible-test units` only looks under tests/unit,
and every test in this directory is skipped unless SEMAPHORE_URL is set, so
CI never talks to a server. Run it against a throwaway server:

    SEMAPHORE_URL=http://127.0.0.1:3019 SEMAPHORE_PASSWORD=... \\
        python -m pytest ansible_collections/ramanavelineni/semaphoreui/tests/live

SEMAPHORE_USERNAME defaults to admin. With SEMAPHORE_PASSWORD the suite runs
twice: once logging in with the password, once with an API token it creates
for the run and deletes again. With only SEMAPHORE_API_TOKEN it runs once.

The suite creates and deletes objects, so the server must be a throwaway on a
loopback address; any other address is refused unless
SEMAPHORE_LIVE_ALLOW_REMOTE=1. Everything it creates has a name starting with
"live-", and it deletes what an earlier run left behind before it starts. It
never touches an object without that prefix.
"""

import contextlib
import io
import ipaddress
import json
import os
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar

import pytest

# The repository root holds ansible_collections/, which the modules import
# themselves through. tests/live is five directories below it.
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), *['..'] * 5))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from ansible.module_utils import basic  # noqa: E402  pylint: disable=wrong-import-position
from ansible_collections.ramanavelineni.semaphoreui.plugins.modules import info  # noqa: E402  pylint: disable=wrong-import-position

PREFIX = 'live-'
TIMEOUT = 30
URL = os.environ.get('SEMAPHORE_URL', '').rstrip('/')
USERNAME = os.environ.get('SEMAPHORE_USERNAME') or 'admin'
PASSWORD = os.environ.get('SEMAPHORE_PASSWORD')
API_TOKEN = os.environ.get('SEMAPHORE_API_TOKEN')
# The modules fall back to these variables themselves. The suite passes every
# connection option explicitly, so take them out of the modules' sight.
for _name in ('SEMAPHORE_URL', 'SEMAPHORE_USERNAME', 'SEMAPHORE_PASSWORD', 'SEMAPHORE_API_TOKEN'):
    os.environ.pop(_name, None)


def pytest_collection_modifyitems(items):
    if URL:
        return
    skip = pytest.mark.skip(reason='live tests need a throwaway Semaphore: set SEMAPHORE_URL and SEMAPHORE_PASSWORD')
    here = os.path.dirname(__file__)
    for item in items:
        if str(item.fspath).startswith(here):
            item.add_marker(skip)


def is_loopback(url):
    host = urllib.parse.urlsplit(url).hostname or ''
    try:
        addresses = set(info[4][0] for info in socket.getaddrinfo(host, None))
    except socket.gaierror:
        return False
    return bool(addresses) and all(ipaddress.ip_address(a.split('%')[0]).is_loopback for a in addresses)


class Api(object):
    """A few direct API calls: cleaning up, a token for the run, and reading what a module can't show."""

    def __init__(self, url, username, password, token):
        self.base = url + '/api'
        self.token = token
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
        if not token:
            status, dummy = self.call('POST', '/auth/login', dict(auth=username, password=password))
            if status != 204:
                raise RuntimeError('Semaphore at %s does not accept the credentials (HTTP %s)' % (url, status))

    def call(self, method, path, body=None):
        headers = {'Content-Type': 'application/json'}
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=TIMEOUT) as answer:
                status, raw = answer.status, answer.read()
        except urllib.error.HTTPError as e:
            status, raw = e.code, e.read()
        try:
            return status, json.loads(raw) if raw else None
        except ValueError:
            return status, raw.decode('utf-8', 'replace')

    def get(self, path):
        status, body = self.call('GET', path)
        if status != 200:
            raise RuntimeError('GET %s answered HTTP %s' % (path, status))
        return body

    def sweep(self):
        """Delete what carries the suite's prefix. Returns what it found."""
        found = []
        for project in self.get('/projects') or []:
            if project['name'].startswith(PREFIX):
                found.append('project %s' % project['name'])
                self.call('DELETE', '/project/%d' % project['id'])
        status, runners = self.call('GET', '/runners')
        for runner in (runners or []) if status == 200 else []:
            if (runner.get('name') or '').startswith(PREFIX):
                found.append('runner %s' % runner['name'])
                self.call('DELETE', '/runners/%d' % runner['id'])
        for user in self.get('/users') or []:
            if user['username'].startswith(PREFIX):
                found.append('user %s' % user['username'])
                self.call('DELETE', '/users/%d' % user['id'])
        return found


@contextlib.contextmanager
def module_args(args):
    """Hand `args` to AnsibleModule, the way the controller does (see tests/unit's harness for why not ansible's own helper)."""
    payload = json.dumps(dict(ANSIBLE_MODULE_ARGS=args)).encode()
    saved = dict((name, getattr(basic, name)) for name in ('_ANSIBLE_ARGS', '_ANSIBLE_PROFILE') if hasattr(basic, name))
    basic._ANSIBLE_ARGS = payload
    if '_ANSIBLE_PROFILE' in saved:
        basic._ANSIBLE_PROFILE = 'legacy'
    try:
        yield
    finally:
        for name, value in saved.items():
            setattr(basic, name, value)


class Semaphore(object):
    """What the tests get: run(module, ...) with the connection filled in, and the direct API."""

    def __init__(self, api, connection, auth):
        self.api = api
        self.connection = connection
        self.auth = auth
        self.version = ''

    def run(self, module, check_mode=False, **args):
        """The module's result as a dict. None removes an option."""
        full = dict(self.connection, _ansible_check_mode=check_mode, _ansible_diff=True)
        full.update(args)
        full = dict((k, v) for k, v in full.items() if v is not None)
        out = io.StringIO()
        with module_args(full), contextlib.redirect_stdout(out):
            try:
                module.main()
            except SystemExit:
                pass
        text = out.getvalue().strip()
        if not text:
            raise AssertionError('%s printed no result' % module.__name__)
        # Secrets a module registers come back in this key on newer ansible-core; the controller strips it.
        result = json.loads(text.splitlines()[-1])
        result.pop('_ansible_new_secrets', None)
        return result

    def ok(self, module, check_mode=False, **args):
        """run(), failing the test with the module's message when the module failed."""
        result = self.run(module, check_mode=check_mode, **args)
        assert not result.get('failed'), '%s failed: %s' % (module.__name__.rsplit('.', 1)[-1], result.get('msg'))
        return result

    def at_least(self, minor):
        """Whether the server is at least 2.<minor>."""
        parts = self.version.lstrip('v').split('.')
        try:
            return (int(parts[0]), int(parts[1])) >= (2, minor)
        except (ValueError, IndexError):
            return True


def auth_modes():
    if PASSWORD:
        return ['password', 'api_token']
    return ['api_token']


@pytest.fixture(scope='session')
def api():
    if not is_loopback(URL) and os.environ.get('SEMAPHORE_LIVE_ALLOW_REMOTE') != '1':
        pytest.exit('%s is not a loopback address. The live tests create and delete objects; point them at a throwaway '
                    'server, or set SEMAPHORE_LIVE_ALLOW_REMOTE=1 if this one is.' % URL, returncode=2)
    if not PASSWORD and not API_TOKEN:
        pytest.exit('set SEMAPHORE_PASSWORD (or SEMAPHORE_API_TOKEN) for %s' % URL, returncode=2)
    client = Api(URL, USERNAME, PASSWORD, None if PASSWORD else API_TOKEN)
    client.sweep()
    yield client
    left = client.sweep()
    assert not left, 'the run left these behind (now deleted): %s' % ', '.join(left)


@pytest.fixture(scope='module', params=auth_modes())
def sem(request, api):
    """The server, reached once per way of logging in. Module scope, so a test file runs as one chain per way."""
    token_id = None
    if request.param == 'password':
        connection = dict(url=URL, username=USERNAME, password=PASSWORD)
    elif PASSWORD:
        status, body = api.call('POST', '/user/tokens')
        assert status == 201, 'creating an API token answered HTTP %s' % status
        token_id = body['id']
        connection = dict(url=URL, api_token=token_id)
    else:
        connection = dict(url=URL, api_token=API_TOKEN)
    api.sweep()
    server = Semaphore(api, connection, request.param)
    server.version = server.ok(info)['version']
    yield server
    api.sweep()
    if token_id:
        api.call('DELETE', '/user/tokens/%s' % token_id)
