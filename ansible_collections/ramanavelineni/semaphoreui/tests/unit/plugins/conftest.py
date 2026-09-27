# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""Test harness: runs modules against a fake Semaphore built from recorded responses.

fixtures/<major.minor>.json holds real responses recorded from throwaway
servers by tools/record_semaphoreui_fixtures.py. Tests route requests to
those responses and assert on the requests the module sent.
"""

import contextlib
import copy
import io
import json
import os
from urllib.error import HTTPError, URLError

import pytest

from ansible.module_utils import basic

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')
VERSIONS = sorted(f[:-len('.json')] for f in os.listdir(FIXTURES_DIR) if f.endswith('.json'))
PATCH_TARGET = 'ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.semaphore.open_url'

CONNECTION = dict(url='https://semaphore.example.com', username='admin', password='s3cret-pw')


try:
    from ansible.module_utils.testing import patch_module_args
except ImportError:  # ansible-core 2.18
    @contextlib.contextmanager
    def patch_module_args(args=None):
        payload = json.dumps(dict(ANSIBLE_MODULE_ARGS=args or {})).encode()
        original = basic._ANSIBLE_ARGS
        basic._ANSIBLE_ARGS = payload
        try:
            yield
        finally:
            basic._ANSIBLE_ARGS = original


def load_fixtures(version):
    with open(os.path.join(FIXTURES_DIR, '%s.json' % version)) as f:
        return json.load(f)['responses']


class FakeResponse(object):
    def __init__(self, status, body):
        self.status = status
        self.raw = b'' if body is None else json.dumps(body).encode()

    def getcode(self):
        return self.status

    def read(self):
        return self.raw


class FakeServer(object):
    """Answers each (method, path) from a queue of responses.

    A response is a recorded fixture ({"status", "body"}) or an exception
    instance to raise. The last response for a route repeats.
    """

    def __init__(self, fixtures):
        self.fixtures = fixtures
        self.routes = {}
        self.requests = []
        self.route('POST', '/auth/login', 'login')
        self.route('POST', '/auth/logout', 'logout')
        self.route('GET', '/info', 'info')
        self.route('GET', '/apps', 'apps')

    def response(self, name):
        return copy.deepcopy(self.fixtures[name])

    def route(self, method, path, *responses):
        self.routes[(method, path)] = [self.response(r) if isinstance(r, str) else r for r in responses]

    def calls(self, method=None, path=None):
        return [r for r in self.requests
                if (method is None or r['method'] == method) and (path is None or r['path'] == path)]

    def __call__(self, url, data=None, headers=None, method=None, **kwargs):
        path = url.split('/api', 1)[1]
        self.requests.append(dict(
            method=method, path=path, headers=headers or {},
            body=json.loads(data) if data else None, kwargs=kwargs))
        queue = self.routes.get((method, path))
        if not queue:
            raise AssertionError('unexpected request %s %s' % (method, path))
        answer = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(answer, Exception):
            raise answer
        if answer['status'] >= 400:
            raw = b'' if answer['body'] is None else json.dumps(answer['body']).encode()
            raise HTTPError(url, answer['status'], 'error', {}, io.BytesIO(raw))
        return FakeResponse(answer['status'], answer['body'])


@pytest.fixture(params=VERSIONS)
def server(request, mocker):
    fake = FakeServer(load_fixtures(request.param))
    fake.version = request.param
    mocker.patch(PATCH_TARGET, side_effect=fake)
    mocker.patch('time.sleep')
    return fake


@pytest.fixture
def run_module(capsys):
    """run_module(main, args) -> the module's JSON result."""
    def run(main, args, check_mode=False):
        full = dict(CONNECTION, _ansible_check_mode=check_mode, _ansible_diff=True)
        full.update(args)
        # None removes an option entirely: AnsibleModule counts a key that is
        # present as set, even when its value is None.
        full = dict((k, v) for k, v in full.items() if v is not None)
        with patch_module_args(full):
            with pytest.raises(SystemExit):
                main()
        return json.loads(capsys.readouterr().out)
    return run


def transport_error():
    return URLError('connection reset by peer')
