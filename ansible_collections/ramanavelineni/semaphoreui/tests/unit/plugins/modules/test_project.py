# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

import copy
import json

from ansible_collections.ramanavelineni.semaphoreui.plugins.modules import project
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.semaphore import LIST_CAP
from ansible_collections.ramanavelineni.semaphoreui.tests.unit.plugins.conftest import transport_error


def test_create(server, run_module):
    server.route('GET', '/projects', 'projects_empty')
    server.route('POST', '/projects', 'project_create')
    result = run_module(project.main, dict(name='homelab'))

    assert result['changed'] is True
    assert result['project']['id'] == server.fixtures['project_create']['body']['id']
    assert result['project']['alert'] is False
    assert result['project']['max_parallel_tasks'] == 0
    assert server.calls('POST', '/projects')[0]['body'] == dict(name='homelab', alert=False, max_parallel_tasks=0)
    assert result['diff']['before'] == {}
    # Password login, logged out at the end.
    assert server.requests[0]['path'] == '/auth/login'
    assert server.requests[-1]['path'] == '/auth/logout'


def test_create_sends_alert_chat_only_when_set(server, run_module):
    server.route('GET', '/projects', 'projects_empty')
    server.route('POST', '/projects', 'project_create')
    run_module(project.main, dict(name='homelab', alert=True, alert_chat='ops', max_parallel_tasks=3))
    assert server.calls('POST', '/projects')[0]['body'] == dict(
        name='homelab', alert=True, alert_chat='ops', max_parallel_tasks=3)


def test_create_check_mode_sends_nothing(server, run_module):
    server.route('GET', '/projects', 'projects_empty')
    result = run_module(project.main, dict(name='homelab', max_parallel_tasks=2), check_mode=True)
    assert result['changed'] is True
    assert 'id' not in result['project']
    assert result['project']['max_parallel_tasks'] == 2
    assert server.calls('POST') == [call for call in server.calls('POST') if call['path'].startswith('/auth/')]


def test_no_change_when_matching(server, run_module):
    server.route('GET', '/projects', 'projects_one_updated')
    result = run_module(project.main, dict(name='homelab', alert=True, alert_chat='ops', max_parallel_tasks=3))
    assert result['changed'] is False
    assert server.calls('PUT') == []


def test_unset_options_are_not_managed(server, run_module):
    server.route('GET', '/projects', 'projects_one_updated')
    result = run_module(project.main, dict(name='homelab'))
    assert result['changed'] is False
    assert result['project']['alert_chat'] == 'ops'


def test_update_sends_whole_object(server, run_module):
    server.route('GET', '/projects', 'projects_one')
    server.route('PUT', '/project/%d' % pid(server), 'project_update')
    result = run_module(project.main, dict(name='homelab', alert=True))

    assert result['changed'] is True
    assert result['diff']['before']['alert'] is False
    assert result['diff']['after']['alert'] is True
    # The server's update rewrites every column, so unset ones carry the
    # current value, and the body must carry the project's id.
    assert server.calls('PUT')[0]['body'] == dict(
        id=pid(server), name='homelab', alert=True, alert_chat='', max_parallel_tasks=0)


def test_update_check_mode_sends_nothing(server, run_module):
    server.route('GET', '/projects', 'projects_one')
    result = run_module(project.main, dict(name='homelab', max_parallel_tasks=4), check_mode=True)
    assert result['changed'] is True
    assert result['project']['max_parallel_tasks'] == 4
    assert server.calls('PUT') == []


def test_rejected_update_reports_request_and_response(server, run_module):
    server.route('GET', '/projects', 'projects_one')
    server.route('PUT', '/project/%d' % pid(server), 'project_update_id_mismatch')
    result = run_module(project.main, dict(name='homelab', alert=True))

    assert result['failed'] is True
    assert 'returned HTTP 400' in result['msg']
    assert 'Project ID in body and URL must be the same' in result['msg']
    details = result['request_details']
    assert details['method'] == 'PUT'
    assert json.loads(details['request'])['alert'] is True
    assert 's3cret-pw' not in json.dumps(result)
    assert server.requests[-1]['path'] == '/auth/logout'


def test_delete_requires_confirmation(server, run_module):
    server.route('GET', '/projects', 'projects_one')
    result = run_module(project.main, dict(name='homelab', state='absent'))
    assert result['failed'] is True
    assert 'confirm_delete' in result['msg']
    assert server.calls('DELETE') == []


def test_delete(server, run_module):
    server.route('GET', '/projects', 'projects_one')
    server.route('DELETE', '/project/%d' % pid(server), 'project_delete')
    result = run_module(project.main, dict(name='homelab', state='absent', confirm_delete=True))
    assert result['changed'] is True
    assert result['project'] == {}
    assert len(server.calls('DELETE')) == 1


def test_delete_check_mode_sends_nothing(server, run_module):
    server.route('GET', '/projects', 'projects_one')
    result = run_module(project.main, dict(name='homelab', state='absent', confirm_delete=True), check_mode=True)
    assert result['changed'] is True
    assert server.calls('DELETE') == []


def test_delete_missing_is_no_change(server, run_module):
    server.route('GET', '/projects', 'projects_empty')
    result = run_module(project.main, dict(name='homelab', state='absent', confirm_delete=True))
    assert result['changed'] is False


def test_duplicate_names_fail(server, run_module):
    listing = server.response('projects_one')
    twin = dict(listing['body'][0], id=listing['body'][0]['id'] + 1)
    listing['body'].append(twin)
    server.route('GET', '/projects', listing)
    result = run_module(project.main, dict(name='homelab', alert=True))
    assert result['failed'] is True
    assert 'More than one project is named' in result['msg']
    assert server.calls('PUT') == []


def test_list_at_cap_fails_instead_of_creating(server, run_module):
    listing = server.response('projects_one')
    row = listing['body'][0]
    listing['body'] = [dict(row, id=i, name='p%03d' % i) for i in range(LIST_CAP)]
    server.route('GET', '/projects', listing)
    result = run_module(project.main, dict(name='homelab'))
    assert result['failed'] is True
    assert 'cap' in result['msg']
    assert server.calls('POST', '/projects') == []


def test_api_token_skips_login(server, run_module):
    server.route('GET', '/projects', 'projects_one_updated')
    result = run_module(project.main, dict(name='homelab', username=None, password=None, api_token='tok-123'))
    assert result['changed'] is False
    assert server.calls(path='/auth/login') == []
    assert server.calls(path='/auth/logout') == []
    assert all(r['headers']['Authorization'] == 'Bearer tok-123' for r in server.requests)


def test_bad_password_fails(server, run_module):
    server.route('POST', '/auth/login', 'login_bad_password')
    result = run_module(project.main, dict(name='homelab'))
    assert result['failed'] is True
    assert result['request_details']['status'] == 401
    assert 's3cret-pw' not in json.dumps(result)


def test_reads_are_retried_after_transport_errors(server, run_module):
    server.route('GET', '/projects', transport_error(), 'projects_one_updated')
    result = run_module(project.main, dict(name='homelab', alert=True, alert_chat='ops', max_parallel_tasks=3))
    assert result['changed'] is False
    assert len(server.calls('GET', '/projects')) == 2


def test_creates_are_not_retried(server, run_module):
    server.route('GET', '/projects', 'projects_empty')
    server.route('POST', '/projects', transport_error(), 'project_create')
    result = run_module(project.main, dict(name='homelab'))
    assert result['failed'] is True
    assert 'without an HTTP response' in result['msg']
    assert len(server.calls('POST', '/projects')) == 1


def test_untested_version_warns(server, run_module):
    info = server.response('info')
    info['body']['version'] = 'v2.17.9'
    server.route('GET', '/info', info)
    server.route('GET', '/projects', 'projects_one_updated')
    result = run_module(project.main, dict(name='homelab'))
    assert result['changed'] is False
    assert 'v2.17.9' in json.dumps(result.get('warnings', []))


def test_api_suffix_in_url_is_accepted(server, run_module):
    server.route('GET', '/projects', 'projects_one_updated')
    result = run_module(project.main, dict(name='homelab', url='https://semaphore.example.com/api/'))
    assert result['changed'] is False


def pid(server):
    return copy.deepcopy(server.fixtures['projects_one']['body'][0]['id'])
