# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""Test harness: runs modules against a fake Harbor built from recorded responses.

fixtures/<major.minor>/<area>.json hold real responses (status, body and the
Location / X-Total-Count headers) recorded from throwaway servers by
tools/record_harbor_fixtures.py. Every area file of a version is loaded as
one set. Tests route requests to those responses and assert on the requests
the module sent.

What does not depend on Harbor is in utils.py; the names tests import from
here are kept.
"""

import os
from urllib.parse import parse_qs, urlsplit

import pytest

from ansible_collections.ramanavelineni.harbor.tests.unit.plugins import utils

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')
# One directory per Harbor major.minor, one file per recorded area.
VERSIONS = utils.fixture_versions(FIXTURES_DIR)
PATCH_TARGET = 'ansible_collections.ramanavelineni.harbor.plugins.module_utils.harbor.open_url'

CONNECTION = dict(url='https://harbor.example.com', username='admin', password='s3cret-pw')

# Tests import these from here.
FakeHeaders = utils.FakeHeaders
FakeResponse = utils.FakeResponse
patch_module_args = utils.patch_module_args
transport_error = utils.transport_error


def load_fixtures(version):
    """All recorded responses of one version, merged across area files."""
    return utils.load_fixtures(FIXTURES_DIR, version)


class FakeServer(utils.FakeServer):
    """A fake Harbor: a request is routed by its path under /api/v2.0; the query string is recorded, not routed by."""

    ROUTES = (
        ('GET', '/systeminfo', 'systeminfo'),
    )

    def split(self, url):
        parts = urlsplit(url)
        return parts.path.split('/api/v2.0', 1)[1], dict(query=parse_qs(parts.query))


@pytest.fixture(params=VERSIONS)
def server(request, mocker):
    fake = FakeServer(load_fixtures(request.param))
    fake.version = request.param
    mocker.patch(PATCH_TARGET, side_effect=fake)
    mocker.patch('time.sleep')
    return fake


@pytest.fixture
def run_module(capsys):
    """run_module(main, args) -> the module's result, as a user sees it."""
    def run(main, args, check_mode=False):
        return utils.run(main, args, CONNECTION, capsys, check_mode=check_mode)
    return run
