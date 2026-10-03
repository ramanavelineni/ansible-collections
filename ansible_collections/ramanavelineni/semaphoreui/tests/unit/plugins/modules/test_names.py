# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""Names with a slash, spaces or letters outside ASCII: found by name, sent as they are, quoted where they are in a URL.

Hand-edited throughout: every recorded object has a plain ASCII name, so these
are recorded answers with the name replaced.
"""

from urllib.parse import quote

import pytest

from ansible_collections.ramanavelineni.semaphoreui.plugins.modules import (
    project,
    project_info,
    repository,
    repository_info,
    team_member,
    view,
)

NAMES = ['team/infra', 'two  words here', 'Gr\u00f6\u00dfe \u9879\u76ee', 'a&b=c?d#e', '100% done']
IDS = ['slash', 'spaces', 'non-ascii', 'url-characters', 'percent']


def renamed(server, fixture, field, old, new):
    answer = server.response(fixture)
    rows = answer['body'] if isinstance(answer['body'], list) else [answer['body']]
    for row in rows:
        if row.get(field) == old:
            row[field] = new
    return answer


@pytest.mark.parametrize('name', NAMES, ids=IDS)
def test_project_is_found_and_created_by_such_a_name(server, run_module, name):
    server.route('GET', '/projects', renamed(server, 'projects_one', 'name', 'homelab', name))
    found = run_module(project.main, dict(name=name))
    assert found['changed'] is False
    assert found['project']['name'] == name
    assert [p['name'] for p in run_module(project_info.main, dict(name=name))['projects']] == [name]

    server.route('GET', '/projects', 'projects_empty')
    server.route('POST', '/projects', renamed(server, 'project_create', 'name', 'homelab', name))
    created = run_module(project.main, dict(name=name))
    assert created['changed'] is True
    assert created['project']['name'] == name
    # The name is in the body, never in the URL.
    assert server.calls('POST', '/projects')[0]['body']['name'] == name


@pytest.mark.parametrize('name', NAMES, ids=IDS)
def test_missing_project_is_named_as_typed(server, run_module, name):
    server.route('GET', '/projects', 'projects_one')
    result = run_module(repository_info.main, dict(project=name))
    assert result['failed'] is True
    assert result['msg'].startswith('Project %r does not exist' % name)


@pytest.mark.parametrize('name', NAMES, ids=IDS)
def test_objects_in_a_project_are_referenced_by_such_names(server, run_module, name):
    server.route('GET', '/projects', renamed(server, 'projects_one', 'name', 'homelab', name))
    base = '/project/%d' % server.fixtures['projects_one']['body'][0]['id']
    repo_id = server.fixtures['repository_create']['body']['id']
    server.route('GET', base + '/keys', renamed(server, 'keys_with_deploy', 'name', 'deploy', name))
    server.route('GET', base + '/repositories', renamed(server, 'repositories_one', 'name', 'ansible', name))
    unchanged = run_module(repository.main, dict(project=name, name=name, ssh_key=name))
    assert unchanged['changed'] is False
    assert unchanged['repository']['ssh_key'] == name

    server.route('PUT', '%s/repositories/%d' % (base, repo_id), 'repository_update')
    result = run_module(repository.main, dict(project=name, name=name, git_branch='develop'))
    assert result['changed'] is True
    body = server.calls('PUT')[0]['body']
    assert body['name'] == name
    assert body['ssh_key_id'] == server.fixtures['key_create']['body']['id']
    # Ids go into the path; a name never does.
    assert all(name not in r['path'] and quote(name, safe='') not in r['path'] for r in server.requests)


@pytest.mark.parametrize('name', NAMES, ids=IDS)
def test_view_title_is_such_a_name(server, run_module, name):
    server.route('GET', '/projects', 'projects_one')
    base = '/project/%d' % server.fixtures['projects_one']['body'][0]['id']
    view_id = [v for v in server.fixtures['views_two']['body'] if v['title'] == 'k8s'][0]['id']
    server.route('GET', base + '/views', renamed(server, 'views_two', 'title', 'k8s', name))
    server.route('PUT', '%s/views/%d' % (base, view_id), 'view_update')
    result = run_module(view.main, dict(project='homelab', name=name, hidden=True))
    assert result['changed'] is True
    assert result['view']['name'] == name
    assert server.calls('PUT')[0]['body']['title'] == name


@pytest.mark.parametrize('name', NAMES, ids=IDS)
def test_user_name_in_the_search_url_is_quoted(server, run_module, name):
    server.route('GET', '/projects', 'team_projects_list')
    server.route('GET', '/user', 'team_user_current')
    pid = [p for p in server.fixtures['team_projects_list']['body'] if p['name'] == 'fixtures-team'][0]['id']
    members = '/project/%d/users' % pid
    # The search is the one request with a name in its URL. Every character
    # outside letters, digits and "_.-~" must be percent-encoded, or the query
    # ends at the first "&" or "#" and a space breaks the request line.
    search = '/users?s=' + quote(name, safe='')
    server.route('GET', search, renamed(server, 'team_users_search', 'username', 'tm-fixture-a', name))
    server.route('GET', members, renamed(server, 'team_members_two', 'username', 'tm-fixture-a', name))
    result = run_module(team_member.main, dict(project='fixtures-team', user=name, role='manager'))
    assert result.get('failed') is not True, result.get('msg')
    assert result['changed'] is False
    assert result['member']['username'] == name
    path = [r['path'] for r in server.requests if r['path'].startswith('/users?')]
    assert path == [search]
    assert path[0].isascii() and not set(path[0][len('/users?s='):]) & set(' /&=?#')
