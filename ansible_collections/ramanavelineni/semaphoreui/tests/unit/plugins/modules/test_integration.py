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


def removal_routes(server, path, matchers_after, values_after):
    """Route the deletions of the recorded matcher and value, and what the lists show afterwards."""
    mid = server.fixtures['integration_matcher_create']['body']['id']
    vid = server.fixtures['integration_value_create']['body']['id']
    server.route('DELETE', '%s/matchers/%d' % (path, mid), 'integration_matcher_delete')
    # No deletion of a value was recorded; Semaphore answers it like the matcher's (204, no body).
    server.route('DELETE', '%s/values/%d' % (path, vid), 'integration_matcher_delete')
    server.route('GET', path + '/matchers', 'integration_matchers_one', matchers_after)
    server.route('GET', path + '/values', 'integration_values_one', values_after)
    return '%s/matchers/%d' % (path, mid), '%s/values/%d' % (path, vid)


def test_extra_items_deleted(server, project, run_module):
    path = existing(server, project)
    deletions = removal_routes(server, path, 'integration_matchers_empty', 'integration_values_empty')
    result = run_module(integration.main, dict(project='homelab', name='gh', matchers=[], extract_values=[]))
    assert result['changed'] is True
    assert sorted(c['path'] for c in server.calls('DELETE')) == sorted(deletions)
    assert result['integration']['matchers'] == [] and result['integration']['extract_values'] == []
    # Each list is read again after the deletions, to see that they happened.
    assert len(server.calls('GET', path + '/matchers')) == 2 and len(server.calls('GET', path + '/values')) == 2


def test_no_second_read_when_nothing_is_removed(server, project, run_module):
    path = existing(server, project)
    result = run_module(integration.main, GH)
    assert result['changed'] is False
    assert len(server.calls('GET', path + '/matchers')) == 1 and len(server.calls('GET', path + '/values')) == 1


@pytest.mark.parametrize('matchers_after, values_after, named, unnamed', [
    ('integration_matchers_one', 'integration_values_one', ["matcher 'main'", "extracted value 'sha'"], []),
    ('integration_matchers_one', 'integration_values_empty', ["matcher 'main'"], ['extracted value']),
    ('integration_matchers_empty', 'integration_values_one', ["extracted value 'sha'"], ['matcher ']),
], ids=['both-kept', 'matcher-kept', 'value-kept'])
def test_a_removal_the_server_does_not_carry_out_fails(server, project, run_module, matchers_after, values_after, named, unnamed):
    # What Semaphore 2.18.30 and 2.19.12 on SQLite do: 204 to the DELETE (recorded), and the list afterwards
    # still holds the entry (seen on both servers; that second read was not recorded, so the recorded list
    # from before the DELETE stands in for it).
    path = existing(server, project)
    removal_routes(server, path, matchers_after, values_after)
    server.route('PUT', path, 'integration_update')
    result = run_module(integration.main, dict(project='homelab', name='gh', searchable=True, matchers=[], extract_values=[]))
    assert result['failed'] is True
    assert 'did not remove' in result['msg'] and "integration 'gh'" in result['msg']
    for text in named:
        assert text in result['msg']
    for text in unnamed:
        assert text not in result['msg'].split('with success')[0]
    assert 'state: absent' in result['msg'] and 'new webhook URL' in result['msg']
    # The other change of the task was not made.
    assert server.calls('PUT') == [] and server.calls('POST', path + '/matchers') == []


def test_removal_in_check_mode_warns_and_sends_nothing(server, project, run_module, monkeypatch):
    warnings = []
    monkeypatch.setattr(integration.AnsibleModule, 'warn', lambda self, text: warnings.append(text))
    path = existing(server, project)
    result = run_module(integration.main, dict(project='homelab', name='gh', matchers=[], extract_values=[]), check_mode=True)
    assert result['changed'] is True
    assert server.calls('DELETE') == []
    assert len(server.calls('GET', path + '/matchers')) == 1
    told = [w for w in warnings if "can't tell" in w]
    assert len(told) == 1 and "matcher 'main'" in told[0] and "extracted value 'sha'" in told[0]


def test_check_mode_without_a_removal_does_not_warn(server, project, run_module, monkeypatch):
    warnings = []
    monkeypatch.setattr(integration.AnsibleModule, 'warn', lambda self, text: warnings.append(text))
    existing(server, project)
    run_module(integration.main, dict(GH, matchers=[dict(name='main', key='ref', value='other')]), check_mode=True)
    assert [w for w in warnings if "can't tell" in w] == []


def test_removal_comes_before_the_other_changes(server, project, run_module):
    path = existing(server, project)
    deletion = removal_routes(server, path, 'integration_matchers_empty', 'integration_values_one')[0]
    server.route('PUT', path, 'integration_update')
    server.route('POST', path + '/matchers', 'integration_matcher_create')
    result = run_module(integration.main, dict(project='homelab', name='gh', searchable=True,
                                               matchers=[dict(name='event', match_type='header', key='X-GitHub-Event', value='push')]))
    assert result['changed'] is True
    writes = [(c['method'], c['path']) for c in server.requests
              if c['method'] != 'GET' and not c['path'].startswith('/auth/')]
    assert writes == [('DELETE', deletion), ('PUT', path), ('POST', path + '/matchers')]


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
