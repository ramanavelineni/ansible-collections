# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""The diff of an update and of a removal, for the modules no other test checks it for.

`before` is the object as it was, `after` is what the task returns: the
object as Harbor stored it, or nothing once it is removed.
"""

import json

from ansible_collections.ramanavelineni.harbor.plugins.modules import (
    log_rotation,
    replication,
    robot_account,
    scan_all,
)

PURGE = '/system/purgeaudit/schedule'
SCAN_ALL = '/system/scanAll/schedule'
SECRET = 'DeclaredSecret9'


def location_id(server, fixture):
    return int(server.fixtures[fixture]['headers']['location'].rsplit('/', 1)[-1])


def ok(body=None):
    return dict(status=200, body=body, headers={})


def scan_all_schedule(cron, kind):
    """Hand-written after Harbor's swagger model: Scan All can't be recorded without a vulnerability scanner."""
    return ok(dict(id=3, status='Scheduled', schedule=dict(type=kind, cron=cron), parameters={},
                   creation_time='2026-09-27T20:00:00.000Z', update_time='2026-09-27T20:00:00.000Z'))


def changed_fields(diff):
    return sorted(k for k in diff['after'] if diff['after'][k] != diff['before'].get(k))


# -- log rotation -----------------------------------------------------------------

def test_log_rotation_update_diff(server, run_module):
    # Hand-edited: the recorded schedule with the retention the task sets. No such change was recorded.
    after = server.response('system_purge_schedule_custom')
    parameters = json.loads(after['body']['job_parameters'])
    parameters['audit_retention_hour'] = 168
    after['body']['job_parameters'] = json.dumps(parameters)
    server.route('GET', PURGE, 'system_purge_schedule_custom', after)
    server.route('PUT', PURGE, 'system_purge_schedule_update')
    result = run_module(log_rotation.main, dict(audit_retention_hour=168))
    diff = result['diff']
    assert diff['before'] == dict(
        schedule='custom', cron='0 0 6 * * *',
        next_scheduled_time=server.fixtures['system_purge_schedule_custom']['body']['schedule']['next_scheduled_time'],
        audit_retention_hour=720, include_event_types=['create_artifact', 'delete_artifact'], dry_run=None)
    assert changed_fields(diff) == ['audit_retention_hour']
    assert diff['after']['audit_retention_hour'] == 168
    assert diff['after'] == result['log_rotation']


def test_log_rotation_remove_diff(server, run_module):
    server.route('GET', PURGE, 'system_purge_schedule_custom', 'system_purge_schedule_none')
    server.route('PUT', PURGE, 'system_purge_schedule_update')
    result = run_module(log_rotation.main, dict(schedule='none'))
    diff = result['diff']
    assert diff['before']['schedule'] == 'custom' and diff['before']['audit_retention_hour'] == 720
    assert diff['after'] == dict(schedule='none', cron='', next_scheduled_time=None, audit_retention_hour=None,
                                 include_event_types=None, dry_run=None)
    assert diff['after'] == result['log_rotation']


def test_log_rotation_no_change_diff_is_empty(server, run_module):
    server.route('GET', PURGE, 'system_purge_schedule_custom')
    result = run_module(log_rotation.main, dict(audit_retention_hour=720))
    assert result['changed'] is False
    assert result['diff']['before'] == result['diff']['after'] == result['log_rotation']


# -- scan all (hand-written answers, see scan_all_schedule) ---------------------------

def test_scan_all_update_diff(server, run_module):
    server.route('GET', SCAN_ALL, scan_all_schedule('0 0 5 * * 0', 'Custom'), scan_all_schedule('0 0 0 * * *', 'Daily'))
    server.route('PUT', SCAN_ALL, ok(None))
    result = run_module(scan_all.main, dict(schedule='daily'))
    diff = result['diff']
    assert diff['before'] == dict(schedule='custom', cron='0 0 5 * * 0', next_scheduled_time=None)
    assert diff['after'] == dict(schedule='daily', cron='0 0 0 * * *', next_scheduled_time=None)
    assert diff['after'] == result['scan_all']
    assert server.calls('PUT', SCAN_ALL)[0]['body'] == dict(schedule=dict(type='Daily', cron='0 0 0 * * *'))


def test_scan_all_remove_diff(server, run_module):
    server.route('GET', SCAN_ALL, scan_all_schedule('0 0 5 * * 0', 'Custom'), ok(None))
    server.route('PUT', SCAN_ALL, ok(None))
    result = run_module(scan_all.main, dict(schedule='none'))
    diff = result['diff']
    assert diff['before'] == dict(schedule='custom', cron='0 0 5 * * 0', next_scheduled_time=None)
    assert diff['after'] == dict(schedule='none', cron='', next_scheduled_time=None)
    assert diff['after'] == result['scan_all']


def test_scan_all_no_change_diff_is_empty(server, run_module):
    server.route('GET', SCAN_ALL, scan_all_schedule('0 0 5 * * 0', 'Custom'))
    result = run_module(scan_all.main, dict(schedule='custom', cron='0 0 5 * * 0'))
    assert result['changed'] is False
    assert result['diff']['before'] == result['diff']['after'] == result['scan_all']


# -- replication --------------------------------------------------------------------

def replication_routes(server):
    server.route('GET', '/replication/policies', 'registry_replication_list')
    server.route('GET', '/registries', 'registry_list')
    return '/replication/policies/%d' % location_id(server, 'registry_replication_create')


def test_replication_update_diff(server, run_module):
    path = replication_routes(server)
    server.route('PUT', path, 'registry_replication_update')
    server.route('GET', path, 'registry_replication_get_updated')
    result = run_module(replication.main, dict(name='rr-fixtures-pull', speed=256,
                                               trigger=dict(type='scheduled', cron='0 0 3 * * *')))
    diff = result['diff']
    assert diff['before']['speed'] == 0 and diff['before']['trigger'] == dict(type='manual', cron='')
    assert changed_fields(diff) == ['speed', 'trigger']
    assert diff['after']['speed'] == 256
    assert diff['after']['trigger'] == dict(type='scheduled', cron='0 0 3 * * *')
    assert diff['after'] == result['replication']
    # What was not declared is shown as it is, on both sides.
    assert diff['before']['filters'] == diff['after']['filters'] == [
        dict(type='name', value='library/**', decoration=''), dict(type='tag', value='v*', decoration='excludes')]


def test_replication_delete_diff(server, run_module):
    path = replication_routes(server)
    server.route('DELETE', path, 'registry_replication_delete')
    result = run_module(replication.main, dict(name='rr-fixtures-pull', state='absent'))
    diff = result['diff']
    assert diff['after'] == {} and result['replication'] == {}
    before = diff['before']
    assert (before['id'], before['name']) == (location_id(server, 'registry_replication_create'), 'rr-fixtures-pull')
    assert before['src_registry'] == 'rr-fixtures-self' and before['dest_registry'] is None
    assert before['dest_namespace'] == 'library' and before['override'] is True and before['enabled'] is False


def test_replication_delete_missing_diff_is_empty(server, run_module):
    server.route('GET', '/replication/policies', 'registry_replication_list_before')
    result = run_module(replication.main, dict(name='rr-fixtures-pull', state='absent'))
    assert result['changed'] is False
    assert result['diff'] == dict(before={}, after={})


# -- robot accounts -------------------------------------------------------------------

def robot_path(server):
    server.route('GET', '/robots', 'robot_list_system')
    return '/robots/%d' % server.fixtures['robot_create']['body']['id']


def test_robot_update_diff(server, run_module):
    path = robot_path(server)
    server.route('PUT', path, 'robot_update')
    server.route('GET', path, 'robot_get_updated')
    permissions = [dict(namespace='fixtures-robot', access=[dict(resource='repository', action='pull'),
                                                            dict(resource='repository', action='push')])]
    result = run_module(robot_account.main, dict(name='fixtures-robot-sys', description='pulls everything',
                                                 permissions=permissions))
    diff = result['diff']
    assert diff['before']['description'] == 'pulls'
    assert diff['before']['permissions'] == [dict(kind='project', namespace='*',
                                                  access=[dict(resource='repository', action='pull')])]
    assert changed_fields(diff) == ['description', 'permissions']
    assert diff['after']['description'] == 'pulls everything'
    assert diff['after']['permissions'][0]['namespace'] == 'fixtures-robot'
    assert diff['after'] == result['robot_account']
    assert (diff['before']['id'], diff['before']['name']) == (diff['after']['id'], diff['after']['name'])


def test_robot_secret_only_update_diff_shows_no_secret(server, run_module):
    path = robot_path(server)
    server.route('PATCH', path, 'robot_secret_set')
    result = run_module(robot_account.main, dict(name='fixtures-robot-sys', secret=SECRET))
    assert result['changed'] is True and result['secret_updated'] is True
    # The secret is the only thing that changes, and it is in neither side.
    assert result['diff']['before'] == result['diff']['after'] == result['robot_account']
    assert SECRET not in json.dumps(result)


def test_robot_delete_diff(server, run_module):
    path = robot_path(server)
    server.route('DELETE', path, 'robot_delete')
    result = run_module(robot_account.main, dict(name='fixtures-robot-sys', state='absent'))
    diff = result['diff']
    assert diff['after'] == {} and result['robot_account'] == {}
    before = diff['before']
    assert (before['id'], before['name'], before['level']) == (
        server.fixtures['robot_create']['body']['id'], 'fixtures-robot-sys', 'system')
    assert before['full_name'] == server.fixtures['robot_list_system']['body'][0]['name']
    assert before['description'] == 'pulls' and before['duration'] == -1
    assert 'secret' not in before


def test_robot_delete_missing_diff_is_empty(server, run_module):
    server.route('GET', '/robots', 'robot_list_system_empty')
    result = run_module(robot_account.main, dict(name='fixtures-robot-sys', state='absent'))
    assert result['changed'] is False
    assert result['diff'] == dict(before={}, after={})
