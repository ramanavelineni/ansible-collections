# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

import json
from urllib.error import URLError

import pytest

from ansible_collections.ramanavelineni.semaphoreui.plugins.modules import runner, runner_info


def rid(server):
    return server.fixtures['runner_create']['body']['id']


@pytest.fixture
def listed(server):
    server.route('GET', '/runners', 'runner_list_one')
    return '/runners/%d' % rid(server)


def test_create_returns_registration_token(server, run_module):
    empty = server.response('runner_list_one')
    empty['body'] = []
    server.route('GET', '/runners', empty)
    server.route('POST', '/runners', 'runner_create')
    server.route('POST', '/runners/%d/registration-token' % rid(server), 'runner_registration_token')
    result = run_module(runner.main, dict(name='rn-fixture', max_parallel_tasks=2, tags=['b', 'a']))
    assert result['changed'] is True
    assert result['registration_token'] == server.fixtures['runner_registration_token']['body']['registration_token']
    assert result['runner']['tags'] == ['a', 'b']
    assert server.calls('POST', '/runners')[0]['body'] == dict(
        name='rn-fixture', max_parallel_tasks=2, active=True, tags=['a', 'b'], webhook='', is_default=False)


def test_create_check_mode(server, run_module):
    empty = server.response('runner_list_one')
    empty['body'] = []
    server.route('GET', '/runners', empty)
    result = run_module(runner.main, dict(name='rn-fixture'), check_mode=True)
    assert result['changed'] is True
    assert result['registration_token'] == ''
    assert server.calls('POST', '/runners') == []


def test_no_change(server, listed, run_module):
    result = run_module(runner.main, dict(name='rn-fixture', max_parallel_tasks=2, tags=['a', 'b'], active=True))
    assert result['changed'] is False
    assert result['registration_token'] == ''
    assert server.calls('PUT') == []


def test_update_sends_whole_runner(server, listed, run_module):
    server.route('PUT', listed, 'runner_update')
    result = run_module(runner.main, dict(name='rn-fixture', webhook='https://hooks.example.com/r'))
    assert result['changed'] is True
    # Semaphore's update replaces every field, so unmanaged ones go back as they are.
    assert server.calls('PUT')[0]['body'] == dict(
        name='rn-fixture', max_parallel_tasks=2, active=True, tags=['a', 'b'],
        webhook='https://hooks.example.com/r', is_default=False)


def test_update_check_mode(server, listed, run_module):
    result = run_module(runner.main, dict(name='rn-fixture', active=False), check_mode=True)
    assert result['changed'] is True
    assert result['runner']['active'] is False
    assert server.calls('PUT') == []


def test_regenerate_token(server, listed, run_module):
    server.route('POST', listed + '/registration-token', 'runner_registration_token')
    result = run_module(runner.main, dict(name='rn-fixture', regenerate_token=True))
    assert result['changed'] is True
    assert result['registration_token'].startswith('smrs_')
    assert server.calls('PUT') == []


def test_regenerate_on_registered_runner_warns(server, run_module):
    listing = server.response('runner_list_one')
    listing['body'][0]['registered'] = True
    server.route('GET', '/runners', listing)
    server.route('POST', '/runners/%d/registration-token' % rid(server), 'runner_registration_token')
    result = run_module(runner.main, dict(name='rn-fixture', regenerate_token=True))
    assert result['changed'] is True
    assert 'register again' in json.dumps(result['warnings'])
    assert result['runner']['registered'] is False


def test_regenerate_check_mode(server, listed, run_module):
    result = run_module(runner.main, dict(name='rn-fixture', regenerate_token=True), check_mode=True)
    assert result['changed'] is True
    assert result['registration_token'] == ''
    assert server.calls('POST', listed + '/registration-token') == []


def registered_listing(server):
    listing = server.response('runner_list_one')
    listing['body'][0]['registered'] = True
    return listing


def test_regenerate_check_mode_predicts_the_real_run(server, run_module):
    token_path = '/runners/%d/registration-token' % rid(server)
    server.route('GET', '/runners', registered_listing(server))
    server.route('POST', token_path, 'runner_registration_token')
    real = run_module(runner.main, dict(name='rn-fixture', regenerate_token=True))
    predicted = run_module(runner.main, dict(name='rn-fixture', regenerate_token=True), check_mode=True)
    assert len(server.calls('POST', token_path)) == 1
    assert predicted['runner']['registered'] is False
    assert predicted['diff']['before']['registered'] is True
    assert predicted['runner'] == real['runner']
    assert predicted['diff'] == real['diff']
    assert 'register again' in json.dumps(predicted['warnings'])


# -- the token request, when it fails ------------------------------------------
# Hand-written answers: no failing token request was recorded.

def new_runner(server):
    empty = server.response('runner_list_one')
    empty['body'] = []
    server.route('GET', '/runners', empty)
    server.route('POST', '/runners', 'runner_create')
    return '/runners/%d' % rid(server)


def test_token_request_is_retried_after_create(server, run_module):
    path = new_runner(server)
    server.route('POST', path + '/registration-token', dict(status=502, body=None), URLError('connection reset'),
                 'runner_registration_token')
    result = run_module(runner.main, dict(name='rn-fixture', retries=2))
    assert result['changed'] is True
    assert result['registration_token'].startswith('smrs_')
    assert len(server.calls('POST', path + '/registration-token')) == 3
    assert len(server.calls('POST', '/runners')) == 1
    assert server.calls('DELETE') == []


def test_token_request_is_retried_on_regenerate(server, listed, run_module):
    server.route('POST', listed + '/registration-token', dict(status=503, body=None), 'runner_registration_token')
    result = run_module(runner.main, dict(name='rn-fixture', regenerate_token=True))
    assert result['changed'] is True
    assert result['registration_token'].startswith('smrs_')
    assert len(server.calls('POST', listed + '/registration-token')) == 2


def test_token_request_is_not_retried_on_a_refusal(server, run_module):
    path = new_runner(server)
    server.route('POST', path + '/registration-token', dict(status=400, body=dict(error='no')))
    server.route('DELETE', path, 'runner_delete')
    result = run_module(runner.main, dict(name='rn-fixture'))
    assert result['failed'] is True
    assert len(server.calls('POST', path + '/registration-token')) == 1


def test_new_runner_without_token_is_deleted_again(server, run_module):
    path = new_runner(server)
    server.route('POST', path + '/registration-token', dict(status=502, body=None))
    server.route('DELETE', path, 'runner_delete')
    result = run_module(runner.main, dict(name='rn-fixture', retries=1))
    assert result['failed'] is True
    assert 'registration token could not be fetched' in result['msg']
    assert 'HTTP 502' in result['msg']
    assert 'deleted again' in result['msg']
    assert 'regenerate_token' not in result['msg']
    assert len(server.calls('POST', path + '/registration-token')) == 2
    assert [c['path'] for c in server.calls('DELETE')] == [path]
    assert result['request_details']['url'].endswith(path + '/registration-token')


def test_new_runner_without_token_that_cannot_be_deleted(server, run_module):
    path = new_runner(server)
    server.route('POST', path + '/registration-token', dict(status=502, body=None))
    server.route('DELETE', path, dict(status=502, body=None))
    result = run_module(runner.main, dict(name='rn-fixture', retries=0))
    assert result['failed'] is True
    assert 'Deleting the runner again failed too' in result['msg']
    assert 'regenerate_token: true' in result['msg']
    assert len(server.calls('DELETE')) == 1


def test_failed_regenerate_keeps_the_runner(server, listed, run_module):
    server.route('POST', listed + '/registration-token', dict(status=502, body=None))
    result = run_module(runner.main, dict(name='rn-fixture', regenerate_token=True, retries=1))
    assert result['failed'] is True
    assert 'HTTP 502' in result['msg']
    assert len(server.calls('POST', listed + '/registration-token')) == 2
    assert server.calls('DELETE') == []


def test_global_lookup_ignores_project_runners(server, run_module):
    listing = server.response('runner_list_one')
    listing['body'][0]['project_id'] = 7
    server.route('GET', '/runners', listing)
    server.route('POST', '/runners', 'runner_create')
    server.route('POST', '/runners/%d/registration-token' % rid(server), 'runner_registration_token')
    result = run_module(runner.main, dict(name='rn-fixture'))
    assert result['changed'] is True
    assert len(server.calls('POST', '/runners')) == 1


def test_duplicate_names_fail(server, run_module):
    listing = server.response('runner_list_one')
    listing['body'].append(dict(listing['body'][0], id=rid(server) + 1))
    server.route('GET', '/runners', listing)
    result = run_module(runner.main, dict(name='rn-fixture', active=False))
    assert result['failed'] is True
    assert 'More than one runner is named' in result['msg']


def test_delete(server, listed, run_module):
    server.route('DELETE', listed, 'runner_delete')
    result = run_module(runner.main, dict(name='rn-fixture', state='absent'))
    assert result['changed'] is True
    assert len(server.calls('DELETE')) == 1


def test_delete_missing(server, run_module):
    empty = server.response('runner_list_one')
    empty['body'] = []
    server.route('GET', '/runners', empty)
    result = run_module(runner.main, dict(name='rn-fixture', state='absent'))
    assert result['changed'] is False


# Project runners need Semaphore Pro. The success paths below reuse the global
# runner recordings under the project routes (Pro mirrors the global
# endpoints); a Community server can only show the refusal.

@pytest.fixture
def project(server):
    server.route('GET', '/projects', 'projects_one')
    return '/project/%d' % server.fixtures['projects_one']['body'][0]['id']


def test_project_runner_create(server, project, run_module):
    empty = server.response('runner_list_one')
    empty['body'] = []
    created = server.response('runner_create')
    created['body']['project_id'] = int(project.split('/')[-1])
    server.route('GET', project + '/runners', empty)
    server.route('POST', project + '/runners', created)
    server.route('POST', '%s/runners/%d/registration-token' % (project, rid(server)), 'runner_registration_token')
    result = run_module(runner.main, dict(name='rn-fixture', project='homelab'))
    assert result['changed'] is True
    assert result['runner']['project'] == 'homelab'
    assert result['registration_token'].startswith('smrs_')
    assert server.calls('POST', project + '/runners')[0]['body']['project_id'] == int(project.split('/')[-1])


def test_project_runner_update(server, project, run_module):
    listing = server.response('runner_list_one')
    listing['body'][0]['project_id'] = int(project.split('/')[-1])
    server.route('GET', project + '/runners', listing)
    server.route('PUT', '%s/runners/%d' % (project, rid(server)), 'runner_update')
    result = run_module(runner.main, dict(name='rn-fixture', project='homelab', max_parallel_tasks=5))
    assert result['changed'] is True
    body = server.calls('PUT')[0]['body']
    assert body['max_parallel_tasks'] == 5 and body['project_id'] == int(project.split('/')[-1])


def test_project_runner_refused_on_community(server, project, run_module):
    server.route('GET', project + '/runners', 'runner_project_list_community')
    server.route('POST', project + '/runners', 'runner_project_create_community')
    result = run_module(runner.main, dict(name='rn-fixture', project='homelab'))
    assert result['failed'] is True
    assert 'plan does not allow' in result['msg']


def test_runner_info(server, run_module):
    listing = server.response('runner_list_one_updated')
    listing['body'].append(dict(listing['body'][0], id=rid(server) + 1, name='project-one', project_id=3))
    server.route('GET', '/runners', listing)
    result = run_module(runner_info.main, {})
    assert [r['name'] for r in result['runners']] == ['rn-fixture']
    assert result['runners'][0]['webhook'] == 'https://hooks.example.com/r'
    assert 'token' not in result['runners'][0]


def test_runner_info_project(server, project, run_module):
    server.route('GET', project + '/runners', 'runner_project_list_community')
    result = run_module(runner_info.main, dict(project='homelab'))
    assert result['runners'] == []
