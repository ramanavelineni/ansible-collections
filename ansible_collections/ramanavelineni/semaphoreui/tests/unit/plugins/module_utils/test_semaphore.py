# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

import json

import pytest

from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.semaphore import (
    SemaphoreError,
    base_url,
    diff_fields,
    find_by_name,
    redact,
    scrub,
    semaphore_module_kwargs,
    server_minor,
    version_is_tested,
)


@pytest.mark.parametrize('url, expected', [
    ('https://semaphore.example.com', 'https://semaphore.example.com'),
    ('https://semaphore.example.com/', 'https://semaphore.example.com'),
    ('https://semaphore.example.com/api', 'https://semaphore.example.com'),
    ('https://semaphore.example.com/api/', 'https://semaphore.example.com'),
    ('https://example.com/semaphore/api', 'https://example.com/semaphore'),
    ('https://example.com/apis', 'https://example.com/apis'),
])
def test_base_url(url, expected):
    assert base_url(url) == expected


@pytest.mark.parametrize('version, expected', [
    ('v2.19.12', True),
    ('2.18.30', True),
    ('v2.19', True),
    ('v2.17.3', False),
    ('v2.20.0', False),
    ('v2.180.1', False),
    ('', False),
    (None, False),
    ('develop', False),
])
def test_version_is_tested(version, expected):
    assert version_is_tested(version) is expected


def test_find_by_name_single_match():
    items = [{'id': 1, 'name': 'a'}, {'id': 2, 'name': 'b'}]
    assert find_by_name(items, 'b', 'project') == {'id': 2, 'name': 'b'}


def test_find_by_name_no_match():
    assert find_by_name([{'id': 1, 'name': 'a'}], 'z', 'project') is None


def test_find_by_name_duplicate_names_fail():
    items = [{'id': 1, 'name': 'a'}, {'id': 7, 'name': 'a'}]
    with pytest.raises(ValueError, match=r"More than one project is named 'a' \(ids 1, 7\)"):
        find_by_name(items, 'a', 'project')


def test_find_by_name_other_field():
    assert find_by_name([{'id': 3, 'title': 'All'}], 'All', 'view', field='title')['id'] == 3


def test_diff_fields_ignores_unmanaged_and_equal():
    desired = {'alert': True, 'alert_chat': None, 'max_parallel_tasks': 0}
    current = {'alert': False, 'alert_chat': 'x', 'max_parallel_tasks': 0}
    assert diff_fields(desired, current) == ['alert']


def test_semaphore_error_messages():
    empty = SemaphoreError('PUT', 'https://s/api/project/1', status=400, response='')
    assert 'HTTP 400: (empty body)' in empty.message()
    transport = SemaphoreError('GET', 'https://s/api/info', reason='connection reset')
    assert 'failed without an HTTP response: connection reset' in transport.message()
    assert transport.details()['status'] is None


def test_redact_masks_secret_keys_and_no_log_values():
    body = dict(name='deploy', type='ssh', ssh=dict(login='git', passphrase='', private_key='-----BEGIN\nKEY'),
                secrets=[dict(name='API', secret='tok"en', type='env')], override_secret=True, note='declared-value')
    assert redact(body, secrets={'declared-value'}) == dict(
        name='deploy', type='ssh', ssh=dict(login='git', passphrase='', private_key='********'),
        secrets=[dict(name='API', secret='********', type='env')], override_secret=True, note='********')
    assert body['ssh']['private_key'] == '-----BEGIN\nKEY'
    assert redact(None) is None


def test_scrub_takes_secrets_out_of_a_server_answer():
    # As written, and as JSON writes a value with a quote and a backslash.
    secret = 'to"k\\en'
    answer = json.dumps(dict(error='rejected %s' % secret, hint='plain pw-123 here'))
    shown = scrub(answer, (secret, 'pw-123', None, ''))
    assert shown == '{"error": "rejected ********", "hint": "plain ******** here"}'
    assert scrub('token %s refused' % secret, (secret,)) == 'token ******** refused'
    # The longer secret goes first, so one that contains another is not left half shown.
    assert scrub('abcdef abc', ('abc', 'abcdef')) == '******** ********'
    assert scrub('nothing to hide', ()) == 'nothing to hide'


def test_server_minor():
    assert server_minor('v2.19.12-012ed06-1788086368') == (2, 19)
    assert server_minor('2.9.0') == (2, 9)
    assert server_minor('') is None and server_minor(None) is None


SHARED_EXCLUSIVE = [('api_token', 'username'), ('api_token', 'password')]


def test_module_kwargs_alone():
    assert semaphore_module_kwargs() == dict(mutually_exclusive=SHARED_EXCLUSIVE)


def test_module_kwargs_add_to_the_shared_ones():
    kwargs = semaphore_module_kwargs(mutually_exclusive=[('cron', 'run_at')],
                                     required_if=[('state', 'present', ('role',))])
    assert kwargs == dict(mutually_exclusive=SHARED_EXCLUSIVE + [('cron', 'run_at')],
                          required_if=[('state', 'present', ('role',))])


def test_module_kwargs_do_not_leak_between_calls():
    semaphore_module_kwargs(mutually_exclusive=[('cron', 'run_at')])
    assert semaphore_module_kwargs() == dict(mutually_exclusive=SHARED_EXCLUSIVE)


@pytest.mark.parametrize('name', ['required_together', 'required_one_of'])
def test_module_kwargs_take_the_other_constraints(name):
    assert semaphore_module_kwargs(**{name: [('a', 'b')]})[name] == [('a', 'b')]


def test_module_kwargs_refuse_anything_else():
    with pytest.raises(TypeError):
        semaphore_module_kwargs(supports_check_mode=False)
