# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""A task whose project or registry does not exist.

state: absent on an object inside a project that is gone is already settled:
the object went with the project. In check mode the project or registry may
come from an earlier task of the same play, which check mode did not run, so
the task reports a change with a warning instead of failing. Without check
mode a present task still fails.

The fake server answers only the routes set here, so any other request (a
write, or a read below the missing project) fails the task.
"""

import json

import pytest

from ansible_collections.ramanavelineni.harbor.plugins.modules import (
    project,
    replication,
    robot_account,
    tag_immutability,
    tag_retention,
    webhook,
)

# Hand-written: the answer to GET /projects?name=<a project that does not exist>.
NO_PROJECTS = dict(status=200, body=[], headers={'x-total-count': '0'})
PERMISSIONS = [dict(access=[dict(resource='repository', action='pull')])]


def no_project(server):
    server.route('GET', '/projects', dict(NO_PROJECTS))


def no_registry(server):
    server.route('GET', '/projects', 'projects_before')
    server.route('GET', '/registries', 'registries_empty')


def no_replication_registry(server):
    server.route('GET', '/replication/policies', 'registry_replication_list_before')
    server.route('GET', '/registries', 'registries_empty')


# module, task, the module's own result key with its empty value
IN_A_PROJECT = [
    (robot_account, dict(level='project', project='gone', name='ci'), dict(robot_account={}, secret_updated=False)),
    (webhook, dict(project='gone', name='ci-notify'), dict(webhook={})),
    (tag_retention, dict(project='gone'), dict(tag_retention={})),
    (tag_immutability, dict(project='gone', tags='v*'), dict(tag_immutability={})),
]
IN_A_PROJECT_IDS = ['robot_account', 'webhook', 'tag_retention', 'tag_immutability']


@pytest.mark.parametrize('module, task, empty', IN_A_PROJECT, ids=IN_A_PROJECT_IDS)
def test_absent_in_a_deleted_project_reports_no_change(server, run_module, module, task, empty):
    no_project(server)
    result = run_module(module.main, dict(task, state='absent'))
    assert result.get('failed') is not True, result.get('msg')
    assert result['changed'] is False
    for key, value in empty.items():
        assert result[key] == value
    assert result['diff'] == dict(before={}, after={})
    # The login is checked again before the project is taken for missing
    # (an anonymous answer leaves out private projects). Nothing is read below
    # the project, and nothing is deleted.
    assert [(r['method'], r['path']) for r in server.requests] == [
        ('GET', '/systeminfo'), ('GET', '/projects'), ('GET', '/systeminfo')]


@pytest.mark.parametrize('module, task, empty', IN_A_PROJECT, ids=IN_A_PROJECT_IDS)
def test_absent_in_a_deleted_project_in_check_mode_reports_no_change(server, run_module, module, task, empty):
    no_project(server)
    result = run_module(module.main, dict(task, state='absent'), check_mode=True)
    assert result['changed'] is False
    assert not result.get('warnings')


# module, task, routes that leave its project or registry missing, empty result, the missing thing's message
PRESENT = [
    (robot_account, dict(level='project', project='gone', name='ci', permissions=PERMISSIONS), no_project,
     dict(robot_account={}, secret_updated=False), "Project 'gone' does not exist"),
    (webhook, dict(project='gone', name='ci-notify', event_types=['PUSH_ARTIFACT'], address='https://ci.example.com/hook'),
     no_project, dict(webhook={}), "Project 'gone' does not exist"),
    (tag_retention, dict(project='gone', rules=[dict(template='always')]), no_project, dict(tag_retention={}),
     "Project 'gone' does not exist"),
    (tag_immutability, dict(project='gone', tags='v*'), no_project, dict(tag_immutability={}),
     "Project 'gone' does not exist"),
    (replication, dict(name='rr-new', src_registry='hub', trigger=dict(type='manual')), no_replication_registry,
     dict(replication={}), "Registry 'hub' does not exist"),
    (project, dict(name='proxy-hub', proxy_registry='hub'), no_registry, dict(project={}),
     "Registry 'hub' does not exist"),
]
PRESENT_IDS = ['robot_account', 'webhook', 'tag_retention', 'tag_immutability', 'replication', 'project']


@pytest.mark.parametrize('module, task, routes, empty, missing', PRESENT, ids=PRESENT_IDS)
def test_check_mode_predicts_a_create_when_the_parent_comes_from_an_earlier_task(
        server, run_module, module, task, routes, empty, missing):
    routes(server)
    result = run_module(module.main, task, check_mode=True)
    assert result.get('failed') is not True, result.get('msg')
    assert result['changed'] is True
    for key, value in empty.items():
        assert result[key] == value
    assert result['diff'] == dict(before={}, after={})
    assert len(result['warnings']) == 1
    assert missing in json.dumps(result['warnings']) and 'Check mode assumes' in json.dumps(result['warnings'])
    assert [r for r in server.requests if r['method'] != 'GET'] == []


@pytest.mark.parametrize('module, task, routes, empty, missing', PRESENT, ids=PRESENT_IDS)
def test_without_check_mode_a_missing_parent_still_fails(server, run_module, module, task, routes, empty, missing):
    routes(server)
    result = run_module(module.main, task)
    assert result['failed'] is True
    assert missing in result['msg']
    assert not result.get('warnings')
    assert [r for r in server.requests if r['method'] != 'GET'] == []
