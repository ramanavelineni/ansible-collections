# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""Check mode when what a task refers to doesn't exist yet: an earlier task would have created it."""

import json

import pytest

from ansible_collections.ramanavelineni.semaphoreui.plugins.modules import (
    integration,
    inventory,
    key_store,
    repository,
    repository_info,
    runner,
    schedule,
    team_member,
    template,
    variable_group,
    view,
)

MODULES = [
    (integration, 'integration', {}),
    (inventory, 'inventory', {}),
    (key_store, 'key', dict(type='none')),
    (repository, 'repository', {}),
    (runner, 'runner', {}),
    (schedule, 'schedule', {}),
    (template, 'template', {}),
    (variable_group, 'variable_group', {}),
    (view, 'view', {}),
]


@pytest.mark.parametrize('module, key, extra', MODULES, ids=[m[1] for m in MODULES])
def test_missing_project_is_a_change_in_check_mode(server, run_module, module, key, extra):
    server.route('GET', '/projects', 'projects_empty')
    result = run_module(module.main, dict(extra, project='new', name='anything'), check_mode=True)
    assert result.get('failed') is not True, result.get('msg')
    assert result['changed'] is True
    assert result[key] == {}
    assert result['diff'] == dict(before={}, after={})
    # A warning is a string, or a dict from ansible-core 2.19 on.
    warnings = json.dumps(result['warnings'])
    assert "Project 'new' does not exist" in warnings and 'Check mode assumes' in warnings
    assert [r for r in server.requests if r['method'] not in ('GET', 'POST')] == []
    assert [r['path'] for r in server.requests if r['method'] == 'POST'] == ['/auth/login', '/auth/logout']


@pytest.mark.parametrize('module, key, extra', MODULES, ids=[m[1] for m in MODULES])
def test_missing_project_still_fails_outside_check_mode(server, run_module, module, key, extra):
    server.route('GET', '/projects', 'projects_empty')
    result = run_module(module.main, dict(extra, project='new', name='anything'))
    assert result['failed'] is True
    assert "Project 'new' does not exist" in result['msg']


def test_missing_member_project_in_check_mode(server, run_module):
    server.route('GET', '/projects', 'projects_empty')
    result = run_module(team_member.main, dict(project='new', user='alice', role='owner'), check_mode=True)
    assert result['changed'] is True and result['member'] == {}


def test_missing_key_is_a_change_in_check_mode(server, run_module):
    server.route('GET', '/projects', 'projects_one')
    base = '/project/%d' % server.fixtures['projects_one']['body'][0]['id']
    server.route('GET', base + '/keys', 'keys_new_project')
    server.route('GET', base + '/repositories', 'repositories_empty')
    args = dict(project='homelab', name='ansible', git_url='git@github.com:example/ansible.git',
                git_branch='main', ssh_key='deploy')
    checked = run_module(repository.main, args, check_mode=True)
    assert checked['changed'] is True and checked['repository'] == {}
    assert "Key 'deploy' does not exist" in json.dumps(checked['warnings'])
    real = run_module(repository.main, args)
    assert real['failed'] is True and "Key 'deploy' does not exist" in real['msg']


def test_info_module_still_fails_in_check_mode(server, run_module):
    server.route('GET', '/projects', 'projects_empty')
    result = run_module(repository_info.main, dict(project='new'), check_mode=True)
    assert result['failed'] is True
