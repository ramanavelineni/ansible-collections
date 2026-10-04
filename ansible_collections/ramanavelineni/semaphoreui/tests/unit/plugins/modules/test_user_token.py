# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

import json

import pytest
import yaml

from ansible_collections.ramanavelineni.semaphoreui.plugins.modules import user_token

NAME = 'tk-fixture'
# What the recorder wrote in place of the token and of its listed start.
VALUE = 'tkfix001-recorded-not-a-real-api-token-000000='
START = 'tkfix001'
STANDARD_KEYS = set(['changed', 'diff', 'invocation', 'warnings', 'deprecations'])


def creates(server):
    return server.calls('POST', '/user/tokens')


def deletes(server):
    return [r for r in server.requests if r['method'] == 'DELETE']


def test_the_recording_has_the_stand_in_and_only_the_start_in_lists(server):
    assert server.fixtures['token_create']['body']['id'] == VALUE
    assert [t['id'] for t in server.fixtures['tokens_two']['body']] == [START, 'tkfix002']
    assert all('name' in t for t in server.fixtures['tokens_two']['body'])


def test_creates_the_token_and_returns_it_once(server, run_module):
    server.route('GET', '/user/tokens', 'tokens_none')
    server.route('POST', '/user/tokens', 'token_create')
    result = run_module(user_token.main, dict(name=NAME))
    assert result['changed'] is True
    assert result['token'] == VALUE
    created = server.fixtures['token_create']['body']
    assert result['user_token'] == dict(id=START, name=NAME, created=created['created'], expires_at=None, expired=False)
    assert result['diff'] == dict(before={}, after=result['user_token'])
    assert creates(server)[0]['body'] == dict(name=NAME)
    # The token is in the result once: as the value, nowhere in what describes it.
    assert json.dumps(result).count(VALUE) == 1


def test_an_existing_token_is_left_alone_and_not_returned(server, run_module):
    server.route('GET', '/user/tokens', 'tokens_two')
    for check_mode in (False, True):
        result = run_module(user_token.main, dict(name=NAME), check_mode=check_mode)
        assert result['changed'] is False
        assert result['token'] == ''
        assert result['user_token']['id'] == START and result['user_token']['expired'] is False
    assert creates(server) == [] and deletes(server) == []


def test_check_mode_creates_nothing(server, run_module):
    server.route('GET', '/user/tokens', 'tokens_none')
    result = run_module(user_token.main, dict(name=NAME), check_mode=True)
    assert result['changed'] is True and result['token'] == ''
    assert result['user_token'] == dict(name=NAME, expires_at=None, expired=False)
    assert creates(server) == []


def test_expiry_is_sent_in_utc(server, run_module):
    server.route('GET', '/user/tokens', 'tokens_one')
    server.route('POST', '/user/tokens', 'token_create_expiring')
    result = run_module(user_token.main, dict(name='tk-fixture-expiring', expires_at='2099-01-01T02:00:00+02:00'))
    assert result['changed'] is True
    assert creates(server)[0]['body'] == dict(name='tk-fixture-expiring', expires_at='2099-01-01T00:00:00Z')
    assert result['user_token']['expires_at'] == '2099-01-01T00:00:00Z'


def test_the_same_expiry_written_another_way_is_no_change(server, run_module):
    server.route('GET', '/user/tokens', 'tokens_two')
    for written in ('2099-01-01T00:00:00Z', '2099-01-01 01:00:00+01:00', None):
        result = run_module(user_token.main, dict(name='tk-fixture-expiring', expires_at=written))
        assert result['changed'] is False, written
    assert creates(server) == []


@pytest.mark.parametrize('name, asked, said', [
    (NAME, '2099-01-01T00:00:00Z', 'exists and does not expire; the task asks for 2099-01-01T00:00:00Z'),
    ('tk-fixture-expiring', '2098-01-01T00:00:00Z', 'exists and expires at 2099-01-01T00:00:00Z; the task asks for'),
])
def test_another_expiry_than_the_stored_one_fails(server, run_module, name, asked, said):
    server.route('GET', '/user/tokens', 'tokens_two')
    result = run_module(user_token.main, dict(name=name, expires_at=asked))
    assert result['failed'] is True and said in result['msg'] and 'cannot change the expiry' in result['msg']
    assert creates(server) == [] and deletes(server) == []


@pytest.mark.parametrize('expires_at, said', [
    ('2099-01-01T00:00:00', 'is not a date and time with a time zone'),
    ('tomorrow', 'is not a date and time with a time zone'),
    ('2001-01-01T00:00:00Z', 'is in the past'),
])
def test_an_expiry_semaphore_would_refuse_fails_before_any_request(server, run_module, expires_at, said):
    result = run_module(user_token.main, dict(name=NAME, expires_at=expires_at))
    assert result['failed'] is True and said in result['msg']
    assert server.calls('GET', '/user/tokens') == [] and creates(server) == []


def test_the_recorded_refusal_of_a_past_expiry_has_no_message(server):
    # Why the module checks it itself: Semaphore's answer says nothing.
    assert server.fixtures['token_create_past'] == dict(status=400, body=None)


def test_revokes_by_the_start_of_the_token(server, run_module):
    server.route('GET', '/user/tokens', 'tokens_two')
    server.route('DELETE', '/user/tokens/' + START, 'token_delete')
    result = run_module(user_token.main, dict(name=NAME, state='absent'))
    assert result['changed'] is True
    assert result['user_token'] == {} and result['token'] == ''
    assert result['diff']['before']['id'] == START and result['diff']['after'] == {}
    assert [r['path'] for r in deletes(server)] == ['/user/tokens/' + START]


def test_revoke_in_check_mode_and_when_gone(server, run_module):
    server.route('GET', '/user/tokens', 'tokens_two')
    assert run_module(user_token.main, dict(name=NAME, state='absent'), check_mode=True)['changed'] is True
    server.route('GET', '/user/tokens', 'tokens_after_delete')
    for check_mode in (False, True):
        result = run_module(user_token.main, dict(name=NAME, state='absent'), check_mode=check_mode)
        assert result['changed'] is False and result['user_token'] == {}
    assert deletes(server) == []


def two_of_a_name(server):
    listing = server.response('tokens_two')
    listing['body'][1]['name'] = NAME
    server.route('GET', '/user/tokens', listing)


def test_two_valid_tokens_of_a_name_fail_for_present(server, run_module):
    two_of_a_name(server)
    result = run_module(user_token.main, dict(name=NAME))
    assert result['failed'] is True and "More than one API token is named 'tk-fixture'" in result['msg']
    assert creates(server) == []


def test_absent_revokes_every_token_of_the_name(server, run_module):
    two_of_a_name(server)
    server.route('DELETE', '/user/tokens/' + START, 'token_delete')
    server.route('DELETE', '/user/tokens/tkfix002', 'token_delete')
    assert run_module(user_token.main, dict(name=NAME, state='absent'))['changed'] is True
    assert sorted(r['path'] for r in deletes(server)) == ['/user/tokens/tkfix001', '/user/tokens/tkfix002']


# Hand-edited: no token that stopped working was recorded.
@pytest.mark.parametrize('stopped', [dict(expired=True), dict(expires_at='2001-01-01T00:00:00Z')], ids=['revoked', 'time-passed'])
def test_a_token_that_stopped_working_is_replaced(server, run_module, stopped):
    listing = server.response('tokens_one')
    listing['body'][0].update(stopped)
    server.route('GET', '/user/tokens', listing)
    server.route('DELETE', '/user/tokens/' + START, 'token_delete')
    server.route('POST', '/user/tokens', 'token_create')
    result = run_module(user_token.main, dict(name=NAME))
    assert result['changed'] is True and result['token'] == VALUE
    assert result['diff']['before']['expired'] is True and result['diff']['after']['expired'] is False
    assert [r['path'] for r in deletes(server)] == ['/user/tokens/' + START]
    # Check mode says the same and sends neither request.
    del server.requests[:]
    checked = run_module(user_token.main, dict(name=NAME), check_mode=True)
    assert checked['changed'] is True and checked['token'] == ''
    assert deletes(server) == [] and creates(server) == []


def test_the_token_the_task_connects_with_is_not_revoked(server, run_module):
    server.route('GET', '/user/tokens', 'tokens_two')
    own = dict(api_token=VALUE, username=None, password=None)
    for check_mode in (False, True):
        result = run_module(user_token.main, dict(own, name=NAME, state='absent'), check_mode=check_mode)
        assert result['failed'] is True and 'is the one this task connects with' in result['msg']
    assert deletes(server) == []
    # Another token of the account goes, also when connected with a token.
    server.route('DELETE', '/user/tokens/tkfix002', 'token_delete')
    assert run_module(user_token.main, dict(own, name='tk-fixture-expiring', state='absent'))['changed'] is True


def test_a_server_without_token_names_is_refused(server, run_module):
    # Hand-edited: both recorded versions store names.
    listing = server.response('tokens_one')
    del listing['body'][0]['name']
    server.route('GET', '/user/tokens', listing)
    for state in ('present', 'absent'):
        result = run_module(user_token.main, dict(name=NAME, state=state))
        assert result['failed'] is True and 'stores no names for API tokens' in result['msg']
    assert creates(server) == [] and deletes(server) == []


def test_an_empty_name_is_refused(server, run_module):
    # The account's unnamed tokens (made in the UI without a name) would all match it.
    result = run_module(user_token.main, dict(name=' ', state='absent'))
    assert result['failed'] is True and 'name must not be empty' in result['msg']
    assert server.calls('GET', '/user/tokens') == []


def test_an_answer_without_a_token_fails(server, run_module):
    # Hand-written: no server was seen to answer this.
    server.route('GET', '/user/tokens', 'tokens_none')
    server.route('POST', '/user/tokens', dict(status=201, body=dict(name=NAME)))
    result = run_module(user_token.main, dict(name=NAME))
    assert result['failed'] is True and 'without a token' in result['msg']


def test_a_failed_request_shows_no_token(server, run_module):
    # Hand-written failure of the creation; the stored tokens' starts are all a failure could show.
    server.route('GET', '/user/tokens', 'tokens_none')
    server.route('POST', '/user/tokens', dict(status=500, body=None))
    result = run_module(user_token.main, dict(name=NAME))
    assert result['failed'] is True and result['request_details']['request'] == dict(name=NAME)
    assert VALUE not in json.dumps(result)


@pytest.mark.parametrize('check_mode', [False, True], ids=['real', 'check'])
@pytest.mark.parametrize('state', ['present', 'absent'])
def test_result_has_the_documented_keys(server, run_module, state, check_mode):
    server.route('GET', '/user/tokens', 'tokens_none' if state == 'present' else 'tokens_one')
    server.route('POST', '/user/tokens', 'token_create')
    server.route('DELETE', '/user/tokens/' + START, 'token_delete')
    result = run_module(user_token.main, dict(name=NAME, state=state), check_mode=check_mode)
    assert result['changed'] is True
    assert set(result) - STANDARD_KEYS == set(yaml.safe_load(user_token.RETURN))
    if state == 'present' and not check_mode:
        documented = set(yaml.safe_load(user_token.RETURN)['user_token']['contains'])
        assert set(result['user_token']) == documented
