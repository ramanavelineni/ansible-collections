# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""Test harness: runs modules against a fake Harbor built from recorded responses.

fixtures/<major.minor>/<area>.json hold real responses (status, body and the
Location / X-Total-Count headers) recorded from throwaway servers by
tools/record_harbor_fixtures.py. Every area file of a version is loaded as
one set. Tests route requests to those responses and assert on the requests
the module sent.
"""

import contextlib
import copy
import io
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

import pytest

from ansible.module_utils import basic

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')
# One directory per Harbor major.minor, one file per recorded area.
VERSIONS = sorted(d for d in os.listdir(FIXTURES_DIR) if os.path.isdir(os.path.join(FIXTURES_DIR, d)))
PATCH_TARGET = 'ansible_collections.ramanavelineni.harbor.plugins.module_utils.harbor.open_url'

CONNECTION = dict(url='https://harbor.example.com', username='admin', password='s3cret-pw')


@contextlib.contextmanager
def patch_module_args(args=None):
    """Expose `args` to AnsibleModule, the way the controller passes them.

    Deliberately not ansible.module_utils.testing.patch_module_args: that file
    carries ansible-core's GPL-3.0, and this collection is Apache-2.0. basic.py
    (Simplified BSD) reads these two module globals; 2.18 has no profile.
    """
    payload = json.dumps(dict(ANSIBLE_MODULE_ARGS=args or {})).encode()
    saved = dict((name, getattr(basic, name)) for name in ('_ANSIBLE_ARGS', '_ANSIBLE_PROFILE') if hasattr(basic, name))
    basic._ANSIBLE_ARGS = payload
    if '_ANSIBLE_PROFILE' in saved:
        basic._ANSIBLE_PROFILE = 'legacy'
    try:
        yield
    finally:
        for name, value in saved.items():
            setattr(basic, name, value)


def load_fixtures(version):
    """All recorded responses of one version, merged across area files."""
    responses = {}
    directory = os.path.join(FIXTURES_DIR, version)
    for name in sorted(os.listdir(directory)):
        if not name.endswith('.json'):
            continue
        with open(os.path.join(directory, name)) as f:
            area = json.load(f)['responses']
        clash = sorted(set(area) & set(responses))
        if clash:
            raise AssertionError('fixtures/%s/%s repeats response names %s' % (version, name, ', '.join(clash)))
        responses.update(area)
    return responses


class FakeHeaders(dict):
    """Enough of http.client.HTTPMessage for the client: items()."""


class FakeResponse(object):
    def __init__(self, status, body, headers):
        self.status = status
        self.raw = b'' if body is None else json.dumps(body).encode()
        self.headers = FakeHeaders(headers or {})

    def getcode(self):
        return self.status

    def read(self):
        return self.raw


class FakeServer(object):
    """Answers each (method, path) from a queue of responses; the query string is ignored.

    A response is a recorded fixture ({"status", "body", "headers"}) or an
    exception instance to raise. The last response for a route repeats.
    """

    def __init__(self, fixtures):
        self.fixtures = fixtures
        self.routes = {}
        self.requests = []
        self.route('GET', '/systeminfo', 'systeminfo')

    def response(self, name):
        return copy.deepcopy(self.fixtures[name])

    def route(self, method, path, *responses):
        self.routes[(method, path)] = [self.response(r) if isinstance(r, str) else r for r in responses]

    def calls(self, method=None, path=None):
        return [r for r in self.requests
                if (method is None or r['method'] == method) and (path is None or r['path'] == path)]

    def __call__(self, url, data=None, headers=None, method=None, **kwargs):
        parts = urlsplit(url)
        path = parts.path.split('/api/v2.0', 1)[1]
        self.requests.append(dict(
            method=method, path=path, query=parse_qs(parts.query), headers=headers or {},
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
        return FakeResponse(answer['status'], answer['body'], answer.get('headers'))


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
        full = dict((k, v) for k, v in full.items() if v is not None)
        with patch_module_args(full):
            with pytest.raises(SystemExit):
                main()
        return json.loads(capsys.readouterr().out)
    return run


def transport_error():
    return URLError('connection reset by peer')
