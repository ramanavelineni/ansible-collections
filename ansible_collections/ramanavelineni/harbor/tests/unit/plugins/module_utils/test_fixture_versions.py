# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""The recorded Harbor versions and the versions the collection calls tested are the same set."""

import json
import os

import pytest

from ansible_collections.ramanavelineni.harbor.plugins.module_utils.harbor import TESTED_VERSIONS
from ansible_collections.ramanavelineni.harbor.tests.unit.plugins import utils
from ansible_collections.ramanavelineni.harbor.tests.unit.plugins.conftest import FIXTURES_DIR, VERSIONS


def test_every_recorded_version_is_called_tested():
    # Without this a new fixtures directory would run through every test and
    # the modules would still warn that the version is untested.
    assert sorted(set(VERSIONS) - set(TESTED_VERSIONS)) == []


def test_every_tested_version_is_recorded():
    # The other way round: a version added to TESTED_VERSIONS alone has no test at all.
    assert sorted(set(TESTED_VERSIONS) - set(VERSIONS)) == []


def test_no_version_is_listed_twice():
    assert len(set(TESTED_VERSIONS)) == len(TESTED_VERSIONS)


def test_every_version_has_the_same_areas():
    # A version recorded without one area would fail only the tests of that
    # area, with a KeyError that says nothing about a missing file.
    areas = dict((version, utils.fixture_areas(FIXTURES_DIR, version)) for version in VERSIONS)
    everywhere = sorted(set(area for names in areas.values() for area in names))
    assert areas == dict((version, everywhere) for version in VERSIONS)


def test_every_version_has_the_same_responses():
    # A response recorded for one version only can be used by no test that
    # runs on all of them.
    names = dict((version, sorted(utils.load_fixtures(FIXTURES_DIR, version))) for version in VERSIONS)
    everywhere = sorted(set(name for found in names.values() for name in found))
    missing = dict((version, sorted(set(everywhere) - set(found))) for version, found in names.items())
    assert missing == dict((version, []) for version in VERSIONS)


@pytest.mark.parametrize('version', VERSIONS)
def test_files_were_recorded_from_the_version_of_their_directory(version):
    for area in utils.fixture_areas(FIXTURES_DIR, version):
        with open(os.path.join(FIXTURES_DIR, version, area + '.json')) as f:
            recorded_from = json.load(f)['recorded_from']
        assert recorded_from.lstrip('v').startswith(version + '.'), '%s/%s.json was recorded from %s' % (version, area, recorded_from)
