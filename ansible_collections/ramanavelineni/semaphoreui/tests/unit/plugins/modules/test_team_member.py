# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

import copy

import pytest

from ansible_collections.ramanavelineni.semaphoreui.plugins.modules import team_member, team_member_info

PROJECT = 'fixtures-team'


@pytest.fixture
def project(server):
    server.route('GET', '/projects', 'team_projects_list')
    server.route('GET', '/user', 'team_user_current')
    server.route('GET', '/users?s=tm-fixture-a', 'team_users_search')
    pid = [p for p in server.fixtures['team_projects_list']['body'] if p['name'] == PROJECT][0]['id']
    return '/project/%d/users' % pid


def user_id(server, name='tm-fixture-a'):
    return [u for u in server.fixtures['team_users_search_prefix']['body'] if u['username'] == name][0]['id']


def members(server, fixture, drop=()):
    answer = server.response(fixture)
    answer['body'] = [m for m in answer['body'] if m['username'] not in drop]
    return answer


def test_add(server, project, run_module):
    server.route('GET', project, 'team_members_initial')
    server.route('POST', project, 'team_member_add')
    result = run_module(team_member.main, dict(project=PROJECT, user='tm-fixture-a', role='manager'))
    assert result['changed'] is True
    assert result['member']['role'] == 'manager'
    assert result['member']['user_id'] == user_id(server)
    assert server.calls('POST', project)[0]['body'] == dict(user_id=user_id(server), role='manager')


def test_add_check_mode(server, project, run_module):
    server.route('GET', project, 'team_members_initial')
    result = run_module(team_member.main, dict(project=PROJECT, user='tm-fixture-a', role='manager'), check_mode=True)
    assert result['changed'] is True
    assert server.calls('POST', project) == []


def test_role_required(server, project, run_module):
    result = run_module(team_member.main, dict(project=PROJECT, user='tm-fixture-a'))
    assert result['failed'] is True
    assert 'role is required' in result['msg']


def test_no_change(server, project, run_module):
    server.route('GET', project, 'team_members_two')
    result = run_module(team_member.main, dict(project=PROJECT, user='tm-fixture-a', role='manager'))
    assert result['changed'] is False
    assert server.calls('PUT') == [] and server.calls('POST', project) == []


def test_role_change(server, project, run_module):
    server.route('GET', project, 'team_members_two')
    server.route('PUT', '%s/%d' % (project, user_id(server)), 'team_member_update')
    result = run_module(team_member.main, dict(project=PROJECT, user='tm-fixture-a', role='owner'))
    assert result['changed'] is True
    assert result['diff']['before']['role'] == 'manager'
    assert result['diff']['after']['role'] == 'owner'
    assert server.calls('PUT')[0]['body'] == dict(role='owner')


def test_login_user_is_protected(server, project, run_module):
    me = server.fixtures['team_user_current']['body']
    server.route('GET', '/users?s=%s' % me['username'], dict(status=200, body=[copy.deepcopy(me)]))
    server.route('GET', project, 'team_members_two')
    result = run_module(team_member.main, dict(project=PROJECT, user=me['username'], role='guest'))
    assert result['failed'] is True
    assert 'logs in as' in result['msg']
    assert server.calls('PUT') == []


def test_login_user_unchanged_is_fine(server, project, run_module):
    me = server.fixtures['team_user_current']['body']
    server.route('GET', '/users?s=%s' % me['username'], dict(status=200, body=[copy.deepcopy(me)]))
    server.route('GET', project, 'team_members_two')
    result = run_module(team_member.main, dict(project=PROJECT, user=me['username'], role='owner'))
    assert result['changed'] is False


@pytest.mark.parametrize('args', [dict(role='manager'), dict(state='absent')])
def test_last_owner_is_protected(server, project, run_module, args):
    me = server.fixtures['team_user_current']['body']['username']
    server.route('GET', project, members(server, 'team_members_updated', drop=(me,)))
    result = run_module(team_member.main, dict(project=PROJECT, user='tm-fixture-a', **args))
    assert result['failed'] is True
    assert 'last owner' in result['msg']
    assert server.calls('PUT') == [] and server.calls('DELETE') == []


def test_owner_can_be_downgraded_when_another_remains(server, project, run_module):
    server.route('GET', project, 'team_members_updated')
    server.route('PUT', '%s/%d' % (project, user_id(server)), 'team_member_update')
    result = run_module(team_member.main, dict(project=PROJECT, user='tm-fixture-a', role='guest'))
    assert result['changed'] is True


def test_remove(server, project, run_module):
    server.route('GET', project, 'team_members_two')
    server.route('DELETE', '%s/%d' % (project, user_id(server)), 'team_member_remove')
    result = run_module(team_member.main, dict(project=PROJECT, user='tm-fixture-a', state='absent'))
    assert result['changed'] is True
    assert result['member'] == {}


def test_remove_not_a_member(server, project, run_module):
    server.route('GET', project, 'team_members_after_remove')
    result = run_module(team_member.main, dict(project=PROJECT, user='tm-fixture-a', state='absent'))
    assert result['changed'] is False


def test_unknown_user(server, project, run_module):
    server.route('GET', '/users?s=tm-nobody', dict(status=200, body=[]))
    server.route('GET', project, 'team_members_initial')
    result = run_module(team_member.main, dict(project=PROJECT, user='tm-nobody', role='guest'))
    assert result['failed'] is True
    assert "'tm-nobody' does not exist" in result['msg']
    result = run_module(team_member.main, dict(project=PROJECT, user='tm-nobody', state='absent'))
    assert result['changed'] is False


def test_prefix_is_not_a_match(server, project, run_module):
    server.route('GET', '/users?s=tm-fixture', 'team_users_search_prefix')
    server.route('GET', project, 'team_members_initial')
    result = run_module(team_member.main, dict(project=PROJECT, user='tm-fixture', role='guest'))
    assert result['failed'] is True
    assert 'does not exist' in result['msg']


def test_duplicate_add_reported(server, project, run_module):
    server.route('GET', project, 'team_members_initial')
    server.route('POST', project, 'team_member_add_duplicate')
    result = run_module(team_member.main, dict(project=PROJECT, user='tm-fixture-a', role='manager'))
    assert result['failed'] is True
    assert 'HTTP 409' in result['msg']


def test_team_member_info(server, project, run_module):
    server.route('GET', project, 'team_members_two')
    result = run_module(team_member_info.main, dict(project=PROJECT))
    assert [(m['username'], m['role']) for m in result['members']] == [('admin', 'owner'), ('tm-fixture-a', 'manager')]
    result = run_module(team_member_info.main, dict(project=PROJECT, user='tm-fixture-a'))
    assert [m['username'] for m in result['members']] == ['tm-fixture-a']
