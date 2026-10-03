# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

import copy
import json

import pytest

from ansible_collections.ramanavelineni.harbor.plugins.modules import (
    configuration,
    configuration_info,
    garbage_collection,
    garbage_collection_info,
    log_rotation,
    log_rotation_info,
    scan_all,
    scan_all_info,
)

GC = '/system/gc/schedule'
PURGE = '/system/purgeaudit/schedule'
SCAN_ALL = '/system/scanAll/schedule'


def ok(body=None):
    return dict(status=200, body=body, headers={})


def scan_all_schedule(cron='0 0 5 * * 0', kind='Custom'):
    """Scan All can't be recorded without a vulnerability scanner; this follows its swagger model."""
    return ok(dict(id=3, status='Scheduled', schedule=dict(type=kind, cron=cron), parameters={},
                   creation_time='2026-09-27T20:00:00.000Z', update_time='2026-09-27T20:00:00.000Z'))


# -- configuration ------------------------------------------------------------

def test_configuration_changes_only_differing_keys(server, run_module):
    server.route('GET', '/configurations', 'system_configurations', 'system_configurations_updated')
    server.route('PUT', '/configurations', 'system_configurations_update')
    current = server.fixtures['system_configurations']['body']
    result = run_module(configuration.main, dict(settings=dict(
        banner_message='fixtures-system', session_timeout=45, auth_mode=current['auth_mode']['value'])))
    assert result['changed'] is True
    assert result['changed_settings'] == ['banner_message', 'session_timeout']
    assert server.calls('PUT', '/configurations')[0]['body'] == dict(banner_message='fixtures-system', session_timeout=45)
    assert result['configuration']['session_timeout'] == 45
    assert result['diff']['before']['session_timeout'] == current['session_timeout']['value']


def test_configuration_no_change(server, run_module):
    server.route('GET', '/configurations', 'system_configurations_updated')
    result = run_module(configuration.main, dict(settings=dict(banner_message='fixtures-system', session_timeout=45)))
    assert result['changed'] is False
    assert server.calls('PUT') == []


def test_configuration_check_mode(server, run_module):
    server.route('GET', '/configurations', 'system_configurations')
    result = run_module(configuration.main, dict(settings=dict(session_timeout=45)), check_mode=True)
    assert result['changed'] is True
    assert result['configuration']['session_timeout'] == 45
    assert server.calls('PUT') == []


@pytest.mark.parametrize('settings, message', [
    (dict(no_such_setting=1), 'Unknown setting'),
    (dict(session_timeout='forty'), 'must be an integer'),
    (dict(session_timeout='4.5'), 'must be an integer'),
    (dict(read_only='maybe'), 'must be a boolean'),
    (dict(banner_message=5), 'must be a string'),
    (dict(read_only=1), 'must be a boolean'),
    (dict(session_timeout=True), 'must be an integer'),
    (dict(oidc_client_secret='x'), 'oidc_client_secret option'),
    (dict(uaa_client_secret='x'), 'uaa_client_secret option'),
    (dict(scan_all_policy={}), 'read-only'),
])
def test_configuration_validation(server, run_module, settings, message):
    result = run_module(configuration.main, dict(settings=settings))
    assert result['failed'] is True
    assert message in result['msg']
    assert server.calls('GET', '/configurations') == []


def test_configuration_takes_templated_strings(server, run_module):
    # What "{{ harbor_session_timeout }}" gives on ansible-core 2.18: strings.
    server.route('GET', '/configurations', 'system_configurations', 'system_configurations_updated')
    server.route('PUT', '/configurations', 'system_configurations_update')
    current = server.fixtures['system_configurations']['body']
    result = run_module(configuration.main, dict(settings=dict(
        session_timeout=' 45 ', read_only='Yes', self_registration=str(current['self_registration']['value']))))
    assert result['changed'] is True
    assert sorted(result['changed_settings']) == ['read_only', 'session_timeout']
    assert server.calls('PUT', '/configurations')[0]['body'] == dict(session_timeout=45, read_only=True)


def test_configuration_templated_strings_no_change(server, run_module):
    server.route('GET', '/configurations', 'system_configurations_updated')
    result = run_module(configuration.main, dict(settings=dict(session_timeout='45', read_only='false')))
    assert result['changed'] is False
    assert server.calls('PUT') == []


def test_configuration_server_rejection_reported(server, run_module):
    server.route('GET', '/configurations', 'system_configurations')
    server.route('PUT', '/configurations', 'system_configurations_bad_value')
    result = run_module(configuration.main, dict(settings=dict(session_timeout=1)))
    assert result['failed'] is True
    assert 'must be positive' in result['msg']


def test_write_only_secret_always(server, run_module):
    server.route('GET', '/configurations', 'system_configurations')
    server.route('PUT', '/configurations', 'system_configurations_update')
    result = run_module(configuration.main, dict(oidc_client_secret='s3cr3t-oidc'))
    assert result['changed'] is True
    assert result['changed_settings'] == ['oidc_client_secret']
    assert server.calls('PUT')[0]['body'] == dict(oidc_client_secret='s3cr3t-oidc')
    assert 's3cr3t-oidc' not in json.dumps(result)


def test_write_only_secret_on_create_with_configured_client(server, run_module):
    configured = server.response('system_configurations')
    configured['body']['oidc_client_id']['value'] = 'harbor'
    server.route('GET', '/configurations', configured)
    result = run_module(configuration.main, dict(settings=dict(oidc_client_id='harbor'),
                                                 oidc_client_secret='s3cr3t-oidc', update_secret='on_create'))
    assert result['changed'] is False
    assert server.calls('PUT') == []


def test_write_only_secret_on_create_new_client(server, run_module):
    configured = server.response('system_configurations')
    configured['body']['oidc_client_id']['value'] = 'harbor'
    server.route('GET', '/configurations', configured)
    server.route('PUT', '/configurations', 'system_configurations_update')
    result = run_module(configuration.main, dict(settings=dict(oidc_client_id='harbor-2'),
                                                 oidc_client_secret='s3cr3t-oidc', update_secret='on_create'))
    assert result['changed_settings'] == ['oidc_client_id', 'oidc_client_secret']


def test_write_only_secret_on_create_when_empty(server, run_module):
    server.route('GET', '/configurations', 'system_configurations')
    server.route('PUT', '/configurations', 'system_configurations_update')
    result = run_module(configuration.main, dict(ldap_search_password='pw', update_secret='on_create'))
    assert result['changed_settings'] == ['ldap_search_password']


def test_readable_secret_compared_and_hidden(server, run_module):
    current = server.response('system_configurations')
    current['body']['uaa_client_secret']['value'] = 'uaa-s3cret'
    server.route('GET', '/configurations', current)
    result = run_module(configuration.main, dict(uaa_client_secret='uaa-s3cret'))
    assert result['changed'] is False
    assert 'uaa_client_secret' not in result['configuration']
    assert 'uaa-s3cret' not in json.dumps(result)


def test_configuration_info_hides_secrets(server, run_module):
    current = server.response('system_configurations')
    current['body']['uaa_client_secret']['value'] = 'uaa-s3cret'
    server.route('GET', '/configurations', current)
    result = run_module(configuration_info.main, {})
    assert result['changed'] is False
    assert 'uaa_client_secret' not in result['configuration']
    assert 'uaa-s3cret' not in json.dumps(result)
    assert result['configuration']['auth_mode'] == current['body']['auth_mode']['value']
    assert result['auth_mode_editable'] is current['body']['auth_mode']['editable']


# -- garbage collection -------------------------------------------------------

def test_gc_create(server, run_module):
    server.route('GET', GC, 'system_gc_schedule_none', 'system_gc_schedule_custom')
    server.route('PUT', GC, 'system_gc_schedule_update')
    result = run_module(garbage_collection.main, dict(schedule='custom', cron='0 0 4 * * 0', delete_untagged=True, workers=2))
    assert result['changed'] is True
    assert server.calls('PUT', GC)[0]['body'] == dict(
        schedule=dict(type='Custom', cron='0 0 4 * * 0'), parameters=dict(delete_untagged=True, workers=2))
    gc = result['garbage_collection']
    assert (gc['schedule'], gc['cron'], gc['delete_untagged'], gc['workers']) == ('custom', '0 0 4 * * 0', True, 2)
    assert gc['next_scheduled_time']
    assert result['diff']['before']['schedule'] == 'none'


def test_gc_no_change(server, run_module):
    server.route('GET', GC, 'system_gc_schedule_custom')
    result = run_module(garbage_collection.main, dict(schedule='custom', cron='0 0 4 * * 0', delete_untagged=True, workers=2))
    assert result['changed'] is False
    assert server.calls('PUT') == []


def test_gc_parameter_change_keeps_schedule_and_others(server, run_module):
    server.route('GET', GC, 'system_gc_schedule_custom')
    server.route('PUT', GC, 'system_gc_schedule_update')
    run_module(garbage_collection.main, dict(workers=4))
    body = server.calls('PUT', GC)[0]['body']
    assert body['schedule'] == dict(type='Custom', cron='0 0 4 * * 0')
    assert body['parameters']['workers'] == 4
    assert body['parameters']['delete_untagged'] is True


def test_gc_preset(server, run_module):
    server.route('GET', GC, 'system_gc_schedule_custom')
    server.route('PUT', GC, 'system_gc_schedule_update')
    run_module(garbage_collection.main, dict(schedule='weekly'))
    assert server.calls('PUT', GC)[0]['body']['schedule'] == dict(type='Weekly', cron='0 0 0 * * 0')


def test_gc_remove(server, run_module):
    server.route('GET', GC, 'system_gc_schedule_custom', 'system_gc_schedule_none')
    server.route('PUT', GC, 'system_gc_schedule_update')
    result = run_module(garbage_collection.main, dict(schedule='none'))
    assert result['changed'] is True
    assert server.calls('PUT', GC)[0]['body'] == dict(schedule=dict(type='None'))
    assert result['garbage_collection']['schedule'] == 'none'


def test_gc_check_mode(server, run_module):
    server.route('GET', GC, 'system_gc_schedule_none')
    result = run_module(garbage_collection.main, dict(schedule='daily'), check_mode=True)
    assert result['changed'] is True
    assert result['garbage_collection']['cron'] == '0 0 0 * * *'
    assert server.calls('PUT') == []


def test_gc_never_sends_manual(server, run_module):
    server.route('GET', GC, 'system_gc_schedule_none')
    result = run_module(garbage_collection.main, dict(schedule='manual'))
    assert result['failed'] is True
    assert server.calls('PUT') == [] and server.calls('POST') == []


@pytest.mark.parametrize('args, message', [
    (dict(schedule='custom'), 'needs cron'),
    (dict(schedule='custom', cron='0 4 * * 0'), 'Harbor uses 6'),
    (dict(schedule='daily', cron='0 0 1 * * *'), 'use schedule: custom'),
    (dict(schedule='none', cron='0 0 1 * * *'), 'cron can only be set'),
    (dict(workers=11), 'between 1 and 10'),
])
def test_gc_validation(server, run_module, args, message):
    server.route('GET', GC, 'system_gc_schedule_custom')
    result = run_module(garbage_collection.main, args)
    assert result['failed'] is True
    assert message in result['msg']
    assert server.calls('PUT') == []


def test_gc_settings_need_a_schedule(server, run_module):
    server.route('GET', GC, 'system_gc_schedule_none')
    result = run_module(garbage_collection.main, dict(workers=2))
    assert result['failed'] is True
    assert 'only apply to a schedule' in result['msg']


def test_gc_delete_tag_version(server, run_module):
    server.route('GET', GC, 'system_gc_schedule_custom')
    server.route('PUT', GC, 'system_gc_schedule_update')
    result = run_module(garbage_collection.main, dict(delete_tag=True))
    if server.version == '2.14':
        assert result['failed'] is True
        assert '2.15' in result['msg']
    else:
        assert result['changed'] is True
        assert server.calls('PUT', GC)[0]['body']['parameters']['delete_tag'] is True


def test_gc_hides_redis_url(server, run_module):
    leaky = server.response('system_gc_schedule_custom')
    params = json.loads(leaky['body']['job_parameters'])
    params['redis_url_reg'] = 'redis://:s3cret@redis:6379/1'
    leaky['body']['job_parameters'] = json.dumps(params)
    server.route('GET', GC, leaky)
    server.route('GET', '/system/gc', 'system_gc_history')
    result = run_module(garbage_collection_info.main, {})
    assert 's3cret' not in json.dumps(result)
    assert result['garbage_collection']['workers'] == 2


def test_gc_bad_cron_from_server(server, run_module):
    server.route('GET', GC, 'system_gc_schedule_custom')
    server.route('PUT', GC, 'system_gc_schedule_bad_cron')
    result = run_module(garbage_collection.main, dict(schedule='custom', cron='0 0 4 * * 1'))
    assert result['failed'] is True
    assert 'invalid cron' in result['msg']


def test_gc_info(server, run_module):
    server.route('GET', GC, 'system_gc_schedule_custom')
    server.route('GET', '/system/gc', 'system_gc_history')
    result = run_module(garbage_collection_info.main, dict(runs=5))
    assert result['changed'] is False
    assert result['garbage_collection']['schedule'] == 'custom'
    assert result['runs'] == []
    query = server.calls('GET', '/system/gc')[0]['query']
    assert query['page_size'] == ['5'] and query['sort'] == ['-creation_time']


def test_gc_info_no_runs(server, run_module):
    server.route('GET', GC, 'system_gc_schedule_none')
    result = run_module(garbage_collection_info.main, dict(runs=0))
    assert result['garbage_collection']['schedule'] == 'none'
    assert server.calls('GET', '/system/gc') == []


# -- log rotation --------------------------------------------------------------

LR = dict(schedule='custom', cron='0 0 6 * * *', audit_retention_hour=720,
          include_event_types=['delete_artifact', 'create_artifact'])


def test_lr_create(server, run_module):
    server.route('GET', '/auditlog-exts/events', 'system_event_types')
    server.route('GET', PURGE, 'system_purge_schedule_none', 'system_purge_schedule_custom')
    server.route('PUT', PURGE, 'system_purge_schedule_update')
    result = run_module(log_rotation.main, LR)
    assert result['changed'] is True
    assert server.calls('PUT', PURGE)[0]['body'] == dict(
        schedule=dict(type='Custom', cron='0 0 6 * * *'),
        parameters=dict(audit_retention_hour=720, include_event_types='create_artifact,delete_artifact'))
    lr = result['log_rotation']
    assert lr['include_event_types'] == ['create_artifact', 'delete_artifact']
    assert lr['audit_retention_hour'] == 720


def test_lr_order_of_types_ignored(server, run_module):
    server.route('GET', '/auditlog-exts/events', 'system_event_types')
    server.route('GET', PURGE, 'system_purge_schedule_custom')
    result = run_module(log_rotation.main, dict(LR, include_event_types=['create_artifact', 'delete_artifact']))
    assert result['changed'] is False


def test_lr_create_needs_parameters(server, run_module):
    server.route('GET', PURGE, 'system_purge_schedule_none')
    result = run_module(log_rotation.main, dict(schedule='daily', audit_retention_hour=24))
    assert result['failed'] is True
    assert 'include_event_types' in result['msg']


def test_lr_unknown_event_type(server, run_module):
    server.route('GET', '/auditlog-exts/events', 'system_event_types')
    result = run_module(log_rotation.main, dict(LR, include_event_types=['nope']))
    assert result['failed'] is True
    assert 'Unknown event types nope' in result['msg']


def test_lr_retention_range(server, run_module):
    result = run_module(log_rotation.main, dict(LR, audit_retention_hour=240001))
    assert result['failed'] is True
    assert 'between 1 and 240000' in result['msg']


def test_lr_change_keeps_other_parameters(server, run_module):
    server.route('GET', PURGE, 'system_purge_schedule_custom')
    server.route('PUT', PURGE, 'system_purge_schedule_update')
    run_module(log_rotation.main, dict(audit_retention_hour=168))
    body = server.calls('PUT', PURGE)[0]['body']
    assert body['parameters'] == dict(audit_retention_hour=168, include_event_types='create_artifact,delete_artifact')
    assert body['schedule'] == dict(type='Custom', cron='0 0 6 * * *')


def test_lr_remove_sends_parameters(server, run_module):
    server.route('GET', PURGE, 'system_purge_schedule_custom', 'system_purge_schedule_none')
    server.route('PUT', PURGE, 'system_purge_schedule_update')
    result = run_module(log_rotation.main, dict(schedule='none'))
    assert result['changed'] is True
    body = server.calls('PUT', PURGE)[0]['body']
    assert body['schedule'] == dict(type='None')
    assert body['parameters']['audit_retention_hour'] == 720
    assert 'include_event_types' in body['parameters']


def test_lr_server_needs_parameters(server, run_module):
    # What Harbor says when parameters are missing: the reason the module always sends them.
    rejected = server.fixtures['system_purge_schedule_no_parameters']
    assert rejected['status'] == 400
    assert 'parameter' in json.dumps(rejected['body'])


def test_lr_info(server, run_module):
    server.route('GET', PURGE, 'system_purge_schedule_custom')
    server.route('GET', '/system/purgeaudit', 'system_purge_history')
    result = run_module(log_rotation_info.main, {})
    assert result['log_rotation']['include_event_types'] == ['create_artifact', 'delete_artifact']
    assert result['runs'] == []


# -- scan all ----------------------------------------------------------------------

def test_scan_all_without_scanner(server, run_module):
    server.route('GET', SCAN_ALL, 'system_scan_all_no_scanner')
    result = run_module(scan_all.main, dict(schedule='daily'))
    assert result['failed'] is True
    assert 'no default vulnerability scanner' in result['msg']
    assert server.calls('PUT') == []


def test_scan_all_info_without_scanner(server, run_module):
    server.route('GET', SCAN_ALL, 'system_scan_all_no_scanner')
    result = run_module(scan_all_info.main, {})
    assert result['failed'] is True
    assert 'no default vulnerability scanner' in result['msg']


def test_scan_all_create(server, run_module):
    server.route('GET', SCAN_ALL, ok(None), scan_all_schedule())
    server.route('PUT', SCAN_ALL, ok(None))
    result = run_module(scan_all.main, dict(schedule='custom', cron='0 0 5 * * 0'))
    assert result['changed'] is True
    assert server.calls('PUT', SCAN_ALL)[0]['body'] == dict(schedule=dict(type='Custom', cron='0 0 5 * * 0'))
    assert result['scan_all']['schedule'] == 'custom'
    assert server.calls('POST') == []


def test_scan_all_no_change(server, run_module):
    server.route('GET', SCAN_ALL, scan_all_schedule())
    result = run_module(scan_all.main, dict(cron='0 0 5 * * 0'))
    assert result['changed'] is False


def test_scan_all_remove(server, run_module):
    server.route('GET', SCAN_ALL, scan_all_schedule(), ok(None))
    server.route('PUT', SCAN_ALL, ok(None))
    result = run_module(scan_all.main, dict(schedule='none'))
    assert result['changed'] is True
    assert server.calls('PUT', SCAN_ALL)[0]['body'] == dict(schedule=dict(type='None'))


def test_scan_all_needs_schedule(server, run_module):
    result = run_module(scan_all.main, {})
    assert result['failed'] is True
    assert 'Set schedule' in result['msg']


def test_scan_all_info(server, run_module):
    metrics = dict(total=4, completed=4, metrics=dict(Success=4), ongoing=False, trigger='Schedule')
    server.route('GET', SCAN_ALL, scan_all_schedule(kind='Daily', cron='0 0 0 * * *'))
    server.route('GET', '/scans/all/metrics', ok(copy.deepcopy(metrics)))
    result = run_module(scan_all_info.main, {})
    assert result['scan_all']['schedule'] == 'daily'
    assert result['metrics'] == metrics
