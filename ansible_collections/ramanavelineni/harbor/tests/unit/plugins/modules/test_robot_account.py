# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

import json

from ansible_collections.ramanavelineni.harbor.plugins.module_utils.harbor import (
    canonical_permissions,
    robot_short_name,
)
from ansible_collections.ramanavelineni.harbor.plugins.modules import robot_account, robot_account_info

PULL_ALL = [dict(namespace='*', access=[dict(resource='repository', action='pull')])]
SECRET = 'DeclaredSecret9'


def rid(server, name='robot_create'):
    return server.fixtures[name]['body']['id']


def existing(server, listing='robot_list_system'):
    server.route('GET', '/robots', listing)


def test_create_returns_generated_secret(server, run_module):
    server.route('GET', '/robots', 'robot_list_system_empty')
    server.route('POST', '/robots', 'robot_create')
    server.route('GET', '/robots/%d' % rid(server), 'robot_get')
    result = run_module(robot_account.main, dict(name='fixtures-robot-sys', description='pulls', permissions=PULL_ALL))
    assert result['changed'] is True
    assert result['secret'] == 'RecordedSecret0'
    assert result['secret_updated'] is False
    assert result['robot_account']['full_name'].endswith('fixtures-robot-sys')
    assert server.calls('POST', '/robots')[0]['body'] == dict(
        name='fixtures-robot-sys', level='system', description='pulls', duration=-1, disable=False,
        permissions=[dict(kind='project', namespace='*', access=[dict(resource='repository', action='pull')])])
    assert server.calls('PATCH') == []


def test_create_sets_declared_secret(server, run_module):
    server.route('GET', '/robots', 'robot_list_system_empty')
    server.route('POST', '/robots', 'robot_create')
    server.route('PATCH', '/robots/%d' % rid(server), 'robot_secret_set')
    server.route('GET', '/robots/%d' % rid(server), 'robot_get')
    result = run_module(robot_account.main, dict(name='fixtures-robot-sys', permissions=PULL_ALL, secret=SECRET))
    assert result['changed'] is True
    assert result['secret_updated'] is True
    assert 'secret' not in result
    assert server.calls('PATCH')[0]['body'] == dict(secret=SECRET)
    assert SECRET not in json.dumps(result)


def test_create_check_mode(server, run_module):
    server.route('GET', '/robots', 'robot_list_system_empty')
    result = run_module(robot_account.main, dict(name='fixtures-robot-sys', permissions=PULL_ALL), check_mode=True)
    assert result['changed'] is True
    assert server.calls('POST') == []


def test_create_needs_permissions(server, run_module):
    server.route('GET', '/robots', 'robot_list_system_empty')
    result = run_module(robot_account.main, dict(name='fixtures-robot-sys'))
    assert result['failed'] is True
    assert 'needs permissions' in result['msg']


def test_no_change(server, run_module):
    existing(server)
    result = run_module(robot_account.main, dict(name='fixtures-robot-sys', description='pulls', duration=-1,
                                                 permissions=PULL_ALL))
    assert result['changed'] is False
    assert server.calls('PUT') == [] and server.calls('PATCH') == []


def test_update_sends_full_name_and_every_field(server, run_module):
    existing(server)
    server.route('PUT', '/robots/%d' % rid(server), 'robot_update')
    server.route('GET', '/robots/%d' % rid(server), 'robot_get_updated')
    result = run_module(robot_account.main, dict(name='fixtures-robot-sys', description='pulls everything'))
    assert result['changed'] is True
    body = server.calls('PUT')[0]['body']
    current = server.fixtures['robot_list_system']['body'][0]
    assert body['name'] == current['name'] and body['name'] != 'fixtures-robot-sys'
    assert body['level'] == 'system'
    assert body['description'] == 'pulls everything'
    assert body['permissions'] == canonical_permissions(current['permissions'])
    assert body['duration'] == -1 and body['disable'] is False


def test_permissions_compared_in_any_order(server, run_module):
    listing = server.response('robot_list_system')
    listing['body'][0]['permissions'] = [dict(kind='project', namespace='a', access=[
        dict(resource='repository', action='push'), dict(resource='repository', action='pull')])]
    server.route('GET', '/robots', listing)
    result = run_module(robot_account.main, dict(name='fixtures-robot-sys', permissions=[dict(namespace='a', access=[
        dict(resource='repository', action='pull'), dict(resource='repository', action='push')])]))
    assert result['changed'] is False


def test_secret_always_and_on_create(server, run_module):
    existing(server)
    server.route('PATCH', '/robots/%d' % rid(server), 'robot_secret_set')
    result = run_module(robot_account.main, dict(name='fixtures-robot-sys', secret=SECRET))
    assert result['changed'] is True and result['secret_updated'] is True
    assert len(server.calls('PATCH')) == 1
    result = run_module(robot_account.main, dict(name='fixtures-robot-sys', secret=SECRET, update_secret='on_create'))
    assert result['changed'] is False and result['secret_updated'] is False
    assert len(server.calls('PATCH')) == 1


def test_weak_secret_fails_before_writing(server, run_module):
    result = run_module(robot_account.main, dict(name='fixtures-robot-sys', permissions=PULL_ALL, secret='weak'))
    assert result['failed'] is True
    assert '8 to 128' in result['msg']
    assert [c['path'] for c in server.requests] == ['/systeminfo']


def test_bad_name_fails_before_writing(server, run_module):
    result = run_module(robot_account.main, dict(name='Fixtures-Robot', permissions=PULL_ALL))
    assert result['failed'] is True
    assert 'lower-case' in result['msg']


def test_rejected_update_reported(server, run_module):
    existing(server)
    server.route('PUT', '/robots/%d' % rid(server), 'robot_update_bad_name')
    result = run_module(robot_account.main, dict(name='fixtures-robot-sys', description='x'))
    assert result['failed'] is True
    assert 'cannot update the level or name of robot' in result['msg']


def test_delete(server, run_module):
    existing(server)
    server.route('DELETE', '/robots/%d' % rid(server), 'robot_delete')
    result = run_module(robot_account.main, dict(name='fixtures-robot-sys', state='absent'))
    assert result['changed'] is True
    assert len(server.calls('DELETE')) == 1


def test_delete_missing_is_no_change(server, run_module):
    server.route('GET', '/robots', 'robot_list_system_empty')
    result = run_module(robot_account.main, dict(name='fixtures-robot-sys', state='absent'))
    assert result['changed'] is False


def test_project_robot_found_by_suffix(server, run_module):
    server.route('GET', '/projects', 'robot_projects_by_name')
    server.route('GET', '/robots', 'robot_list_project')
    result = run_module(robot_account.main, dict(name='ci', level='project', project='fixtures-robot', duration=30))
    assert result['changed'] is False
    assert result['robot_account']['full_name'].endswith('fixtures-robot+ci')


def test_project_robot_other_project_refused(server, run_module):
    server.route('GET', '/projects', 'robot_projects_by_name')
    server.route('GET', '/robots', 'robot_list_project')
    result = run_module(robot_account.main, dict(name='ci', level='project', project='fixtures-robot',
                                                 permissions=[dict(namespace='other', access=[
                                                     dict(resource='repository', action='pull')])]))
    assert result['failed'] is True
    assert 'own project' in result['msg']


def test_project_robot_needs_project(server, run_module):
    result = run_module(robot_account.main, dict(name='ci', level='project', permissions=PULL_ALL))
    assert result['failed'] is True
    assert 'needs project' in result['msg']


def test_info_system_short_names(server, run_module):
    server.route('GET', '/robots', 'robot_list_system_all')
    server.route('GET', '/configurations', 'robot_configurations')
    result = run_module(robot_account_info.main, dict(name='fixtures-robot-sys'))
    assert [r['name'] for r in result['robot_accounts']] == ['fixtures-robot-sys']


def test_info_falls_back_to_default_prefix(server, run_module):
    server.route('GET', '/robots', 'robot_list_system_all')
    server.route('GET', '/configurations', 'robot_configurations_forbidden')
    result = run_module(robot_account_info.main, dict(name='fixtures-robot-sys'))
    assert [r['name'] for r in result['robot_accounts']] == ['fixtures-robot-sys']


def test_info_project(server, run_module):
    server.route('GET', '/projects', 'robot_projects_by_name')
    server.route('GET', '/robots', 'robot_list_project')
    server.route('GET', '/configurations', 'robot_configurations')
    result = run_module(robot_account_info.main, dict(project='fixtures-robot'))
    assert [r['name'] for r in result['robot_accounts']] == ['ci']


def test_canonical_permissions_merges_and_sorts():
    perms = [dict(kind='project', namespace='b', access=[dict(resource='repository', action='push')]),
             dict(namespace='b', access=[dict(resource='repository', action='pull')]),
             dict(kind='system', namespace='/', access=[dict(resource='project', action='list')])]
    assert canonical_permissions(perms) == [
        dict(kind='project', namespace='b', access=[dict(resource='repository', action='pull'),
                                                    dict(resource='repository', action='push')]),
        dict(kind='system', namespace='/', access=[dict(resource='project', action='list')])]


def test_robot_short_name():
    assert robot_short_name('robot$puller', None, 'robot$') == 'puller'
    assert robot_short_name('robot_puller', None, 'robot_') == 'puller'
    assert robot_short_name('robot$apps+ci', 'apps', 'robot$') == 'ci'


def test_info_reports_a_failed_prefix_read(server, run_module):
    # Only "may not read the configuration" falls back to the default prefix.
    server.route('GET', '/robots', 'robot_list_system_all')
    server.route('GET', '/configurations', dict(status=500, body=None, headers={}))
    result = run_module(robot_account_info.main, dict(name='fixtures-robot-sys'))
    assert result['failed'] is True
    assert 'HTTP 500' in result['msg']
