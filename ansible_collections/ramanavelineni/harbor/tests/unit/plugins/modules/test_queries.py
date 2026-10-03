# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""The filters the modules put in the query string.

The fake server routes by method and path alone, so a wrong filter would still
get the recorded answer. These tests read the query of the request the module
sent. (The `?name=` project lookup of the `_info` modules and of `project`,
`webhook` and `robot_account` is asserted in test_anonymous_reads.py.)
"""

import pytest

from ansible_collections.ramanavelineni.harbor.plugins.modules import (
    project,
    project_info,
    robot_account,
    robot_account_info,
    tag_immutability,
    tag_retention,
)

PULL_ALL = [dict(namespace='*', access=[dict(resource='repository', action='pull')])]


def only(server, path):
    """The query of the one GET the module sent to `path`."""
    calls = server.calls('GET', path)
    assert len(calls) == 1
    return calls[0]['query']


def robot_project_id(server):
    return server.fixtures['robot_projects_by_name']['body'][0]['project_id']


def core_project_id(server):
    return int(server.fixtures['project_create']['headers']['location'].rsplit('/', 1)[-1])


def tag_project_id(server):
    return int(server.fixtures['tag_project_create']['headers']['location'].rsplit('/', 1)[-1])


# -- robot accounts ---------------------------------------------------------------

def test_system_robot_is_looked_up_by_level_and_name(server, run_module):
    server.route('GET', '/robots', 'robot_list_system')
    result = run_module(robot_account.main, dict(name='fixtures-robot-sys'))
    assert result['changed'] is False
    assert only(server, '/robots')['q'] == ['Level=system,name=fixtures-robot-sys']


def test_system_robot_lookup_carries_the_name_it_was_given(server, run_module):
    # Another name gets another filter, although the fake server answers the same list.
    server.route('GET', '/robots', 'robot_list_system_empty')
    result = run_module(robot_account.main, dict(name='other-robot', state='absent'))
    assert result['changed'] is False
    assert only(server, '/robots')['q'] == ['Level=system,name=other-robot']


def test_project_robot_is_looked_up_in_its_project(server, run_module):
    server.route('GET', '/projects', 'robot_projects_by_name')
    server.route('GET', '/robots', 'robot_list_project')
    result = run_module(robot_account.main, dict(name='ci', level='project', project='fixtures-robot'))
    assert result['changed'] is False
    assert only(server, '/projects')['name'] == ['fixtures-robot']
    assert only(server, '/robots')['q'] == ['Level=project,ProjectID=%d' % robot_project_id(server)]


def test_project_robot_lookup_uses_the_id_of_the_project_that_was_found(server, run_module):
    # Hand-edited: the recorded project under another id. The filter has to follow it.
    listing = server.response('robot_projects_by_name')
    listing['body'][0]['project_id'] = 4711
    server.route('GET', '/projects', listing)
    server.route('GET', '/robots', 'robot_list_project')
    run_module(robot_account.main, dict(name='ci', level='project', project='fixtures-robot'))
    assert only(server, '/robots')['q'] == ['Level=project,ProjectID=4711']


def test_info_lists_system_robots_by_level(server, run_module):
    server.route('GET', '/robots', 'robot_list_system_all')
    server.route('GET', '/configurations', 'robot_configurations')
    result = run_module(robot_account_info.main, {})
    assert [r['name'] for r in result['robot_accounts']] == ['fixtures-robot-sys']
    assert only(server, '/robots')['q'] == ['Level=system']
    # No project was named, so none is looked up.
    assert server.calls('GET', '/projects') == []


def test_info_lists_project_robots_by_project_id(server, run_module):
    server.route('GET', '/projects', 'robot_projects_by_name')
    server.route('GET', '/robots', 'robot_list_project')
    server.route('GET', '/configurations', 'robot_configurations')
    result = run_module(robot_account_info.main, dict(project='fixtures-robot'))
    assert [r['name'] for r in result['robot_accounts']] == ['ci']
    assert only(server, '/projects')['name'] == ['fixtures-robot']
    assert only(server, '/robots')['q'] == ['Level=project,ProjectID=%d' % robot_project_id(server)]


def test_info_name_is_not_sent_as_a_filter(server, run_module):
    # The stored name carries a prefix the module has to read first, so `name`
    # is applied to the answer, not put in the query.
    server.route('GET', '/robots', 'robot_list_system_all')
    server.route('GET', '/configurations', 'robot_configurations')
    result = run_module(robot_account_info.main, dict(name='no-such-robot'))
    assert result['robot_accounts'] == []
    assert only(server, '/robots')['q'] == ['Level=system']


# -- projects ---------------------------------------------------------------------

def test_project_quota_is_read_for_that_project(server, run_module):
    server.route('GET', '/projects', 'projects_with_created')
    server.route('GET', '/quotas', 'quotas_created')
    result = run_module(project.main, dict(name='fixtures-core'))
    assert result['changed'] is False
    assert only(server, '/projects')['name'] == ['fixtures-core']
    query = only(server, '/quotas')
    assert query['reference'] == ['project']
    assert query['reference_id'] == [str(core_project_id(server))]


def test_project_quota_is_read_again_for_that_project_after_a_write(server, run_module):
    server.route('GET', '/projects', 'projects_with_created')
    server.route('GET', '/quotas', 'quotas_created', 'quotas_created_updated')
    server.route('PUT', '/quotas/%d' % server.fixtures['quotas_created']['body'][0]['id'], 'quota_update')
    server.route('GET', '/projects/%d' % core_project_id(server), 'project_get')
    result = run_module(project.main, dict(name='fixtures-core', quota_gb=-1))
    assert result['changed'] is True
    queries = [call['query'] for call in server.calls('GET', '/quotas')]
    assert len(queries) == 2
    for query in queries:
        assert (query['reference'], query['reference_id']) == (['project'], [str(core_project_id(server))])


def test_project_info_reads_project_quotas_only(server, run_module):
    server.route('GET', '/projects', 'projects_with_created')
    server.route('GET', '/quotas', 'quotas_all')
    result = run_module(project_info.main, dict(name='fixtures-core'))
    assert [p['name'] for p in result['projects']] == ['fixtures-core']
    query = only(server, '/quotas')
    assert query['reference'] == ['project']
    assert 'reference_id' not in query
    # project_info lists every project and picks the name itself.
    assert 'name' not in only(server, '/projects')


# -- the tag modules find their project by name -----------------------------------

@pytest.mark.parametrize('main, args', [
    (tag_immutability.main, dict(project='fixtures-tag-policy', tags='v*', state='absent')),
    (tag_retention.main, dict(project='fixtures-tag-policy', state='absent')),
], ids=['tag_immutability', 'tag_retention'])
def test_tag_modules_look_their_project_up_by_name(server, run_module, main, args):
    server.route('GET', '/projects', 'tag_projects_list')
    server.route('GET', '/projects/%d' % tag_project_id(server), 'tag_project_get')
    server.route('GET', '/projects/%d/immutabletagrules' % tag_project_id(server), 'tag_immutability_list_empty')
    result = run_module(main, args)
    assert result['changed'] is False
    assert only(server, '/projects')['name'] == ['fixtures-tag-policy']
