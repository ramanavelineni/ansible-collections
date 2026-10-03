# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

import pytest

from ansible_collections.ramanavelineni.semaphoreui.plugins.modules import integration, integration_info

GH = dict(project='homelab', name='gh', template='site', auth_method='token', auth_key='deploy', auth_header='X-Token',
          matchers=[dict(name='main', key='ref', value='refs/heads/main')],
          extract_values=[dict(name='sha', key='after', variable='COMMIT_SHA')])


@pytest.fixture
def project(server):
    server.route('GET', '/projects', 'projects_one')
    base = '/project/%d' % server.fixtures['projects_one']['body'][0]['id']
    server.route('GET', base + '/templates', 'templates_one')
    server.route('GET', base + '/keys', 'keys_with_deploy')
    return base


def ipath(server, project):
    return '%s/integrations/%d' % (project, server.fixtures['integration_create']['body']['id'])


def existing(server, project):
    path = ipath(server, project)
    server.route('GET', project + '/integrations', 'integrations_one')
    server.route('GET', path, 'integration_get')
    server.route('GET', path + '/matchers', 'integration_matchers_one')
    server.route('GET', path + '/values', 'integration_values_one')
    server.route('GET', path + '/aliases', 'integration_aliases_one')
    return path


def test_create_with_items_and_alias(server, project, run_module):
    path = ipath(server, project)
    server.route('GET', project + '/integrations', 'integrations_empty')
    server.route('POST', project + '/integrations', 'integration_create')
    server.route('POST', path + '/matchers', 'integration_matcher_create')
    server.route('POST', path + '/values', 'integration_value_create')
    server.route('POST', path + '/aliases', 'integration_alias_create')
    result = run_module(integration.main, GH)
    assert result['changed'] is True
    assert result['webhook_urls'] == [server.fixtures['integration_alias_create']['body']['url']]
    body = server.calls('POST', project + '/integrations')[0]['body']
    assert body['auth_method'] == 'token' and body['auth_header'] == 'X-Token'
    assert body['auth_secret_id'] == server.fixtures['key_create']['body']['id']
    assert server.calls('POST', path + '/matchers')[0]['body']['key'] == 'ref'


def test_create_check_mode(server, project, run_module):
    server.route('GET', project + '/integrations', 'integrations_empty')
    result = run_module(integration.main, GH, check_mode=True)
    assert result['changed'] is True
    assert result['webhook_urls'] == []
    assert [c for c in server.calls('POST') if not c['path'].startswith('/auth/')] == []


def test_auth_needs_key_and_header(server, project, run_module):
    server.route('GET', project + '/integrations', 'integrations_empty')
    result = run_module(integration.main, dict(GH, auth_key=None))
    assert result['failed'] is True and 'auth_key' in result['msg']
    result = run_module(integration.main, dict(GH, auth_header=None))
    assert result['failed'] is True and 'auth_header' in result['msg']


def test_no_change(server, project, run_module):
    existing(server, project)
    matchers = [dict(name='main', key='ref', value='refs/heads/main')]
    result = run_module(integration.main, dict(GH, matchers=matchers))
    assert result['changed'] is False
    assert server.calls('PUT') == [] and server.calls('DELETE') == []


def test_update_fields_keeps_task_params(server, project, run_module):
    path = existing(server, project)
    server.route('PUT', path, 'integration_update')
    result = run_module(integration.main, dict(project='homelab', name='gh', searchable=True))
    assert result['changed'] is True
    body = server.calls('PUT', path)[0]['body']
    current = server.fixtures['integration_get']['body']
    assert body['searchable'] is True
    assert body.get('task_params') == current.get('task_params')
    assert body['id'] == current['id']


def test_matchers_exact(server, project, run_module):
    path = existing(server, project)
    mid = server.fixtures['integration_matcher_create']['body']['id']
    server.route('PUT', '%s/matchers/%d' % (path, mid), 'integration_matcher_update')
    server.route('POST', path + '/matchers', 'integration_matcher_create')
    result = run_module(integration.main, dict(project='homelab', name='gh', matchers=[
        dict(name='main', key='ref', value='refs/heads/develop'),
        dict(name='event', match_type='header', key='X-GitHub-Event', value='push')]))
    assert result['changed'] is True
    assert server.calls('PUT', '%s/matchers/%d' % (path, mid))[0]['body']['value'] == 'refs/heads/develop'
    assert server.calls('POST', path + '/matchers')[0]['body']['name'] == 'event'


def test_extra_items_deleted(server, project, run_module):
    path = existing(server, project)
    mid = server.fixtures['integration_matcher_create']['body']['id']
    vid = server.fixtures['integration_value_create']['body']['id']
    server.route('DELETE', '%s/matchers/%d' % (path, mid), 'integration_matcher_delete')
    server.route('DELETE', '%s/values/%d' % (path, vid), 'integration_matcher_delete')
    result = run_module(integration.main, dict(project='homelab', name='gh', matchers=[], extract_values=[]))
    assert result['changed'] is True
    assert sorted(c['path'] for c in server.calls('DELETE')) == sorted(
        ['%s/matchers/%d' % (path, mid), '%s/values/%d' % (path, vid)])


def test_alias_created_when_missing(server, project, run_module):
    path = existing(server, project)
    server.route('GET', path + '/aliases', 'integration_aliases_empty')
    server.route('POST', path + '/aliases', 'integration_alias_create')
    result = run_module(integration.main, dict(project='homelab', name='gh'))
    assert result['changed'] is True
    assert len(result['webhook_urls']) == 1


def test_delete(server, project, run_module):
    path = existing(server, project)
    server.route('GET', path + '/refs', 'integration_refs_unused')
    server.route('DELETE', path, 'integration_delete')
    stored = run_module(integration.main, dict(project='homelab', name='gh'))['integration']
    result = run_module(integration.main, dict(project='homelab', name='gh', state='absent'))
    assert result['changed'] is True
    assert [c['path'] for c in server.calls('DELETE')] == [path]
    # The diff shows what is deleted, in the shape an update shows it.
    assert result['diff'] == dict(before=stored, after={})
    assert stored['auth_key'] == 'deploy' and [m['name'] for m in stored['matchers']] == ['main']


def test_integration_info(server, project, run_module):
    path = existing(server, project)
    server.route('GET', project + '/integrations', 'integrations_one')
    result = run_module(integration_info.main, dict(project='homelab'))
    info = result['integrations'][0]
    assert info['auth_method'] == 'token' and info['auth_key'] == 'deploy'
    assert [m['name'] for m in info['matchers']] == ['main']
    assert info['webhook_urls'] == [a['url'] for a in server.fixtures['integration_aliases_one']['body']]
    # Matchers, values and aliases are read once each; the integration itself comes from the list.
    assert [len(server.calls('GET', path + sub)) for sub in ('/matchers', '/values', '/aliases')] == [1, 1, 1]
    assert server.calls('GET', path) == []
