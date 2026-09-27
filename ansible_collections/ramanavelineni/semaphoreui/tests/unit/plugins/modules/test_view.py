# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

import pytest

from ansible_collections.ramanavelineni.semaphoreui.plugins.modules import view, view_info


@pytest.fixture
def project(server):
    server.route('GET', '/projects', 'projects_one')
    return '/project/%d' % server.fixtures['projects_one']['body'][0]['id']


def view_id(server, title):
    return [v for v in server.fixtures['views_two']['body'] if v['title'] == title][0]['id']


def test_create_appends_after_last(server, project, run_module):
    server.route('GET', project + '/views', 'views_two')
    server.route('POST', project + '/views', 'view_create')
    result = run_module(view.main, dict(project='homelab', name='infra'))
    assert result['changed'] is True
    last = max(v.get('position', 0) for v in server.fixtures['views_two']['body'])
    assert server.calls('POST', project + '/views')[0]['body']['position'] == last + 1


def test_no_change(server, project, run_module):
    server.route('GET', project + '/views', 'views_two')
    result = run_module(view.main, dict(project='homelab', name='k8s', position=1))
    assert result['changed'] is False


def test_update_sends_type_back(server, project, run_module):
    server.route('GET', project + '/views', 'views_two')
    server.route('PUT', '%s/views/%d' % (project, view_id(server, 'All')), 'view_update')
    result = run_module(view.main, dict(project='homelab', name='All', hidden=True))
    assert result['changed'] is True
    body = server.calls('PUT')[0]['body']
    assert body['type'] == 'all'
    assert body['hidden'] is True
    assert body['title'] == 'All'


def test_built_in_view_is_not_deleted(server, project, run_module):
    server.route('GET', project + '/views', 'views_two')
    result = run_module(view.main, dict(project='homelab', name='All', state='absent'))
    assert result['failed'] is True
    assert 'built-in' in result['msg']
    assert server.calls('DELETE') == []


def test_delete(server, project, run_module):
    server.route('GET', project + '/views', 'views_two')
    server.route('DELETE', '%s/views/%d' % (project, view_id(server, 'k8s')), 'view_delete')
    result = run_module(view.main, dict(project='homelab', name='k8s', state='absent'))
    assert result['changed'] is True


def test_view_info(server, project, run_module):
    server.route('GET', project + '/views', 'views_two')
    result = run_module(view_info.main, dict(project='homelab'))
    assert [(v['name'], v['type']) for v in result['views']] == [('All', 'all'), ('k8s', '')]
