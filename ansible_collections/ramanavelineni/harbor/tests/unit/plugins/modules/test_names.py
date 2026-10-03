# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""Names with a slash, a space, characters outside ASCII, or characters that mean something in a URL.

What Harbor makes of such a name is Harbor's business and is not recorded.
These tests show what the modules do with one: a name goes into the query
string or the request body intact, never into a path, and a robot account
name Harbor's rule forbids is refused before anything is sent.
"""

import pytest

from ansible_collections.ramanavelineni.harbor.plugins.modules import (
    project,
    registry,
    replication,
    robot_account,
    webhook,
)

NAMES = ['team/app', 'my project', 'r\u00e9gistre-\u00fc', 'a&b=c', 'x#1+y%20']
IDS = ['slash', 'space', 'non-ascii', 'ampersand', 'hash-plus-percent']
PULL_ALL = [dict(namespace='*', access=[dict(resource='repository', action='pull')])]


def location_id(server, fixture):
    return int(server.fixtures[fixture]['headers']['location'].rsplit('/', 1)[-1])


def renamed(server, fixture, name, index=0):
    """Hand-edited: a recorded list with one object under another name. No such name was recorded."""
    listing = server.response(fixture)
    listing['body'][index]['name'] = name
    return listing


def paths(server):
    return [r['path'] for r in server.requests]


# -- projects: the name is a query parameter ----------------------------------------

@pytest.mark.parametrize('name', NAMES, ids=IDS)
def test_project_lookup_sends_the_name_intact(server, run_module, name):
    server.route('GET', '/projects', 'projects_before')
    result = run_module(project.main, dict(name=name, state='absent', confirm_delete=True))
    assert result.get('failed') is not True, result.get('msg')
    assert result['changed'] is False
    looked_up = server.calls('GET', '/projects')
    assert len(looked_up) == 1
    # One parameter, whole: nothing in the name ended it early or started another.
    assert looked_up[0]['query']['name'] == [name]
    assert sorted(looked_up[0]['query']) == ['name', 'page', 'page_size']
    assert all(path in ('/systeminfo', '/projects') for path in paths(server))


@pytest.mark.parametrize('name', NAMES, ids=IDS)
def test_project_create_would_send_the_name_intact(server, run_module, name):
    # Check mode: whether Harbor takes such a name was not recorded, so nothing is sent.
    server.route('GET', '/projects', 'projects_before')
    result = run_module(project.main, dict(name=name), check_mode=True)
    assert result['changed'] is True
    assert result['project']['name'] == name
    assert server.calls('POST') == []


@pytest.mark.parametrize('name', NAMES, ids=IDS)
def test_project_found_under_such_a_name_is_deleted_by_id(server, run_module, name):
    pid = location_id(server, 'project_create')
    listing = server.response('projects_with_created')
    for item in listing['body']:
        if item['project_id'] == pid:
            # Hand-edited: the recorded project under this name.
            item['name'] = name
    server.route('GET', '/projects', listing)
    server.route('DELETE', '/projects/%d' % pid, 'project_delete')
    result = run_module(project.main, dict(name=name, state='absent', confirm_delete=True))
    assert result['changed'] is True
    assert result['diff']['before']['name'] == name
    assert [r['path'] for r in server.calls('DELETE')] == ['/projects/%d' % pid]


# -- registries, replication rules, webhooks: the name is matched in the list ---------

def registry_case(server, name):
    server.route('GET', '/registries', renamed(server, 'registry_list', name))
    path = '/registries/%d' % location_id(server, 'registry_create')
    server.route('DELETE', path, 'registry_delete')
    return registry.main, dict(name=name, state='absent'), path


def replication_case(server, name):
    server.route('GET', '/replication/policies', renamed(server, 'registry_replication_list', name))
    path = '/replication/policies/%d' % location_id(server, 'registry_replication_create')
    server.route('DELETE', path, 'registry_replication_delete')
    return replication.main, dict(name=name, state='absent'), path


def webhook_case(server, name):
    server.route('GET', '/projects', 'webhook_projects')
    base = '/projects/%d/webhook/policies' % server.fixtures['webhook_projects']['body'][0]['project_id']
    server.route('GET', base, renamed(server, 'webhook_list_one', name))
    path = '%s/%d' % (base, server.fixtures['webhook_get']['body']['id'])
    server.route('DELETE', path, 'webhook_delete')
    return webhook.main, dict(project='fixtures-webhook', name=name, state='absent'), path


@pytest.mark.parametrize('case', [registry_case, replication_case, webhook_case], ids=['registry', 'replication', 'webhook'])
@pytest.mark.parametrize('name', NAMES, ids=IDS)
def test_object_found_under_such_a_name_is_deleted_by_id(server, run_module, case, name):
    main, args, path = case(server, name)
    result = run_module(main, args)
    assert result.get('failed') is not True, result.get('msg')
    assert result['changed'] is True
    assert result['diff']['before']['name'] == name
    assert [r['path'] for r in server.calls('DELETE')] == [path]
    # The name is in no path and no query: these lists are matched in the module.
    assert all(name not in r['path'] for r in server.requests)
    assert all(name not in sum(r['query'].values(), []) for r in server.requests if r['path'] != '/projects')


@pytest.mark.parametrize('case', [registry_case, replication_case, webhook_case], ids=['registry', 'replication', 'webhook'])
@pytest.mark.parametrize('name', NAMES, ids=IDS)
def test_a_name_only_matches_itself(server, run_module, case, name):
    # The list holds the object under `name`; a task for a name that merely starts the same finds nothing.
    main, args, dummy_path = case(server, name)
    result = run_module(main, dict(args, name=name + 'x'))
    assert result['changed'] is False
    assert server.calls('DELETE') == []


# -- robot accounts: Harbor's rule for the name is checked first ------------------------

@pytest.mark.parametrize('name', NAMES + ['Robot', 'trailing-', '.leading', 'double--dash'],
                         ids=IDS + ['upper-case', 'trailing-separator', 'leading-separator', 'two-separators'])
def test_robot_name_outside_harbors_rule_is_refused_before_anything_is_sent(server, run_module, name):
    result = run_module(robot_account.main, dict(name=name, permissions=PULL_ALL))
    assert result['failed'] is True
    assert 'must be lower-case letters and digits' in result['msg']
    assert paths(server) == ['/systeminfo']


@pytest.mark.parametrize('name', ['ci', 'ci-2', 'build.bot', 'a_b-c.d9'])
def test_robot_name_inside_harbors_rule_reaches_the_lookup(server, run_module, name):
    server.route('GET', '/robots', 'robot_list_system_empty')
    result = run_module(robot_account.main, dict(name=name, state='absent'))
    assert result['changed'] is False
    assert server.calls('GET', '/robots')[0]['query']['q'] == ['Level=system,name=%s' % name]


@pytest.mark.parametrize('project_name', NAMES, ids=IDS)
def test_robot_project_lookup_sends_the_project_name_intact(server, run_module, project_name):
    # Hand-edited: the recorded project under this name.
    server.route('GET', '/projects', renamed(server, 'robot_projects_by_name', project_name))
    server.route('GET', '/robots', 'robot_list_system_empty')
    result = run_module(robot_account.main, dict(name='ci', level='project', project=project_name, state='absent'))
    assert result.get('failed') is not True, result.get('msg')
    assert server.calls('GET', '/projects')[0]['query']['name'] == [project_name]
    project_id = server.fixtures['robot_projects_by_name']['body'][0]['project_id']
    assert server.calls('GET', '/robots')[0]['query']['q'] == ['Level=project,ProjectID=%d' % project_id]
