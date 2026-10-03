# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""Recorded answers no other test routes: the state after an update, empty sub-lists, and refusals.

Three recorded answers stay unused, because no module sends the request they
answer: inventory_update_absolute_path (the module refuses that update itself,
see test_inventory.py), runner_get and runner_get_deleted (the runner modules
only read the list).
"""

import json

import pytest

from ansible_collections.ramanavelineni.semaphoreui.plugins.modules import (
    integration,
    integration_info,
    inventory,
    inventory_info,
    key_store,
    repository,
    team_member,
    template,
    user,
)


def fid(server, fixture):
    return server.fixtures[fixture]['body']['id']


@pytest.fixture
def project(server):
    server.route('GET', '/projects', 'projects_one')
    return '/project/%d' % server.fixtures['projects_one']['body'][0]['id']


# -- an integration that has no matchers and no extracted values yet -------------

@pytest.fixture
def bare_integration(server, project):
    path = '%s/integrations/%d' % (project, fid(server, 'integration_create'))
    server.route('GET', project + '/templates', 'templates_one')
    server.route('GET', project + '/keys', 'keys_with_deploy')
    server.route('GET', project + '/integrations', 'integrations_one')
    server.route('GET', path, 'integration_get')
    server.route('GET', path + '/matchers', 'integration_matchers_empty')
    server.route('GET', path + '/values', 'integration_values_empty')
    server.route('GET', path + '/aliases', 'integration_aliases_one')
    return path


def test_integration_without_items_is_reported_with_empty_lists(server, bare_integration, run_module):
    result = run_module(integration_info.main, dict(project='homelab'))
    assert result['integrations'][0]['matchers'] == []
    assert result['integrations'][0]['extract_values'] == []
    unchanged = run_module(integration.main, dict(project='homelab', name='gh', matchers=[], extract_values=[]))
    assert unchanged['changed'] is False


def test_integration_without_items_gets_the_declared_ones(server, bare_integration, run_module):
    server.route('POST', bare_integration + '/matchers', 'integration_matcher_create')
    server.route('POST', bare_integration + '/values', 'integration_value_create')
    result = run_module(integration.main, dict(
        project='homelab', name='gh', matchers=[dict(name='main', key='ref', value='refs/heads/main')],
        extract_values=[dict(name='sha', key='after', variable='COMMIT_SHA')]))
    assert result['changed'] is True
    assert result['diff']['before']['matchers'] == [] and result['diff']['before']['extract_values'] == []
    assert [m['name'] for m in result['integration']['matchers']] == ['main']
    assert server.calls('POST', bare_integration + '/matchers')[0]['body']['integration_id'] == fid(server, 'integration_create')
    assert server.calls('POST', bare_integration + '/values')[0]['body']['variable'] == 'COMMIT_SHA'
    assert server.calls('PUT') == [] and server.calls('DELETE') == []


# -- the inventory list while a Terraform-family template owns a workspace inventory

def test_inventory_list_without_the_workspace_inventory(server, project, run_module):
    server.route('GET', project + '/keys', 'keys_with_deploy')
    server.route('GET', project + '/repositories', 'repositories_one')
    server.route('GET', project + '/inventory', 'inventory_list_hides_workspace')
    listed = run_module(inventory_info.main, dict(project='homelab'))
    # The workspace inventory ("default") belongs to its template and is not listed.
    assert [i['name'] for i in listed['inventories']] == ['homelab']
    assert listed['inventories'][0]['become_key'] == 'deploy'
    result = run_module(inventory.main, dict(project='homelab', name='homelab', become_key='deploy'))
    assert result['changed'] is False
    assert result['inventory'] == listed['inventories'][0]


# -- what the server lists after an update: the same task again changes nothing ---

def test_key_after_a_type_change_is_no_change(server, project, run_module):
    server.route('GET', project + '/repositories', 'repositories_empty')
    server.route('GET', project + '/keys', 'keys_with_deploy_updated')
    result = run_module(key_store.main, dict(project='homelab', name='deploy', type='login_password',
                                             login_password=dict(login='git', password='pw-unit'),
                                             update_secret='on_create'))
    assert result['changed'] is False and result['secret_updated'] is False
    assert result['key']['type'] == 'login_password'
    # The stored type is what decides: the old one is a change again.
    server.route('PUT', '%s/keys/%d' % (project, fid(server, 'key_create')), 'key_update')
    back = run_module(key_store.main, dict(project='homelab', name='deploy', type='ssh', ssh=dict(private_key='k'),
                                           update_secret='on_create'))
    assert back['changed'] is True
    assert (back['diff']['before']['type'], back['diff']['after']['type']) == ('login_password', 'ssh')


def test_repository_after_an_update_is_no_change(server, project, run_module):
    server.route('GET', project + '/keys', 'keys_with_deploy')
    server.route('GET', project + '/repositories', 'repositories_one_updated')
    result = run_module(repository.main, dict(project='homelab', name='ansible', git_branch='develop'))
    assert result['changed'] is False
    assert result['repository']['git_branch'] == 'develop'
    assert server.calls('PUT') == []


def test_template_after_an_update_is_no_change(server, project, run_module):
    path = '%s/templates/%d' % (project, fid(server, 'template_create'))
    server.route('GET', project + '/repositories', 'repositories_one')
    server.route('GET', project + '/inventory', 'inventories_one')
    server.route('GET', project + '/environment', 'variable_groups_for_templates')
    server.route('GET', project + '/views', 'views_two')
    server.route('GET', project + '/keys', 'keys_with_deploy')
    server.route('GET', project + '/templates', 'templates_one')
    server.route('GET', path, 'template_get_updated')
    result = run_module(template.main, dict(project='homelab', name='site', description='updated'))
    assert result['changed'] is False
    assert result['template']['description'] == 'updated'
    assert server.calls('PUT') == []
    # Against what was stored before, the same task is a change.
    server.route('GET', path, 'template_get')
    server.route('PUT', path, 'template_update')
    assert run_module(template.main, dict(project='homelab', name='site', description='updated'))['changed'] is True


# -- refusals the modules normally prevent, reported as the server gives them ----

def test_key_that_came_into_use_after_the_check(server, project, run_module):
    path = '%s/keys/%d' % (project, fid(server, 'key_create'))
    server.route('GET', project + '/repositories', 'repositories_empty')
    server.route('GET', project + '/keys', 'keys_with_deploy')
    server.route('GET', path + '/refs', 'key_refs_unused')
    server.route('DELETE', path, 'key_delete_in_use')
    result = run_module(key_store.main, dict(project='homelab', name='deploy', state='absent'))
    assert result['failed'] is True
    assert 'HTTP 400' in result['msg']
    # 2.18 refuses without a body; 2.19 says why.
    reason = (server.fixtures['key_delete_in_use']['body'] or {}).get('error', '(empty body)')
    assert reason in result['msg']
    assert result['request_details']['method'] == 'DELETE'


def test_refused_member_is_reported(server, run_module):
    server.route('GET', '/projects', 'team_projects_list')
    server.route('GET', '/user', 'team_user_current')
    server.route('GET', '/users?s=tm-fixture-a', 'team_users_search')
    pid = [p for p in server.fixtures['team_projects_list']['body'] if p['name'] == 'fixtures-team'][0]['id']
    base = '/project/%d/users' % pid
    server.route('GET', base, 'team_members_initial')
    # Recorded with a role Semaphore doesn't know; the module's choices keep such a role from being sent.
    server.route('POST', base, 'team_member_add_bad_role')
    result = run_module(team_member.main, dict(project='fixtures-team', user='tm-fixture-a', role='guest'))
    assert result['failed'] is True
    assert 'HTTP 400' in result['msg']
    assert result['request_details']['request'] == dict(user_id=server.fixtures['team_users_search']['body'][0]['id'],
                                                        role='guest')


def user_routes(server, keep):
    listing = server.response('user_list')
    listing['body'] = [u for u in listing['body'] if keep(u)]
    server.route('GET', '/user', 'user_me')
    server.route('GET', '/users', listing)


def test_email_taken_between_the_check_and_the_create(server, run_module):
    new = server.fixtures['user_create']['body']
    # The list doesn't show the other user yet, so the module's own check passes.
    user_routes(server, lambda u: u['email'] != new['email'])
    server.route('POST', '/users', 'user_create_duplicate_email')
    result = run_module(user.main, dict(login='somebody-else', name='S', email=new['email'], user_password='pw-unit-9'))
    assert result['failed'] is True
    assert 'HTTP 400' in result['msg']
    assert len(server.calls('POST', '/users')) == 1
    assert 'pw-unit-9' not in json.dumps(result)


def test_password_refused_for_a_user_the_list_shows_as_local(server, run_module):
    external = server.response('user_list')
    for row in external['body']:
        row['external'] = False
    server.route('GET', '/user', 'user_me')
    server.route('GET', '/users', external)
    target = server.fixtures['user_create_external']['body']
    server.route('POST', '/users/%d/password' % target['id'], 'user_password_external')
    result = run_module(user.main, dict(login=target['username'], user_password='pw-unit-8'))
    assert result['failed'] is True
    assert 'HTTP 400' in result['msg']
    assert 'pw-unit-8' not in json.dumps(result)
