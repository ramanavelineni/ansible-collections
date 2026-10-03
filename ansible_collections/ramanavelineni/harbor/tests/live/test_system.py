# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""System-wide things: the schedules, the configuration and the info module.

Each test puts back what it found: the schedules and the setting it changes
are the server's own, not objects of the suite.
"""

import json

import pytest

from ansible_collections.ramanavelineni.harbor.plugins.modules import (
    configuration, configuration_info, garbage_collection, garbage_collection_info, info, log_rotation,
    log_rotation_info, scan_all, scan_all_info,
)
from ansible_collections.ramanavelineni.harbor.tests.live.conftest import GC_CRON, PURGE_CRON, SCAN_CRON, changed

GC_PATH = '/system/gc/schedule'
PURGE_PATH = '/system/purgeaudit/schedule'


@pytest.fixture
def restore_schedule(api):
    """restore_schedule(path): remember the schedule now, and put it back after the test."""
    remembered = []

    def remember(path):
        remembered.append((path, api.schedule(path)))

    yield remember
    for path, before in remembered:
        if (before.get('schedule') or {}).get('type') in (None, 'None'):
            now = api.schedule(path)
            if (now.get('schedule') or {}).get('type') not in (None, 'None'):
                api.ok('PUT', path, dict(schedule=dict(type='None', cron='')))
        else:
            api.ok('PUT', path, dict(schedule=before['schedule'], parameters=before_parameters(before)))


def before_parameters(schedule):
    """A stored schedule's parameters as the API takes them back (Harbor returns them as a JSON string)."""
    raw = schedule.get('job_parameters')
    return json.loads(raw) if raw else schedule.get('parameters') or {}


def test_info(api, run):
    result = run(info.main, dict())
    assert not result.get('failed'), result.get('msg')
    assert result['version'] == api.version
    assert result['tested'] is True
    assert result['info']['harbor_version'] == api.version


def test_garbage_collection_schedule(api, run, restore_schedule):
    restore_schedule(GC_PATH)
    before = run(garbage_collection_info.main, dict())['garbage_collection']
    wanted = dict(schedule='custom', cron=GC_CRON, delete_untagged=True, workers=2)

    predicted = run(garbage_collection.main, wanted, check=True)
    assert changed(predicted) is True
    assert run(garbage_collection_info.main, dict())['garbage_collection'] == before

    stored = run(garbage_collection.main, wanted)
    assert changed(stored) is True
    assert stored['garbage_collection']['schedule'] == 'custom'
    assert stored['garbage_collection']['cron'] == GC_CRON
    assert stored['garbage_collection']['delete_untagged'] is True
    assert stored['garbage_collection']['workers'] == 2

    again = run(garbage_collection.main, wanted)
    assert changed(again) is False
    assert again['garbage_collection'] == stored['garbage_collection']
    read = run(garbage_collection_info.main, dict(runs=3))
    assert read['garbage_collection'] == stored['garbage_collection']
    assert isinstance(read['runs'], list)

    # Only a setting changes: the schedule stays.
    update = dict(workers=3)
    would = run(garbage_collection.main, update, check=True)
    assert changed(would) is True
    assert run(garbage_collection_info.main, dict())['garbage_collection'] == stored['garbage_collection']
    updated = run(garbage_collection.main, update)
    assert changed(updated) is True
    assert updated['garbage_collection']['workers'] == 3
    assert updated['garbage_collection']['cron'] == GC_CRON
    assert updated['garbage_collection']['delete_untagged'] is True
    assert changed(run(garbage_collection.main, update)) is False

    removed = run(garbage_collection.main, dict(schedule='none'))
    assert changed(removed) is True
    assert removed['garbage_collection']['schedule'] == 'none'
    assert changed(run(garbage_collection.main, dict(schedule='none'))) is False


def test_garbage_collection_settings_without_an_option(api, run, restore_schedule):
    """A setting the module has no option for is not lost by a change the module makes.

    Harbor 2.14.4 and 2.15.2 do not store a dry_run sent with a garbage
    collection schedule at all, so there is nothing to lose there; the test
    says which of the two it saw. A Harbor that does store it must still have
    it after the module changed something else.
    """
    restore_schedule(GC_PATH)
    assert changed(run(garbage_collection.main, dict(schedule='custom', cron=GC_CRON, delete_untagged=True, workers=1))) is True
    stored = api.schedule(GC_PATH)
    api.ok('PUT', GC_PATH, dict(schedule=dict(type='Custom', cron=GC_CRON),
                                parameters=dict(before_parameters(stored), dry_run=True)))
    kept_by_harbor = before_parameters(api.schedule(GC_PATH)).get('dry_run')

    assert changed(run(garbage_collection.main, dict(workers=2))) is True
    after = before_parameters(api.schedule(GC_PATH))
    assert after.get('workers') == 2
    assert after.get('delete_untagged') is True
    assert after.get('dry_run') == kept_by_harbor


def test_delete_tag_needs_harbor_2_15(api, run, restore_schedule):
    restore_schedule(GC_PATH)
    result = run(garbage_collection.main, dict(schedule='custom', cron=GC_CRON, delete_tag=True))
    if api.minor >= (2, 15):
        assert changed(result) is True
        assert result['garbage_collection']['delete_tag'] is True
        assert changed(run(garbage_collection.main, dict(schedule='custom', cron=GC_CRON, delete_tag=True))) is False
    else:
        assert result.get('failed') is True
        assert '2.15' in result['msg']
        assert cron_now(api, GC_PATH) != GC_CRON


def cron_now(api, path):
    return (api.schedule(path).get('schedule') or {}).get('cron')


def test_log_rotation_schedule(api, run, restore_schedule):
    restore_schedule(PURGE_PATH)
    before = run(log_rotation_info.main, dict())['log_rotation']
    wanted = dict(schedule='custom', cron=PURGE_CRON, audit_retention_hour=720, include_event_types=['create_artifact'], dry_run=True)

    predicted = run(log_rotation.main, wanted, check=True)
    assert changed(predicted) is True
    assert run(log_rotation_info.main, dict())['log_rotation'] == before

    stored = run(log_rotation.main, wanted)
    assert changed(stored) is True
    assert stored['log_rotation']['cron'] == PURGE_CRON
    assert stored['log_rotation']['audit_retention_hour'] == 720
    assert stored['log_rotation']['include_event_types'] == ['create_artifact']
    assert stored['log_rotation']['dry_run'] is True

    again = run(log_rotation.main, wanted)
    assert changed(again) is False
    assert again['log_rotation'] == stored['log_rotation']
    read = run(log_rotation_info.main, dict(runs=3))
    assert read['log_rotation'] == stored['log_rotation']
    assert isinstance(read['runs'], list)

    update = dict(audit_retention_hour=1440)
    would = run(log_rotation.main, update, check=True)
    assert changed(would) is True
    updated = run(log_rotation.main, update)
    assert changed(updated) is True
    assert updated['log_rotation']['audit_retention_hour'] == 1440
    assert updated['log_rotation']['cron'] == PURGE_CRON
    assert changed(run(log_rotation.main, update)) is False

    # An event type the server does not list is refused before anything is written.
    refused = run(log_rotation.main, dict(include_event_types=['live_suite_no_such_event']))
    assert refused.get('failed') is True
    assert run(log_rotation_info.main, dict())['log_rotation'] == updated['log_rotation']

    assert changed(run(log_rotation.main, dict(schedule='none'))) is True
    assert changed(run(log_rotation.main, dict(schedule='none'))) is False


def test_scan_all_without_a_scanner(api, run):
    """A Harbor without a scanner has no scan-all schedule; the modules say so instead of crashing.

    With a scanner installed this test is skipped: the suite does not set a
    scan schedule on a server that would then scan.
    """
    status = api.call('GET', '/system/scanAll/schedule')[0]
    if status != 412:
        pytest.skip('this Harbor has a scanner; the scan-all schedule is left alone')
    read = run(scan_all_info.main, dict())
    wrote = run(scan_all.main, dict(schedule='custom', cron=SCAN_CRON))
    for result in (read, wrote):
        assert result.get('failed') is True
        assert 'scanner' in result['msg']
        assert 'Traceback' not in str(result) and 'Unexpected' not in result['msg']


def test_configuration(api, run):
    before = run(configuration_info.main, dict())
    assert not before.get('failed'), before.get('msg')
    original = before['configuration']['session_timeout']
    wanted = original + 7
    try:
        would = run(configuration.main, dict(settings=dict(session_timeout=wanted)), check=True)
        assert changed(would) is True
        assert would['changed_settings'] == ['session_timeout']
        assert run(configuration_info.main, dict())['configuration']['session_timeout'] == original

        stored = run(configuration.main, dict(settings=dict(session_timeout=wanted)))
        assert changed(stored) is True
        assert stored['configuration']['session_timeout'] == wanted
        assert changed(run(configuration.main, dict(settings=dict(session_timeout=wanted)))) is False
        # A value that went through a template arrives as a string.
        assert changed(run(configuration.main, dict(settings=dict(session_timeout=str(wanted))))) is False
        assert run(configuration_info.main, dict())['configuration'] == stored['configuration']

        # An unknown key fails before anything is sent; Harbor itself would ignore it silently.
        refused = run(configuration.main, dict(settings=dict(live_suite_no_such_setting=1)))
        assert refused.get('failed') is True
    finally:
        restored = run(configuration.main, dict(settings=dict(session_timeout=original)))
        assert not restored.get('failed'), restored.get('msg')
    assert run(configuration_info.main, dict())['configuration']['session_timeout'] == original


def test_configuration_hides_the_secrets(api, run):
    """What configuration_info returns holds no secret Harbor can be asked for."""
    shown = run(configuration_info.main, dict())['configuration']
    raw, dummy = api.ok('GET', '/configurations')
    assert set(shown) <= set(raw)
    for key in shown:
        assert 'secret' not in key and 'password' not in key, key
