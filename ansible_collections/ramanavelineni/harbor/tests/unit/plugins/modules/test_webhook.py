# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

import json

import pytest

from ansible_collections.ramanavelineni.harbor.plugins.modules import webhook, webhook_info

HOOK = dict(project='fixtures-webhook', name='ci-notify', description='recorded',
            event_types=['PUSH_ARTIFACT', 'DELETE_ARTIFACT'], address='http://127.0.0.1:9/hook',
            auth_header='Bearer not-a-real-token')


@pytest.fixture
def project(server):
    server.route('GET', '/projects', 'webhook_projects')
    pid = server.fixtures['webhook_projects']['body'][0]['project_id']
    return '/projects/%d/webhook/policies' % pid


def wid(server):
    return server.fixtures['webhook_get']['body']['id']


def ok(status=200):
    return dict(status=status, body=None, headers={})


def test_create(server, project, run_module):
    server.route('GET', project, 'webhook_list_empty')
    server.route('POST', project, 'webhook_create')
    server.route('GET', '%s/%d' % (project, wid(server)), 'webhook_get')
    result = run_module(webhook.main, HOOK)
    assert result['changed'] is True
    assert result['webhook']['id'] == wid(server)
    assert result['webhook']['auth_header_set'] is True
    body = server.calls('POST', project)[0]['body']
    assert body['enabled'] is True
    assert body['event_types'] == ['DELETE_ARTIFACT', 'PUSH_ARTIFACT']
    assert body['targets'] == [dict(type='http', address='http://127.0.0.1:9/hook',
                                    auth_header='Bearer not-a-real-token', payload_format='Default')]
    assert 'not-a-real-token' not in json.dumps(result)


def test_create_needs_events_and_address(server, project, run_module):
    server.route('GET', project, 'webhook_list_empty')
    result = run_module(webhook.main, dict(project='fixtures-webhook', name='x'))
    assert result['failed'] is True
    assert 'event_types, address' in result['msg']


def test_create_check_mode(server, project, run_module):
    server.route('GET', project, 'webhook_list_empty')
    result = run_module(webhook.main, HOOK, check_mode=True)
    assert result['changed'] is True
    assert server.calls('POST') == []


def test_no_change(server, project, run_module):
    server.route('GET', project, 'webhook_list_one')
    result = run_module(webhook.main, dict(HOOK, skip_cert_verify=False, payload_format='Default', enabled=True))
    assert result['changed'] is False
    assert server.calls('PUT') == []


def test_auth_header_change_is_detected(server, project, run_module):
    server.route('GET', project, 'webhook_list_one')
    server.route('PUT', '%s/%d' % (project, wid(server)), ok())
    result = run_module(webhook.main, dict(HOOK, auth_header='Bearer rotated'))
    assert result['changed'] is True
    assert server.calls('PUT')[0]['body']['targets'][0]['auth_header'] == 'Bearer rotated'
    assert 'rotated' not in json.dumps(result)


def test_update_sends_whole_policy(server, project, run_module):
    server.route('GET', project, 'webhook_list_one')
    server.route('PUT', '%s/%d' % (project, wid(server)), ok())
    result = run_module(webhook.main, dict(project='fixtures-webhook', name='ci-notify', enabled=False))
    assert result['changed'] is True
    assert result['diff']['before']['enabled'] is True and result['diff']['after']['enabled'] is False
    body = server.calls('PUT')[0]['body']
    current = server.fixtures['webhook_get']['body']
    assert body['enabled'] is False
    assert body['description'] == current['description']
    assert body['targets'] == current['targets']
    assert body['event_types'] == sorted(current['event_types'])


def test_update_check_mode(server, project, run_module):
    server.route('GET', project, 'webhook_list_one')
    result = run_module(webhook.main, dict(project='fixtures-webhook', name='ci-notify', event_types=['PUSH_ARTIFACT']),
                        check_mode=True)
    assert result['changed'] is True
    assert result['webhook']['event_types'] == ['PUSH_ARTIFACT']
    assert server.calls('PUT') == []


def test_empty_auth_header_removes_it(server, project, run_module):
    server.route('GET', project, 'webhook_list_one')
    server.route('PUT', '%s/%d' % (project, wid(server)), ok())
    result = run_module(webhook.main, dict(project='fixtures-webhook', name='ci-notify', auth_header=''))
    assert result['changed'] is True
    assert 'auth_header' not in server.calls('PUT')[0]['body']['targets'][0]
    assert result['webhook']['auth_header_set'] is False


def test_switch_to_slack_drops_payload_format(server, project, run_module):
    server.route('GET', project, 'webhook_list_one')
    server.route('PUT', '%s/%d' % (project, wid(server)), ok())
    result = run_module(webhook.main, dict(project='fixtures-webhook', name='ci-notify', notify_type='slack'))
    assert result['changed'] is True
    assert 'payload_format' not in server.calls('PUT')[0]['body']['targets'][0]


def test_slack_payload_format_fails(server, project, run_module):
    server.route('GET', project, 'webhook_list_one')
    result = run_module(webhook.main, dict(project='fixtures-webhook', name='ci-notify', notify_type='slack',
                                           payload_format='CloudEvents'))
    assert result['failed'] is True
    assert 'not allowed for a slack webhook' in result['msg']


def test_several_endpoints_refused(server, project, run_module):
    server.route('GET', project, 'webhook_list_two_targets')
    result = run_module(webhook.main, dict(project='fixtures-webhook', name='ci-notify', address='http://127.0.0.1:9/x'))
    assert result['failed'] is True
    assert 'has 2 endpoints' in result['msg']


def test_several_endpoints_kept_when_targets_untouched(server, project, run_module):
    server.route('GET', project, 'webhook_list_two_targets')
    server.route('PUT', '%s/%d' % (project, wid(server)), ok())
    result = run_module(webhook.main, dict(project='fixtures-webhook', name='ci-notify', enabled=False))
    assert result['changed'] is True
    assert len(server.calls('PUT')[0]['body']['targets']) == 2


def test_server_rejection_reported(server, project, run_module):
    server.route('GET', project, 'webhook_list_empty')
    server.route('POST', project, 'webhook_create_bad_event')
    result = run_module(webhook.main, HOOK)
    assert result['failed'] is True
    assert 'unsupported event type' in result['msg']
    assert 'not-a-real-token' not in json.dumps(result)


def test_delete(server, project, run_module):
    server.route('GET', project, 'webhook_list_one')
    server.route('DELETE', '%s/%d' % (project, wid(server)), 'webhook_delete')
    result = run_module(webhook.main, dict(project='fixtures-webhook', name='ci-notify', state='absent'))
    assert result['changed'] is True
    assert result['webhook'] == {}


def test_delete_missing(server, project, run_module):
    server.route('GET', project, 'webhook_list_empty')
    result = run_module(webhook.main, dict(project='fixtures-webhook', name='ci-notify', state='absent'))
    assert result['changed'] is False


def test_unknown_project(server, run_module):
    server.route('GET', '/projects', dict(status=200, body=[], headers={'x-total-count': '0'}))
    result = run_module(webhook.main, HOOK)
    assert result['failed'] is True
    assert "Project 'fixtures-webhook' does not exist" in result['msg']


def test_webhook_info(server, project, run_module):
    server.route('GET', project, 'webhook_list_two_targets')
    result = run_module(webhook_info.main, dict(project='fixtures-webhook'))
    hook = result['webhooks'][0]
    assert hook['name'] == 'ci-notify' and hook['endpoints'] == 2 and hook['auth_header_set'] is True
    assert 'not-a-real-token' not in json.dumps(result)


def test_webhook_info_by_name(server, project, run_module):
    server.route('GET', project, 'webhook_list_one')
    assert run_module(webhook_info.main, dict(project='fixtures-webhook', name='other'))['webhooks'] == []


def test_failed_update_does_not_report_stored_auth_header(server, project, run_module):
    # The update sends the stored header back; the task never declared it, so
    # Ansible has nothing to mask.
    server.route('GET', project, 'webhook_list_one')
    server.route('PUT', '%s/%d' % (project, wid(server)), dict(status=400, body=dict(errors=[]), headers={}))
    result = run_module(webhook.main, dict(project='fixtures-webhook', name='ci-notify', enabled=False))
    assert result['failed'] is True
    assert server.calls('PUT')[0]['body']['targets'][0]['auth_header'] == 'Bearer not-a-real-token'
    assert 'not-a-real-token' not in json.dumps(result)
    assert result['request_details']['request']['targets'][0]['auth_header'] == '********'
    assert result['request_details']['request']['enabled'] is False


def events(server, project):
    """Where the server lists the events it offers for the project."""
    path = project.rsplit('/', 1)[0] + '/events'
    server.route('GET', path, 'webhook_events')
    return path


def test_known_events_are_not_looked_up(server, project, run_module):
    path = events(server, project)
    server.route('GET', project, 'webhook_list_one')
    result = run_module(webhook.main, HOOK)
    assert result['changed'] is False
    assert server.calls('GET', path) == []


def test_event_the_server_offers_is_accepted(server, project, run_module):
    # Hand-made: the recorded list with one event added, as a newer Harbor would answer.
    offered = server.response('webhook_events')
    offered['body']['event_type'].append('NEW_EVENT')
    path = project.rsplit('/', 1)[0] + '/events'
    server.route('GET', path, offered)
    server.route('GET', project, 'webhook_list_empty')
    server.route('POST', project, 'webhook_create')
    server.route('GET', '%s/%d' % (project, wid(server)), 'webhook_get')
    result = run_module(webhook.main, dict(HOOK, event_types=['PUSH_ARTIFACT', 'NEW_EVENT']))
    assert result['changed'] is True
    assert server.calls('POST', project)[0]['body']['event_types'] == ['NEW_EVENT', 'PUSH_ARTIFACT']
    assert len(server.calls('GET', path)) == 1


def test_event_the_server_does_not_offer_fails(server, project, run_module):
    events(server, project)
    server.route('GET', project, 'webhook_list_empty')
    result = run_module(webhook.main, dict(HOOK, event_types=['PUSH_ARTIFACT', 'NOPE']))
    assert result['failed'] is True
    assert result['msg'].startswith('Unknown event types NOPE; this server offers DELETE_ARTIFACT, PULL_ARTIFACT,')
    assert server.calls('POST') == []


def test_event_the_server_does_not_offer_warns_in_check_mode(server, project, run_module):
    events(server, project)
    server.route('GET', project, 'webhook_list_empty')
    result = run_module(webhook.main, dict(HOOK, event_types=['NOPE']), check_mode=True)
    assert result['changed'] is True
    assert 'Unknown event types NOPE; this server offers' in json.dumps(result.get('warnings', [])), result
    assert server.calls('POST') == []


@pytest.mark.parametrize('answer', [
    # Hand-made: a server that has no such list, and one that answers in another form.
    dict(status=404, body=dict(errors=[dict(code='NOT_FOUND', message='not found')]), headers={}),
    dict(status=200, body=['PUSH_ARTIFACT'], headers={}),
])
def test_unreadable_event_list_leaves_it_to_harbor(server, project, run_module, answer):
    server.route('GET', project.rsplit('/', 1)[0] + '/events', answer)
    server.route('GET', project, 'webhook_list_empty')
    server.route('POST', project, 'webhook_create_bad_event')
    result = run_module(webhook.main, dict(HOOK, event_types=['NOPE']))
    assert result['failed'] is True
    assert 'unsupported event type NOPE' in result['msg']
    assert server.calls('POST', project)[0]['body']['event_types'] == ['NOPE']


def test_delete_does_not_check_events(server, project, run_module):
    server.route('GET', project, 'webhook_list_empty')
    result = run_module(webhook.main, dict(HOOK, event_types=['NOPE'], state='absent'))
    assert result['changed'] is False
