# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""Test helpers that do not depend on the server a collection talks to.

This file is the same, byte for byte, in every collection of the repository
(tools/tests/test_shared_helpers.py checks that). What differs per collection,
the routes a fake server starts with and how a URL is taken apart, is in
conftest.py next to it.
"""

import contextlib
import copy
import io
import json
import os
from urllib.error import HTTPError, URLError

import pytest

from ansible.module_utils import basic

try:
    from ansible.module_utils._internal import _secrets
except ImportError:
    # ansible-core up to 2.22: modules mask their own results, see visible_result().
    _secrets = None

# What ansible-core puts where a secret was.
MASK = '$REDACTED$'
# Shorter values are not registered as secrets by ansible-core.
SHORTEST_SECRET = 4


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


def fixture_versions(fixtures_dir):
    """The recorded server versions: one directory per major.minor."""
    return sorted(d for d in os.listdir(fixtures_dir) if os.path.isdir(os.path.join(fixtures_dir, d)))


def fixture_areas(fixtures_dir, version):
    """The area files of one version, without their extension."""
    return sorted(name[:-len('.json')] for name in os.listdir(os.path.join(fixtures_dir, version)) if name.endswith('.json'))


def load_fixtures(fixtures_dir, version):
    """All recorded responses of one version, merged across area files."""
    responses = {}
    for area in fixture_areas(fixtures_dir, version):
        with open(os.path.join(fixtures_dir, version, area + '.json')) as f:
            recorded = json.load(f)['responses']
        clash = sorted(set(recorded) & set(responses))
        if clash:
            raise AssertionError('fixtures/%s/%s.json repeats response names %s' % (version, area, ', '.join(clash)))
        responses.update(recorded)
    return responses


class FakeHeaders(dict):
    """Enough of http.client.HTTPMessage for the clients: items()."""


class FakeResponse(object):
    def __init__(self, status, body, headers=None):
        self.status = status
        self.raw = b'' if body is None else json.dumps(body).encode()
        self.headers = FakeHeaders(headers or {})

    def getcode(self):
        return self.status

    def read(self):
        return self.raw


class FakeServer(object):
    """Answers each (method, path) from a queue of responses.

    A response is a recorded fixture ({"status", "body"} and, where the
    recorder keeps them, "headers") or an exception instance to raise. The
    last response for a route repeats.

    A collection's conftest.py subclasses this: ROUTES are the routes every
    test starts with, and split() says which part of a URL is the path.
    """

    ROUTES = ()

    def __init__(self, fixtures):
        self.fixtures = fixtures
        self.routes = {}
        self.requests = []
        for method, path, name in self.ROUTES:
            self.route(method, path, name)

    def split(self, url):
        """(path, more) for a URL: the key requests are routed by, and what else to record of it."""
        raise NotImplementedError('no split() for %s' % url)

    def response(self, name):
        return copy.deepcopy(self.fixtures[name])

    def route(self, method, path, *responses):
        self.routes[(method, path)] = [self.response(r) if isinstance(r, str) else r for r in responses]

    def calls(self, method=None, path=None):
        return [r for r in self.requests
                if (method is None or r['method'] == method) and (path is None or r['path'] == path)]

    def __call__(self, url, data=None, headers=None, method=None, **kwargs):
        path, more = self.split(url)
        self.requests.append(dict(
            more, method=method, path=path, headers=headers or {},
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


def _masker(secrets):
    """mask(text) for the secrets a module reported, as the controller of that ansible-core masks them."""
    # A module that reports its secrets comes from an ansible-core that has this class.
    masker = _secrets.SecretMasker()
    masker.register_secret_texts(str(s) for s in secrets)
    return lambda text: masker.mask_string(text, mask_placeholder=MASK)


def _masked(value, mask):
    """`value` with `mask` applied to every string in it, keys included, and to numbers long enough to be a secret."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        return mask(value)
    if isinstance(value, (int, float)):
        text = str(value)
        if len(text) < SHORTEST_SECRET:
            return value
        hidden = mask(text)
        return value if hidden == text else hidden
    if isinstance(value, dict):
        return dict((_masked(k, mask), _masked(v, mask)) for k, v in value.items())
    if isinstance(value, list):
        return [_masked(v, mask) for v in value]
    return value


def visible_result(raw):
    """What a user gets to see of a module's raw result.

    Up to ansible-core 2.22 a module takes the values of its no_log options
    out of its result itself, so the raw result is what the user sees.

    Later versions leave that to the controller: the module adds the secrets
    it knows as `_ansible_new_secrets`, and the controller removes that key,
    registers the values and masks every occurrence of them, in keys and
    values, before a callback gets the result. This does the same, with a
    masker that knows only this result's secrets, so one test cannot hide
    what another leaks. A secret the module did not report stays as it is.
    """
    if not isinstance(raw, dict) or '_ansible_new_secrets' not in raw:
        return raw
    result = dict(raw)
    secrets = result.pop('_ansible_new_secrets') or []
    return _masked(result, _masker(secrets)) if secrets else result


def run(main, args, connection, capsys, check_mode=False):
    """Run a module's main() with `args` on top of `connection`; the result as the user sees it."""
    full = dict(connection, _ansible_check_mode=check_mode, _ansible_diff=True)
    full.update(args)
    # None removes an option entirely: AnsibleModule counts a key that is
    # present as set, even when its value is None.
    full = dict((k, v) for k, v in full.items() if v is not None)
    with patch_module_args(full):
        with pytest.raises(SystemExit):
            main()
    return visible_result(json.loads(capsys.readouterr().out))


def transport_error():
    return URLError('connection reset by peer')
