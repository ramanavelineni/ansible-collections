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


# Harbor reports a setting as not editable in two cases the recordings don't
# hold: auth_mode once a second user exists, and every setting that the
# server's own configuration fixes. The flag is set by hand here.

def locked_configuration(server, *keys):
    current = server.response('system_configurations')
    for key in keys:
        current['body'][key]['editable'] = False
    return current


def test_configuration_refuses_to_change_a_setting_that_is_not_editable(server, run_module):
    server.route('GET', '/configurations', locked_configuration(server, 'auth_mode'))
    result = run_module(configuration.main, dict(settings=dict(auth_mode='oidc_auth', session_timeout=45)))
    assert result['failed'] is True
    assert result['msg'] == ('Harbor reports this setting as not editable at the moment, so it cannot be changed: '
                             'auth_mode. auth_mode can only change while no user other than the admin exists.')
    assert server.calls('PUT') == []


def test_configuration_names_every_setting_that_is_not_editable(server, run_module):
    server.route('GET', '/configurations', locked_configuration(server, 'session_timeout', 'read_only', 'banner_message'))
    result = run_module(configuration.main, dict(settings=dict(session_timeout=45, read_only=True)), check_mode=True)
    assert result['failed'] is True
    assert result['msg'] == ('Harbor reports these settings as not editable at the moment, so they cannot be '
                             'changed: read_only, session_timeout.')
    assert server.calls('PUT') == []


def test_configuration_unchanged_setting_that_is_not_editable_is_no_change(server, run_module):
    current = locked_configuration(server, 'auth_mode')
    server.route('GET', '/configurations', current)
    result = run_module(configuration.main, dict(settings=dict(auth_mode=current['body']['auth_mode']['value'])))
    assert result.get('failed') is not True
    assert result['changed'] is False
    assert server.calls('PUT') == []


def test_configuration_changes_other_settings_beside_one_that_is_not_editable(server, run_module):
    current = locked_configuration(server, 'auth_mode')
    server.route('GET', '/configurations', current, 'system_configurations_updated')
    server.route('PUT', '/configurations', 'system_configurations_update')
    result = run_module(configuration.main, dict(settings=dict(
        auth_mode=current['body']['auth_mode']['value'], session_timeout=45)))
    assert result['changed'] is True
    assert server.calls('PUT')[0]['body'] == dict(session_timeout=45)


def test_configuration_refuses_a_secret_that_is_not_editable(server, run_module):
    server.route('GET', '/configurations', locked_configuration(server, 'uaa_client_secret'))
    result = run_module(configuration.main, dict(uaa_client_secret='uaa-s3cret'))
    assert result['failed'] is True
    assert 'cannot be changed: uaa_client_secret.' in result['msg']
    assert 'uaa-s3cret' not in json.dumps(result)
    assert server.calls('PUT') == []


# A secret a newer Harbor might return: no recorded version has one, so the
# keys are added by hand. The module has no name for them, only the pattern.
NEW_SECRETS = dict(oidc_refresh_token='t0ken-value', ldap_bind_password='pw-value',
                   OIDC_Client_Secret_V2='secret-value', smtp_passwd='passwd-value',
                   registry_credential='cred-value', jwt_private_key='key-value')
# Settings the module knows that have such a word in their name and are no secret.
LOOK_ALIKES = ('robot_token_duration', 'token_expiration', 'http_authproxy_tokenreview_endpoint')


def with_new_secrets(server, name='system_configurations'):
    current = server.response(name)
    for key, value in NEW_SECRETS.items():
        current['body'][key] = dict(value=value, editable=True)
    return current


def test_configuration_info_hides_a_secret_it_has_no_name_for(server, run_module):
    current = with_new_secrets(server)
    server.route('GET', '/configurations', current)
    result = run_module(configuration_info.main, {})
    assert sorted(set(current['body']) - set(result['configuration'])) == sorted(list(NEW_SECRETS) + ['uaa_client_secret'])
    for value in NEW_SECRETS.values():
        assert value not in json.dumps(result)


def test_configuration_hides_a_secret_it_has_no_name_for(server, run_module):
    server.route('GET', '/configurations', with_new_secrets(server), with_new_secrets(server, 'system_configurations_updated'))
    server.route('PUT', '/configurations', 'system_configurations_update')
    result = run_module(configuration.main, dict(settings=dict(session_timeout=45)))
    assert result['changed'] is True
    assert result['configuration']['session_timeout'] == 45
    assert not set(NEW_SECRETS) & set(result['configuration'])
    for value in NEW_SECRETS.values():
        assert value not in json.dumps(result)


def test_configuration_hides_a_secret_it_has_no_name_for_without_a_change(server, run_module):
    server.route('GET', '/configurations', with_new_secrets(server))
    result = run_module(configuration.main, {})
    assert result['changed'] is False
    assert not set(NEW_SECRETS) & set(result['configuration'])
    for value in NEW_SECRETS.values():
        assert value not in json.dumps(result)


def test_configuration_hides_a_secret_it_has_no_name_for_in_check_mode(server, run_module):
    server.route('GET', '/configurations', with_new_secrets(server))
    result = run_module(configuration.main, dict(settings=dict(session_timeout=45)), check_mode=True)
    assert result['changed'] is True
    assert not set(NEW_SECRETS) & set(result['configuration'])
    for value in NEW_SECRETS.values():
        assert value not in json.dumps(result)


@pytest.mark.parametrize('main', [configuration.main, configuration_info.main], ids=['configuration', 'configuration_info'])
def test_settings_that_only_look_like_secrets_are_returned(server, run_module, main):
    current = server.response('system_configurations')
    server.route('GET', '/configurations', current)
    result = run_module(main, {})
    for key in LOOK_ALIKES:
        assert result['configuration'][key] == current['body'][key]['value']
    # Everything Harbor returned is there, the one recorded secret excepted.
    assert sorted(set(current['body']) - set(result['configuration'])) == ['uaa_client_secret']


def test_a_setting_that_only_looks_like_a_secret_can_be_set(server, run_module):
    current = server.response('system_configurations')
    server.route('GET', '/configurations', current, 'system_configurations_updated')
    server.route('PUT', '/configurations', 'system_configurations_update')
    wanted = current['body']['robot_token_duration']['value'] + 1
    result = run_module(configuration.main, dict(settings=dict(robot_token_duration=wanted)))
    assert result['changed'] is True
    assert server.calls('PUT')[0]['body'] == dict(robot_token_duration=wanted)


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


def test_gc_delete_tag_is_sent_when_the_version_cannot_be_read(server, run_module):
    # The same rule as project and registry: only a version known to be older refuses the option.
    info = server.response('systeminfo')
    info['body']['harbor_version'] = 'dev'
    server.route('GET', '/systeminfo', info)
    server.route('GET', GC, 'system_gc_schedule_custom')
    server.route('PUT', GC, 'system_gc_schedule_update')
    result = run_module(garbage_collection.main, dict(delete_tag=True))
    assert result.get('failed') is not True
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


def with_parameters(server, name, **extra):
    """The recorded schedule `name` with more job parameters. Hand-edited: no fixture has any of them."""
    schedule = server.response(name)
    params = json.loads(schedule['body']['job_parameters'])
    params.update(extra)
    schedule['body']['job_parameters'] = json.dumps(params)
    return schedule


def with_type(server, name, kind):
    """The recorded schedule `name` as another type. Hand-edited: only Custom was recorded."""
    schedule = server.response(name)
    schedule['body']['schedule']['type'] = kind
    return schedule


def history(first, count):
    """A page of run history. Hand-written after the swagger model: the recorded history is empty."""
    return dict(status=200, headers={}, body=[
        dict(id=i, job_name='GARBAGE_COLLECTION', job_kind='SCHEDULE', job_status='Success',
             job_parameters='{"workers":2}', creation_time='2026-09-27T20:00:00.000Z',
             update_time='2026-09-27T20:01:00.000Z')
        for i in range(first, first - count, -1)])


def test_gc_change_keeps_parameters_without_an_option(server, run_module):
    server.route('GET', GC, with_parameters(server, 'system_gc_schedule_custom', dry_run=True))
    server.route('PUT', GC, 'system_gc_schedule_update')
    result = run_module(garbage_collection.main, dict(workers=4))
    assert result['changed'] is True
    sent = server.calls('PUT', GC)[0]['body']['parameters']
    assert sent['dry_run'] is True
    assert (sent['workers'], sent['delete_untagged']) == (4, True)


def test_gc_change_still_drops_internal_parameters(server, run_module):
    server.route('GET', GC, with_parameters(server, 'system_gc_schedule_custom',
                                            redis_url_reg='redis://:s3cret@redis:6379/1', time_window=2))
    server.route('PUT', GC, 'system_gc_schedule_update')
    run_module(garbage_collection.main, dict(workers=4))
    sent = server.calls('PUT', GC)[0]['body']['parameters']
    assert 'redis_url_reg' not in sent and 'time_window' not in sent


def test_gc_unknown_type_fails_when_it_would_be_written(server, run_module):
    server.route('GET', GC, with_type(server, 'system_gc_schedule_custom', 'Manual'))
    for check_mode in (False, True):
        result = run_module(garbage_collection.main, dict(workers=4), check_mode=check_mode)
        assert result['failed'] is True
        assert "type 'manual'" in result['msg'] and 'Set schedule' in result['msg']
    assert server.calls('PUT') == []


def test_gc_unknown_type_untouched_is_no_change(server, run_module):
    server.route('GET', GC, with_type(server, 'system_gc_schedule_custom', 'Manual'))
    result = run_module(garbage_collection.main, dict(workers=2))
    assert result['changed'] is False
    assert result['garbage_collection']['schedule'] == 'manual'


def test_gc_unknown_type_can_be_replaced(server, run_module):
    server.route('GET', GC, with_type(server, 'system_gc_schedule_custom', 'Manual'), 'system_gc_schedule_custom')
    server.route('PUT', GC, 'system_gc_schedule_update')
    result = run_module(garbage_collection.main, dict(schedule='weekly'))
    assert result['changed'] is True
    assert server.calls('PUT', GC)[0]['body']['schedule'] == dict(type='Weekly', cron='0 0 0 * * 0')


def test_gc_info_reports_unknown_type(server, run_module):
    server.route('GET', GC, with_type(server, 'system_gc_schedule_custom', 'Manual'))
    server.route('GET', '/system/gc', 'system_gc_history')
    result = run_module(garbage_collection_info.main, {})
    assert result.get('failed') is not True
    assert result['garbage_collection']['schedule'] == 'manual'
    assert result['garbage_collection']['workers'] == 2


def test_gc_info_reads_runs_past_one_page(server, run_module):
    server.route('GET', GC, 'system_gc_schedule_none')
    server.route('GET', '/system/gc', history(250, 100), history(150, 100), history(50, 50))
    result = run_module(garbage_collection_info.main, dict(runs=250))
    assert [run['id'] for run in result['runs']] == list(range(250, 0, -1))
    queries = [call['query'] for call in server.calls('GET', '/system/gc')]
    assert [q['page'] for q in queries] == [['1'], ['2'], ['3']]
    assert all(q['page_size'] == ['100'] and q['sort'] == ['-creation_time'] for q in queries)


def test_gc_info_stops_reading_when_it_has_enough_runs(server, run_module):
    server.route('GET', GC, 'system_gc_schedule_none')
    server.route('GET', '/system/gc', history(300, 100), history(200, 100), history(100, 100))
    result = run_module(garbage_collection_info.main, dict(runs=120))
    assert [run['id'] for run in result['runs']] == list(range(300, 180, -1))
    assert len(server.calls('GET', '/system/gc')) == 2


def test_gc_info_stops_when_a_page_repeats(server, run_module):
    # A server that ignored `page` answers every request with the same runs.
    server.route('GET', GC, 'system_gc_schedule_none')
    server.route('GET', '/system/gc', history(100, 100))
    result = run_module(garbage_collection_info.main, dict(runs=250))
    assert [run['id'] for run in result['runs']] == list(range(100, 0, -1))
    assert len(server.calls('GET', '/system/gc')) == 2


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


def test_lr_change_keeps_parameters_without_an_option(server, run_module):
    server.route('GET', PURGE, with_parameters(server, 'system_purge_schedule_custom', dry_run=True, later_option='x'))
    server.route('PUT', PURGE, 'system_purge_schedule_update')
    run_module(log_rotation.main, dict(audit_retention_hour=168))
    assert server.calls('PUT', PURGE)[0]['body']['parameters'] == dict(
        audit_retention_hour=168, include_event_types='create_artifact,delete_artifact', dry_run=True, later_option='x')


def test_lr_unknown_type_fails_when_it_would_be_written(server, run_module):
    server.route('GET', PURGE, with_type(server, 'system_purge_schedule_custom', 'Manual'))
    result = run_module(log_rotation.main, dict(audit_retention_hour=168))
    assert result['failed'] is True
    assert "type 'manual'" in result['msg']
    assert server.calls('PUT') == []


def test_lr_info_reports_unknown_type(server, run_module):
    server.route('GET', PURGE, with_type(server, 'system_purge_schedule_custom', 'Manual'))
    server.route('GET', '/system/purgeaudit', 'system_purge_history')
    result = run_module(log_rotation_info.main, {})
    assert result['log_rotation']['schedule'] == 'manual'


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
