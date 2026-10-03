# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

import json

import pytest

from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.semaphore import SemaphoreError
from ansible_collections.ramanavelineni.semaphoreui.plugins.modules import user, user_info


@pytest.fixture
def users(server):
    server.route('GET', '/user', 'user_me')
    server.route('GET', '/users', 'user_list')
    return server


def created(server, fixture='user_create'):
    return server.fixtures[fixture]['body']


def test_create(users, run_module):
    listing = users.response('user_list')
    new = created(users)
    listing['body'] = [u for u in listing['body'] if u['id'] != new['id']]
    users.route('GET', '/users', listing)
    users.route('POST', '/users', 'user_create')
    result = run_module(user.main, dict(login=new['username'], name='Fixture', email=new['email'],
                                        user_password='pw-unit-1'))
    assert result['changed'] is True and result['password_updated'] is True
    assert result['user']['id'] == new['id']
    body = users.calls('POST', '/users')[0]['body']
    assert body == dict(username=new['username'], name='Fixture', email=new['email'], admin=False, alert=False,
                        external=False, password='pw-unit-1')
    assert 'pw-unit-1' not in json.dumps(result)


def test_create_needs_password(users, run_module):
    result = run_module(user.main, dict(login='nobody', name='N', email='n@example.com'))
    assert result['failed'] is True
    assert 'user_password' in result['msg']


def test_create_external_without_password(users, run_module):
    users.route('POST', '/users', 'user_create_external')
    ext = created(users, 'user_create_external')
    listing = users.response('user_list')
    listing['body'] = [u for u in listing['body'] if u['id'] != ext['id']]
    users.route('GET', '/users', listing)
    result = run_module(user.main, dict(login=ext['username'], name='External', email=ext['email'], external=True))
    assert result['changed'] is True and result['password_updated'] is False
    assert 'password' not in users.calls('POST', '/users')[0]['body']


def test_duplicate_email_fails_early(users, run_module):
    other = created(users)
    result = run_module(user.main, dict(login='somebody-else', name='S', email=other['email'], user_password='p1'))
    assert result['failed'] is True
    assert 'already belongs to user' in result['msg']
    assert users.calls('POST', '/users') == []


def test_always_sends_password(users, run_module):
    uid = created(users)['id']
    users.route('POST', '/users/%d/password' % uid, 'user_password')
    result = run_module(user.main, dict(login=created(users)['username'], user_password='pw-unit-2'))
    assert result['changed'] is True and result['password_updated'] is True
    assert users.calls('POST', '/users/%d/password' % uid)[0]['body'] == dict(password='pw-unit-2')
    assert users.calls('PUT') == []


def test_on_create_leaves_password(users, run_module):
    result = run_module(user.main, dict(login=created(users)['username'], user_password='pw-unit-2',
                                        update_secret='on_create'))
    assert result['changed'] is False
    assert [c for c in users.calls('POST') if not c['path'].startswith('/auth/')] == []


def test_update_sends_whole_user(users, run_module):
    uid = created(users)['id']
    users.route('PUT', '/users/%d' % uid, 'user_update')
    result = run_module(user.main, dict(login=created(users)['username'], name='Fixture Team', alert=True))
    assert result['changed'] is True and result['password_updated'] is False
    body = users.calls('PUT')[0]['body']
    assert body['name'] == 'Fixture Team' and body['alert'] is True
    assert body['username'] == created(users)['username'] and body['email'] == created(users)['email']
    assert 'pro' in body


def test_no_change(users, run_module):
    listing = users.response('user_list_updated')
    users.route('GET', '/users', listing)
    result = run_module(user.main, dict(login=created(users)['username'], name='Fixture Team', alert=True))
    assert result['changed'] is False


def test_external_is_fixed(users, run_module):
    result = run_module(user.main, dict(login=created(users)['username'], external=True))
    assert result['failed'] is True
    assert 'cannot change' in result['msg']


def test_password_for_external_fails(users, run_module):
    result = run_module(user.main, dict(login=created(users, 'user_create_external')['username'],
                                        user_password='pw-unit-3'))
    assert result['failed'] is True
    assert 'external' in result['msg']


def test_login_user_is_protected(users, run_module):
    me = users.fixtures['user_me']['body']['username']
    result = run_module(user.main, dict(login=me, name='Changed'))
    assert result['failed'] is True and 'logs in as' in result['msg']
    result = run_module(user.main, dict(login=me, state='absent'))
    assert result['failed'] is True and 'logs in as' in result['msg']
    result = run_module(user.main, dict(login=me, user_password='pw-unit-4'))
    assert result['changed'] is False
    assert 'logs in as' in json.dumps(result.get('warnings'))
    assert users.calls('PUT') == [] and users.calls('DELETE') == []


def test_delete(users, run_module):
    uid = created(users)['id']
    users.route('DELETE', '/users/%d' % uid, 'user_delete')
    result = run_module(user.main, dict(login=created(users)['username'], state='absent'))
    assert result['changed'] is True


def test_delete_500_explains_2_18(users, run_module):
    uid = created(users)['id']
    users.route('DELETE', '/users/%d' % uid, dict(status=500, body=None))
    result = run_module(user.main, dict(login=created(users)['username'], state='absent'))
    assert result['failed'] is True
    assert 'HTTP 500' in result['msg']
    # Only a server before 2.19 has the session problem; on 2.19 a 500 is reported as it is.
    assert ('before 2.19' in result['msg']) == (users.version == '2.18')


def test_delete_missing(users, run_module):
    result = run_module(user.main, dict(login='does-not-exist', state='absent'))
    assert result['changed'] is False


def test_user_info(users, run_module):
    result = run_module(user_info.main, dict(login=created(users)['username']))
    assert len(result['users']) == 1
    assert set(result['users'][0]) == set(['id', 'username', 'name', 'email', 'admin', 'alert', 'external'])


def test_semaphore_error_passthrough():
    assert SemaphoreError('DELETE', 'u', status=400).status == 400
