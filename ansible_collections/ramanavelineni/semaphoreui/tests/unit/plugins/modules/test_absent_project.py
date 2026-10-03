# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""state: absent in a project that doesn't exist: deleting a project deletes everything in it."""

import pytest

from ansible_collections.ramanavelineni.semaphoreui.plugins.modules import (
    integration,
    inventory,
    key_store,
    repository,
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
def test_absent_in_missing_project_is_unchanged(server, run_module, module, key, extra):
    server.route('GET', '/projects', 'projects_empty')
    result = run_module(module.main, dict(extra, project='gone', name='anything', state='absent'))
    assert result.get('failed') is not True, result.get('msg')
    assert result['changed'] is False
    assert result[key] == {}
    assert result['diff'] == dict(before={}, after={})


def test_absent_member_in_missing_project_is_unchanged(server, run_module):
    server.route('GET', '/projects', 'projects_empty')
    result = run_module(team_member.main, dict(project='gone', user='alice', state='absent'))
    assert result['changed'] is False and result['member'] == {}


def test_present_in_missing_project_still_fails(server, run_module):
    server.route('GET', '/projects', 'projects_empty')
    result = run_module(view.main, dict(project='gone', name='anything'))
    assert result['failed'] is True
    assert "Project 'gone' does not exist" in result['msg']
