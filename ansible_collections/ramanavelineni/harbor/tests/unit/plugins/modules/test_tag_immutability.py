# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

import pytest

from ansible_collections.ramanavelineni.harbor.plugins.modules import tag_immutability, tag_immutability_info

PROJECT = 'fixtures-tag-policy'


def pid(server):
    return int(server.fixtures['tag_project_create']['headers']['location'].rsplit('/', 1)[-1])


def iid(server):
    return int(server.fixtures['tag_immutability_create']['headers']['location'].rsplit('/', 1)[-1])


def base(server):
    return '/projects/%d/immutabletagrules' % pid(server)


@pytest.fixture
def project(server):
    server.route('GET', '/projects', 'tag_projects_list')
    server.route('GET', '/projects/%d' % pid(server), 'tag_project_get')
    return server


def test_create(project, run_module):
    server = project
    server.route('GET', base(server), 'tag_immutability_list_empty')
    server.route('POST', base(server), 'tag_immutability_create')
    result = run_module(tag_immutability.main, dict(project=PROJECT, tags='v*'))
    assert result['changed'] is True
    assert result['tag_immutability']['id'] == iid(server)
    assert server.calls('POST', base(server))[0]['body'] == dict(
        disabled=False, action='immutable', template='immutable_template',
        tag_selectors=[dict(kind='doublestar', decoration='matches', pattern='v*')],
        scope_selectors=dict(repository=[dict(kind='doublestar', decoration='repoMatches', pattern='**')]))
    assert server.calls('PUT') == []


def test_create_disabled_needs_a_toggle(project, run_module):
    server = project
    server.route('GET', base(server), 'tag_immutability_list_empty')
    server.route('POST', base(server), 'tag_immutability_create')
    server.route('PUT', '%s/%d' % (base(server), iid(server)), 'tag_immutability_toggle')
    result = run_module(tag_immutability.main, dict(project=PROJECT, tags='v*', disabled=True))
    assert result['changed'] is True
    assert result['tag_immutability']['disabled'] is True
    assert server.calls('POST', base(server))[0]['body']['disabled'] is False
    put = server.calls('PUT')[0]['body']
    assert put['disabled'] is True and put['id'] == iid(server)


def test_create_check_mode(project, run_module):
    server = project
    server.route('GET', base(server), 'tag_immutability_list_empty')
    result = run_module(tag_immutability.main, dict(project=PROJECT, tags='v*'), check_mode=True)
    assert result['changed'] is True
    assert server.calls('POST') == []


def test_no_change(project, run_module):
    server = project
    server.route('GET', base(server), 'tag_immutability_list_one')
    result = run_module(tag_immutability.main, dict(project=PROJECT, tags='v*'))
    assert result['changed'] is False
    assert result['tag_immutability']['id'] == iid(server)


def test_other_patterns_are_another_rule(project, run_module):
    server = project
    server.route('GET', base(server), 'tag_immutability_list_one')
    server.route('POST', base(server), 'tag_immutability_create')
    result = run_module(tag_immutability.main, dict(project=PROJECT, tags='v*', tags_decoration='excludes'))
    assert result['changed'] is True
    assert server.calls('POST', base(server))[0]['body']['tag_selectors'][0]['decoration'] == 'excludes'


def test_disable(project, run_module):
    server = project
    server.route('GET', base(server), 'tag_immutability_list_one')
    server.route('PUT', '%s/%d' % (base(server), iid(server)), 'tag_immutability_toggle')
    result = run_module(tag_immutability.main, dict(project=PROJECT, tags='v*', disabled=True))
    assert result['changed'] is True
    assert result['diff']['before']['disabled'] is False
    assert server.calls('PUT')[0]['body']['disabled'] is True


def test_disabled_already(project, run_module):
    server = project
    server.route('GET', base(server), 'tag_immutability_list_disabled')
    result = run_module(tag_immutability.main, dict(project=PROJECT, tags='v*', disabled=True))
    assert result['changed'] is False


def test_delete(project, run_module):
    server = project
    server.route('GET', base(server), 'tag_immutability_list_one')
    server.route('DELETE', '%s/%d' % (base(server), iid(server)), 'tag_immutability_delete')
    result = run_module(tag_immutability.main, dict(project=PROJECT, tags='v*', state='absent'))
    assert result['changed'] is True


def test_delete_missing(project, run_module):
    server = project
    server.route('GET', base(server), 'tag_immutability_list_empty')
    result = run_module(tag_immutability.main, dict(project=PROJECT, tags='v*', state='absent'))
    assert result['changed'] is False


def test_duplicate_reported(project, run_module):
    server = project
    server.route('GET', base(server), 'tag_immutability_list_empty')
    server.route('POST', base(server), 'tag_immutability_create_duplicate')
    result = run_module(tag_immutability.main, dict(project=PROJECT, tags='v*'))
    assert result['failed'] is True
    assert 'already exists' in result['msg']


def test_info(project, run_module):
    server = project
    server.route('GET', base(server), 'tag_immutability_list_disabled')
    result = run_module(tag_immutability_info.main, dict(project=PROJECT))
    assert result['tag_immutability'] == [dict(
        id=iid(server), project=PROJECT, repositories='**', repositories_decoration='matches',
        tags='v*', tags_decoration='matches', disabled=True)]
