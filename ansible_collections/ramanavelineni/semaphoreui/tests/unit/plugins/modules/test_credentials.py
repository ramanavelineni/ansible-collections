# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""Where the credentials come from: the task's options first, then the environment."""

import json

import pytest

from ansible_collections.ramanavelineni.semaphoreui.plugins.modules import project

NONE = dict(api_token=None, username=None, password=None)


@pytest.fixture
def run(server, run_module, monkeypatch):
    """run(env, **options) -> result of a project task with only these credentials."""
    for name in ('SEMAPHORE_API_TOKEN', 'SEMAPHORE_USERNAME', 'SEMAPHORE_PASSWORD'):
        monkeypatch.delenv(name, raising=False)
    server.route('GET', '/projects', 'projects_one_updated')

    def run(env, **options):
        for name, value in env.items():
            monkeypatch.setenv('SEMAPHORE_' + name, value)
        return run_module(project.main, dict(NONE, name='homelab', **options))
    return run


def bearer(server):
    return set(r['headers'].get('Authorization') for r in server.requests)


def login_body(server):
    return server.calls('POST', '/auth/login')[0]['body']


def test_env_token_does_not_clash_with_the_tasks_password(server, run):
    result = run(dict(API_TOKEN='env-tok'), username='admin', password='s3cret-pw')
    assert result['changed'] is False
    assert login_body(server) == dict(auth='admin', password='s3cret-pw')
    assert not any('env-tok' in str(r['headers']) for r in server.requests)


def test_env_password_does_not_clash_with_the_tasks_token(server, run):
    result = run(dict(USERNAME='envuser', PASSWORD='env-pw'), api_token='tok-123')
    assert result['changed'] is False
    assert server.calls(path='/auth/login') == []
    assert bearer(server) == set(['Bearer tok-123'])


def test_token_from_the_environment(server, run):
    result = run(dict(API_TOKEN='env-tok'))
    assert result['changed'] is False
    assert server.calls(path='/auth/login') == []
    assert bearer(server) == set(['Bearer env-tok'])


def test_password_login_from_the_environment(server, run):
    result = run(dict(USERNAME='envuser', PASSWORD='env-pw'))
    assert result['changed'] is False
    assert login_body(server) == dict(auth='envuser', password='env-pw')


def test_environment_token_wins_over_environment_password(server, run):
    result = run(dict(API_TOKEN='env-tok', USERNAME='envuser', PASSWORD='env-pw'))
    assert result['changed'] is False
    assert server.calls(path='/auth/login') == []
    assert bearer(server) == set(['Bearer env-tok'])


def test_username_from_the_task_password_from_the_environment(server, run):
    # The token in the environment is not used: the task chose a password login.
    result = run(dict(PASSWORD='env-pw', API_TOKEN='env-tok'), username='admin')
    assert result['changed'] is False
    assert login_body(server) == dict(auth='admin', password='env-pw')


def test_password_from_the_task_username_from_the_environment(server, run):
    result = run(dict(USERNAME='envuser'), password='s3cret-pw')
    assert result['changed'] is False
    assert login_body(server) == dict(auth='envuser', password='s3cret-pw')


def test_empty_environment_variable_counts_as_unset(server, run):
    result = run(dict(API_TOKEN='', USERNAME='envuser', PASSWORD='env-pw'))
    assert result['changed'] is False
    assert login_body(server) == dict(auth='envuser', password='env-pw')


def test_no_credentials_fails(server, run):
    result = run({})
    assert result['failed'] is True
    assert result['msg'] == 'one of the following is required: api_token, username'
    assert server.requests == []


@pytest.mark.parametrize('env, options', [
    ({}, dict(username='admin')),
    ({}, dict(password='s3cret-pw')),
    (dict(USERNAME='envuser'), {}),
    (dict(PASSWORD='env-pw'), {}),
    # A token in the environment doesn't complete a username the task set.
    (dict(API_TOKEN='env-tok'), dict(username='admin')),
])
def test_half_a_password_login_fails(server, run, env, options):
    result = run(env, **options)
    assert result['failed'] is True
    assert result['msg'] == 'parameters are required together: username, password'
    assert server.requests == []


@pytest.mark.parametrize('options', [
    dict(api_token='tok-123', username='admin', password='s3cret-pw'),
    dict(api_token='tok-123', username='admin'),
    dict(api_token='tok-123', password='s3cret-pw'),
])
def test_token_and_password_in_the_task_still_clash(server, run, options):
    result = run({}, **options)
    assert result['failed'] is True
    assert 'mutually exclusive' in result['msg']
    assert server.requests == []


@pytest.mark.parametrize('env, secret', [
    (dict(API_TOKEN='env-tok'), 'env-tok'),
    (dict(USERNAME='envuser', PASSWORD='env-pw'), 'env-pw'),
])
def test_secrets_from_the_environment_are_masked(server, run, env, secret):
    # The server echoes the secret in its error; the result must not carry it.
    answer = dict(status=400, body=dict(error='rejected %s' % secret))
    server.route('GET', '/projects', answer)
    server.route('POST', '/auth/login', answer)
    result = run(env)
    assert result['failed'] is True
    assert secret not in json.dumps(result)
