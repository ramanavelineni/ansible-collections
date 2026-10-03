# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""project_id names the project instead of project, and the list of projects is not read."""

import json

import pytest

from ansible_collections.ramanavelineni.semaphoreui.plugins.modules import (
    integration,
    integration_info,
    inventory,
    inventory_info,
    key_store,
    key_store_info,
    repository,
    repository_info,
    runner,
    runner_info,
    schedule,
    schedule_info,
    team_member,
    team_member_info,
    template,
    template_info,
    variable_group,
    variable_group_info,
    view,
    view_info,
)

# module, the key of its result, the options it needs besides the project.
MANAGE = [
    (integration, 'integration', dict(name='anything')),
    (inventory, 'inventory', dict(name='anything')),
    (key_store, 'key', dict(name='anything', type='none')),
    (repository, 'repository', dict(name='anything')),
    (runner, 'runner', dict(name='anything')),
    (schedule, 'schedule', dict(name='anything')),
    (team_member, 'member', dict(user='alice', role='owner')),
    (template, 'template', dict(name='anything')),
    (variable_group, 'variable_group', dict(name='anything')),
    (view, 'view', dict(name='anything')),
]
INFO = [
    (integration_info, 'integrations'),
    (inventory_info, 'inventories'),
    (key_store_info, 'key_store'),
    (repository_info, 'repositories'),
    (runner_info, 'runners'),
    (schedule_info, 'schedules'),
    (team_member_info, 'members'),
    (template_info, 'templates'),
    (variable_group_info, 'variable_groups'),
    (view_info, 'views'),
]
# Modules that cannot work without a project. runner and runner_info can:
# without one they mean the global runners.
NEED_A_PROJECT = [m for m in MANAGE if m[0] is not runner] + [(m, key, {}) for m, key in INFO if m is not runner_info]
MANAGE_IDS = [m[1] for m in MANAGE]
INFO_IDS = [m[1] for m in INFO]

# A project's lists, each as recorded with nothing named "anything" in it.
EMPTY_LISTS = dict(
    integrations='integrations_empty', inventory='inventories_empty', keys='keys_new_project',
    repositories='repositories_empty', runners='runner_project_list_community', schedules='schedules_empty',
    templates='templates_empty', environment='variable_groups_empty', views='views_new_project',
)


def pid(server):
    return server.fixtures['projects_one']['body'][0]['id']


def single(server):
    """GET /project/<id>. Hand-written: the recorder never read a single project.

    The body is the project's row in the recorded list, which the API
    describes as the same object.
    """
    return dict(status=200, body=server.response('projects_one')['body'][0])


def not_found():
    """Hand-written: what a project that isn't there is assumed to answer."""
    return dict(status=404, body=dict(error='Not found'))


@pytest.fixture
def project(server):
    """A project reachable by id only: a read of the project list fails the test."""
    base = '/project/%d' % pid(server)
    server.route('GET', base, single(server))
    for path, fixture in EMPTY_LISTS.items():
        server.route('GET', '%s/%s' % (base, path), fixture)
    members = server.response('team_members_initial')
    members['body'] = []
    server.route('GET', base + '/users', members)
    no_users = server.response('team_users_search')
    no_users['body'] = []
    server.route('GET', '/users?s=alice', no_users)
    return base


def capped(server):
    """The list of projects as a server with 200 projects answers it."""
    answer = server.response('projects_one')
    row = answer['body'][0]
    answer['body'] = [dict(row, id=row['id'] + n, name='p%d' % n if n else row['name']) for n in range(200)]
    return answer


@pytest.mark.parametrize('module, key, args', MANAGE, ids=MANAGE_IDS)
def test_manage_by_id_reads_that_project_only(server, project, run_module, module, key, args):
    result = run_module(module.main, dict(args, project_id=pid(server), state='absent'))
    assert result.get('failed') is not True, result.get('msg')
    assert result['changed'] is False and result[key] == {}
    assert len(server.calls('GET', project)) == 1
    assert server.calls('GET', '/projects') == []


@pytest.mark.parametrize('module, key', INFO, ids=INFO_IDS)
def test_info_by_id_reads_that_project_only(server, project, run_module, module, key):
    result = run_module(module.main, dict(project_id=pid(server)))
    assert result.get('failed') is not True, result.get('msg')
    assert result['changed'] is False and isinstance(result[key], list)
    assert len(server.calls('GET', project)) == 1
    assert server.calls('GET', '/projects') == []


def test_by_name_reads_the_list_not_the_project(server, project, run_module):
    server.route('GET', '/projects', 'projects_one')
    result = run_module(view.main, dict(project='homelab', name='anything', state='absent'))
    assert result['changed'] is False
    assert len(server.calls('GET', '/projects')) == 1
    assert server.calls('GET', project) == []


@pytest.mark.parametrize('module, key, args', MANAGE + [(m, key, {}) for m, key in INFO], ids=MANAGE_IDS + INFO_IDS)
def test_project_and_project_id_exclude_each_other(server, run_module, module, key, args):
    result = run_module(module.main, dict(args, project='homelab', project_id=pid(server)))
    assert result['failed'] is True
    assert result['msg'] == 'parameters are mutually exclusive: project|project_id'
    assert server.requests == []


@pytest.mark.parametrize('module, key, args', NEED_A_PROJECT, ids=[m[1] for m in NEED_A_PROJECT])
def test_one_of_them_is_required(server, run_module, module, key, args):
    result = run_module(module.main, dict(args))
    assert result['failed'] is True
    assert result['msg'] == 'one of the following is required: project, project_id'
    assert server.requests == []


@pytest.mark.parametrize('module, key, args', MANAGE, ids=MANAGE_IDS)
def test_wrong_id_fails(server, run_module, module, key, args):
    server.route('GET', '/project/999', not_found())
    result = run_module(module.main, dict(args, project_id=999))
    assert result['failed'] is True
    assert result['msg'] == 'Project with id 999 does not exist, or the user this module logs in as cannot see it.'
    assert [r['method'] for r in server.requests if r['path'].startswith('/project')] == ['GET']


@pytest.mark.parametrize('module, key', INFO, ids=INFO_IDS)
def test_info_with_wrong_id_fails_in_check_mode_too(server, run_module, module, key):
    server.route('GET', '/project/999', not_found())
    for check_mode in (False, True):
        result = run_module(module.main, dict(project_id=999), check_mode=check_mode)
        assert result['failed'] is True
        assert 'Project with id 999 does not exist' in result['msg']


@pytest.mark.parametrize('module, key, args', MANAGE, ids=MANAGE_IDS)
def test_absent_in_missing_id_is_unchanged(server, run_module, module, key, args):
    server.route('GET', '/project/999', not_found())
    result = run_module(module.main, dict(args, project_id=999, state='absent'))
    assert result.get('failed') is not True, result.get('msg')
    assert result['changed'] is False and result[key] == {}
    assert result['diff'] == dict(before={}, after={})


@pytest.mark.parametrize('module, key, args', MANAGE, ids=MANAGE_IDS)
def test_missing_id_is_a_change_in_check_mode(server, run_module, module, key, args):
    server.route('GET', '/project/999', not_found())
    result = run_module(module.main, dict(args, project_id=999), check_mode=True)
    assert result.get('failed') is not True, result.get('msg')
    assert result['changed'] is True and result[key] == {}
    # A warning is a string, or a dict from ansible-core 2.19 on.
    warnings = json.dumps(result['warnings'])
    assert 'Project with id 999 does not exist' in warnings and 'Check mode assumes' in warnings
    assert [r for r in server.requests if r['method'] not in ('GET', 'POST')] == []
    assert [r['path'] for r in server.requests if r['method'] == 'POST'] == ['/auth/login', '/auth/logout']


def test_a_project_the_user_is_no_member_of_counts_as_missing(server, run_module):
    # Hand-written, like not_found().
    server.route('GET', '/project/999', dict(status=403, body=None))
    result = run_module(view.main, dict(project_id=999, name='anything'))
    assert result['failed'] is True and 'Project with id 999 does not exist' in result['msg']


def test_another_failure_reading_the_project_is_reported_as_it_is(server, run_module):
    server.route('GET', '/project/999', dict(status=500, body=dict(error='database is locked')))
    result = run_module(view.main, dict(project_id=999, name='anything', state='absent'))
    assert result['failed'] is True
    assert 'returned HTTP 500' in result['msg'] and 'database is locked' in result['msg']
    assert result['request_details']['status'] == 500


def test_the_cap_blocks_the_name_but_not_the_id(server, project, run_module):
    server.route('GET', '/projects', capped(server))
    by_name = run_module(view.main, dict(project='homelab', name='anything', state='absent'))
    assert by_name['failed'] is True
    assert 'returned 200 rows' in by_name['msg'] and 'Refusing to continue' in by_name['msg']
    by_id = run_module(view.main, dict(project_id=pid(server), name='anything', state='absent'))
    assert by_id.get('failed') is not True, by_id.get('msg')
    assert by_id['changed'] is False


def test_create_by_id_writes_into_that_project(server, project, run_module):
    server.route('POST', project + '/views', 'view_create')
    result = run_module(view.main, dict(project_id=pid(server), name='k8s'))
    assert result['changed'] is True
    assert result['view']['project_id'] == pid(server)
    assert server.calls('POST', project + '/views')[0]['body']['project_id'] == pid(server)
    assert server.calls('GET', '/projects') == []


def test_by_id_and_by_name_give_the_same_result(server, project, run_module):
    server.route('GET', '/projects', 'projects_one')
    server.route('GET', project + '/views', 'views_two')
    by_name = run_module(view_info.main, dict(project='homelab'))
    by_id = run_module(view_info.main, dict(project_id=pid(server)))
    assert by_name['views'] == by_id['views'] and len(by_id['views']) == 2


def test_runner_by_id_returns_the_project_name(server, project, run_module):
    # As in test_runner.py: the global runner recording under the project's
    # routes, since project runners need Semaphore Pro.
    listing = server.response('runner_list_one')
    listing['body'][0]['project_id'] = pid(server)
    server.route('GET', project + '/runners', listing)
    name = listing['body'][0]['name']
    managed = run_module(runner.main, dict(project_id=pid(server), name=name))
    assert managed['changed'] is False
    assert managed['runner']['project'] == 'homelab'
    listed = run_module(runner_info.main, dict(project_id=pid(server)))
    assert [r['project'] for r in listed['runners']] == ['homelab']
    assert server.calls('GET', '/runners') == []


def test_runner_without_a_project_is_still_global(server, run_module):
    server.route('GET', '/runners', 'runner_list_one')
    name = server.fixtures['runner_list_one']['body'][0]['name']
    result = run_module(runner.main, dict(name=name))
    assert result['changed'] is False and result['runner']['project'] is None
    assert [r['path'] for r in server.calls('GET') if r['path'].startswith('/project')] == []


def test_a_message_names_the_project_by_name(server, project, run_module):
    args = dict(project_id=pid(server), name='ansible', git_url='git@github.com:example/ansible.git',
                git_branch='main', ssh_key='deploy')
    result = run_module(repository.main, args)
    assert result['failed'] is True
    assert result['msg'] == "Key 'deploy' does not exist in project 'homelab'."
