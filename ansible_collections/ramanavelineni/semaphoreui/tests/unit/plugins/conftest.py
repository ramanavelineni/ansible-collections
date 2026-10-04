# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""Test harness: runs modules against a fake Semaphore built from recorded responses.

fixtures/<major.minor>/<area>.json hold real responses recorded from
throwaway servers by tools/record_semaphoreui_fixtures.py. Tests route requests to
those responses and assert on the requests the module sent.

What does not depend on Semaphore is in utils.py; the names tests import from
here are kept.
"""

import os

import pytest

from ansible_collections.ramanavelineni.semaphoreui.tests.unit.plugins import utils

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')
# One directory per Semaphore major.minor, one file per recorded area.
VERSIONS = utils.fixture_versions(FIXTURES_DIR)
PATCH_TARGET = 'ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.semaphore.open_url'

CONNECTION = dict(url='https://semaphore.example.com', username='admin', password='s3cret-pw')

# Tests import these from here.
FakeResponse = utils.FakeResponse
patch_module_args = utils.patch_module_args
transport_error = utils.transport_error


def load_fixtures(version):
    """All recorded responses of one version, merged across area files."""
    return utils.load_fixtures(FIXTURES_DIR, version)


class FakeServer(utils.FakeServer):
    """A fake Semaphore: a request is routed by what follows /api, query string included."""

    ROUTES = (
        ('POST', '/auth/login', 'login'),
        ('POST', '/auth/logout', 'logout'),
        ('GET', '/info', 'info'),
        ('GET', '/apps', 'apps'),
    )

    def split(self, url):
        return url.split('/api', 1)[1], {}


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
