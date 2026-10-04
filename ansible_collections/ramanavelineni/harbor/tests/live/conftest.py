# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""Live suite: the real modules against a real Harbor, on the developer's machine.

The unit tests prove what a module sends and how it reads recorded answers.
They cannot prove that Harbor accepts what is sent, or that a second run finds
nothing to change. These tests can: each calls a module's main() in this
process, with real HTTP, against the server named by the environment:

    HARBOR_URL        for example http://127.0.0.1:8015
    HARBOR_USERNAME   an administrator (default: admin)
    HARBOR_PASSWORD   its password

Without HARBOR_URL every test is skipped, so nothing here runs by accident;
"ansible-test units" does not look into tests/live at all. From the repository
root, with ansible-core and pytest installed:

    HARBOR_URL=http://127.0.0.1:8015 HARBOR_PASSWORD=... PYTHONPATH=. \\
        python -m pytest ansible_collections/ramanavelineni/harbor/tests/live

The suite creates, changes and deletes objects and, for a moment, global
settings and schedules, so it only runs against a server on this machine (a
loopback address) unless HARBOR_LIVE_ALLOW_REMOTE=1 says the server is a
throwaway too. Everything it creates is named "live-..."; nothing else is
touched. What a run that died left behind is removed at the start of the next.
"""

import base64
import contextlib
import ipaddress
import json
import os
import socket
import time
import urllib.error
import urllib.request
from urllib.parse import quote, urlsplit

import pytest

from ansible.module_utils import basic

HERE = os.path.dirname(os.path.abspath(__file__))
URL = (os.environ.get('HARBOR_URL') or '').rstrip('/')
USERNAME = os.environ.get('HARBOR_USERNAME') or 'admin'
PASSWORD = os.environ.get('HARBOR_PASSWORD') or ''
ALLOW_REMOTE = 'HARBOR_LIVE_ALLOW_REMOTE'
PREFIX = 'live-'
TIMEOUT = 60

# Password of the users the suite creates. Not a secret: the users exist only
# while a test runs, on a throwaway server.
USER_PASSWORD = 'Live-Suite-1x9Q'

# Cron expressions only this suite uses, so a leftover schedule can be told
# from one somebody set.
GC_CRON = '0 17 3 29 2 *'
PURGE_CRON = '0 18 3 29 2 *'
SCAN_CRON = '0 19 3 29 2 *'
OWN_CRONS = (GC_CRON, PURGE_CRON, SCAN_CRON)


def pytest_collection_modifyitems(config, items):
    if URL:
        return
    skip = pytest.mark.skip(reason='HARBOR_URL is not set: the live suite needs a throwaway Harbor (see tests/live/conftest.py)')
    for item in items:
        if str(item.fspath).startswith(HERE):
            item.add_marker(skip)


def is_loopback(url):
    """Whether every address the URL's host resolves to is on this machine."""
    host = urlsplit(url).hostname or ''
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        pass
    try:
        found = socket.getaddrinfo(host, None)
    except OSError:
        return False
    return bool(found) and all(ipaddress.ip_address(entry[4][0]).is_loopback for entry in found)


class Api(object):
    """Plain HTTP to Harbor's API, for what the tests set up and look at beside the modules."""

    def __init__(self, url, username, password):
        self.url = url
        self.username = username
        self.password = password
        # An opener of its own, without cookies: ansible-core's open_url installs a global one, and a
        # request that carries Harbor's session cookie needs a CSRF token as well.
        self.opener = urllib.request.build_opener()

    def call(self, method, path, body=None, username=None, password=None, anonymous=False):
        """(status, body, headers); the body parsed when it is JSON."""
        request = urllib.request.Request(
            self.url + '/api/v2.0' + path, method=method,
            data=None if body is None else json.dumps(body).encode())
        if body is not None:
            request.add_header('Content-Type', 'application/json')
        if not anonymous:
            pair = '%s:%s' % (username or self.username, password or self.password)
            request.add_header('Authorization', 'Basic ' + base64.b64encode(pair.encode()).decode())
        try:
            with self.opener.open(request, timeout=TIMEOUT) as response:
                return response.status, parse(response.read()), dict(response.headers)
        except urllib.error.HTTPError as error:
            return error.code, parse(error.read()), dict(error.headers)

    def ok(self, method, path, body=None, expect=(200, 201), **kwargs):
        """call(), failing the test unless the status is one of `expect`."""
        status, answer, headers = self.call(method, path, body, **kwargs)
        assert status in expect, '%s %s answered HTTP %s: %s' % (method, path, status, answer)
        return answer, headers

    def listing(self, path):
        """Every row of a list endpoint (the suite's own lists fit in one page)."""
        sep = '&' if '?' in path else '?'
        answer, dummy = self.ok('GET', '%s%spage=1&page_size=100' % (path, sep))
        return answer or []

    # -- what the suite creates beside the modules --------------------------------

    def projects(self, name):
        return [p for p in self.listing('/projects?name=%s' % quote(name)) if p['name'] == name]

    def create_project(self, name, public=False):
        dummy, headers = self.ok('POST', '/projects', dict(
            project_name=name, metadata=dict(public='true' if public else 'false')))
        return int(header(headers, 'Location').rsplit('/', 1)[1])

    def create_user(self, name):
        self.ok('POST', '/users', dict(username=name, email='%s@example.invalid' % name, realname=name,
                                       password=USER_PASSWORD))

    def add_member(self, project_id, username, role_id=1):
        """role_id 1 is a project admin."""
        self.ok('POST', '/projects/%d/members' % project_id, dict(role_id=role_id, member_user=dict(username=username)))

    def schedule(self, path):
        """A schedule as Harbor stores it; {} when there is none, or no scanner to have one for (412)."""
        answer, dummy = self.ok('GET', path, expect=(200, 412))
        return answer if isinstance(answer, dict) and 'errors' not in answer else {}

    # -- cleaning up --------------------------------------------------------------

    def delete_project(self, project):
        pid = project['project_id']
        retention = (project.get('metadata') or {}).get('retention_id')
        if retention:
            self.call('DELETE', '/retentions/%s' % retention)
        for rule in self.listing('/projects/%d/immutabletagrules' % pid):
            self.ok('DELETE', '/projects/%d/immutabletagrules/%d' % (pid, rule['id']))
        for hook in self.listing('/projects/%d/webhook/policies' % pid):
            self.ok('DELETE', '/projects/%d/webhook/policies/%d' % (pid, hook['id']))
        for robot in self.listing('/robots?q=%s' % quote('Level=project,ProjectID=%d' % pid)):
            self.ok('DELETE', '/robots/%d' % robot['id'])
        self.ok('DELETE', '/projects/%d' % pid)

    def sweep(self):
        """Take everything named live-... off the server, and the suite's own schedules."""
        for rule in self.listing('/replication/policies'):
            if rule['name'].startswith(PREFIX):
                self.ok('DELETE', '/replication/policies/%d' % rule['id'])
        for project in self.listing('/projects?name=%s' % PREFIX):
            if project['name'].startswith(PREFIX):
                self.delete_project(project)
        for registry in self.listing('/registries'):
            if registry['name'].startswith(PREFIX):
                self.ok('DELETE', '/registries/%d' % registry['id'])
        for robot in self.listing('/robots?q=%s' % quote('name=~%s' % PREFIX)):
            # Harbor shows a system robot as <prefix><name>; the prefix is a setting.
            if PREFIX in robot['name']:
                self.ok('DELETE', '/robots/%d' % robot['id'])
        for user in self.listing('/users?q=%s' % quote('username=~%s' % PREFIX)):
            if user['username'].startswith(PREFIX):
                self.ok('DELETE', '/users/%d' % user['user_id'])
        for path in ('/system/gc/schedule', '/system/purgeaudit/schedule', '/system/scanAll/schedule'):
            if cron_of(self.schedule(path)) in OWN_CRONS:
                self.ok('PUT', path, dict(schedule=dict(type='None', cron='')))


def parse(raw):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return raw.decode('utf-8', 'replace')


def header(headers, name):
    """A response header, whatever case the server wrote it in."""
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return None


def cron_of(schedule):
    return ((schedule or {}).get('schedule') or {}).get('cron')


@pytest.fixture(scope='session')
def api():
    """The server, checked once: on this machine, and the administrator is accepted."""
    if not is_loopback(URL) and os.environ.get(ALLOW_REMOTE) != '1':
        pytest.exit('%s is not on this machine. The live suite creates, changes and deletes objects, settings and '
                    'schedules, so it only runs against a throwaway server. If this one is throwaway too, set %s=1.'
                    % (URL, ALLOW_REMOTE), returncode=2)
    if not PASSWORD:
        pytest.exit('set HARBOR_PASSWORD to the password of %s' % USERNAME, returncode=2)
    server = Api(URL, USERNAME, PASSWORD)
    status, info, dummy = server.call('GET', '/systeminfo')
    if status != 200 or not isinstance(info, dict) or not info.get('harbor_version'):
        # Not retried: a second wrong password would only lock the user again.
        pytest.exit('Harbor at %s does not accept the credentials of %s (HTTP %s, no harbor_version).'
                    % (URL, USERNAME, status), returncode=2)
    status, me, dummy = server.call('GET', '/users/current')
    if status != 200 or not me.get('sysadmin_flag'):
        pytest.exit('%s is not an administrator of %s; the live suite needs one.' % (USERNAME, URL), returncode=2)
    server.version = info['harbor_version']
    server.minor = tuple(int(part) for part in info['harbor_version'].lstrip('v').split('.')[:2])
    server.sweep()
    yield server
    server.sweep()


@contextlib.contextmanager
def module_args(args):
    """Hand `args` to AnsibleModule the way the controller does.

    Not ansible.module_utils.testing.patch_module_args: that file is GPL-3.0
    and this collection is Apache-2.0. basic.py (Simplified BSD) reads these
    two module globals; ansible-core 2.18 has no profile.
    """
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


@pytest.fixture
def run(api, capsys):
    """run(main, args) -> the module's JSON result, from a real run against the server.

    check=True runs in check mode. username / password in `args` log in as
    somebody else than the administrator.
    """
    def call(main, args, check=False):
        full = dict(url=api.url, username=api.username, password=api.password,
                    _ansible_check_mode=check, _ansible_diff=True)
        full.update(args)
        full = dict((key, value) for key, value in full.items() if value is not None)
        capsys.readouterr()
        with module_args(full):
            with pytest.raises(SystemExit):
                main()
        out = capsys.readouterr().out
        result = json.loads(out)
        # ansible-core 2.23 lists what the controller has to mask; it is not part of the result.
        result.pop('_ansible_new_secrets', None)
        return result
    return call


@pytest.fixture
def project(api):
    """A private project of the suite's own, gone again after the test."""
    name = PREFIX + 'project'
    for leftover in api.projects(name):
        api.delete_project(leftover)
    api.create_project(name)
    yield name
    for leftover in api.projects(name):
        api.delete_project(leftover)


@pytest.fixture
def member(api, project):
    """A user who is no administrator of Harbor, but the administrator of the suite's project."""
    name = PREFIX + 'member'
    for leftover in api.listing('/users?q=%s' % quote('username=%s' % name)):
        api.ok('DELETE', '/users/%d' % leftover['user_id'])
    api.create_user(name)
    api.add_member(api.projects(project)[0]['project_id'], name)
    yield dict(username=name, password=USER_PASSWORD)
    for leftover in api.listing('/users?q=%s' % quote('username=%s' % name)):
        api.ok('DELETE', '/users/%d' % leftover['user_id'])


def changed(result):
    """The module's `changed`, with a clear failure when the task failed instead."""
    assert not result.get('failed'), result.get('msg')
    return result['changed']


def wait_out_lock():
    """Let a login lock (1.5 s) pass that a test caused on purpose."""
    time.sleep(2)
