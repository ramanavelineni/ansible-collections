# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""Harbor's 1.5 s login lock: requests during it are handled as anonymous.

The lock starts when another client fails to log in as the same user, so the
client waits LOGIN_LOCK_WAIT seconds and asks again once.
"""

import time

from ansible_collections.ramanavelineni.harbor.plugins.module_utils.harbor import LOGIN_LOCK_WAIT
from ansible_collections.ramanavelineni.harbor.plugins.modules import info, project, project_info

# What Harbor answers an anonymous request to an endpoint that needs a login.
UNAUTHORIZED = dict(status=401, body=dict(errors=[dict(code='UNAUTHORIZED', message='UnAuthorized')]))


def lock_waits():
    return [c for c in time.sleep.call_args_list if c.args == (LOGIN_LOCK_WAIT,)]


def test_login_check_asks_again_after_the_lock(server, run_module):
    server.route('GET', '/systeminfo', 'systeminfo_anonymous', 'systeminfo')
    result = run_module(info.main, {})
    assert result.get('failed') is not True
    assert result['tested'] is True
    assert len(server.calls('GET', '/systeminfo')) == 2
    assert len(lock_waits()) == 1


def test_login_check_fails_when_still_anonymous(server, run_module):
    server.route('GET', '/systeminfo', 'systeminfo_anonymous')
    result = run_module(info.main, {})
    assert result['failed'] is True
    assert 'also when asked again %d seconds later' % LOGIN_LOCK_WAIT in result['msg']
    assert len(server.calls('GET', '/systeminfo')) == 2


def test_no_wait_when_the_login_works(server, run_module):
    run_module(info.main, {})
    assert lock_waits() == []
    assert len(server.calls('GET', '/systeminfo')) == 1


def test_read_retried_once_after_401(server, run_module):
    server.route('GET', '/projects', dict(UNAUTHORIZED), 'projects_before')
    server.route('GET', '/registries', 'registries_empty')
    server.route('GET', '/quotas', 'quotas_all')
    result = run_module(project_info.main, {})
    assert result.get('failed') is not True
    assert len(server.calls('GET', '/projects')) == 2
    assert len(lock_waits()) == 1


def test_create_retried_once_after_401(server, run_module):
    server.route('GET', '/projects', 'projects_before')
    server.route('POST', '/projects', dict(UNAUTHORIZED), 'project_create')
    server.route('GET', '/projects/%d' % server.fixtures['project_get']['body']['project_id'], 'project_get')
    server.route('GET', '/quotas', 'quotas_created')
    name = server.fixtures['project_get']['body']['name']
    result = run_module(project.main, dict(name=name))
    assert result['changed'] is True
    assert len(server.calls('POST', '/projects')) == 2
    assert len(lock_waits()) == 1


def test_second_401_fails(server, run_module):
    server.route('GET', '/projects', dict(UNAUTHORIZED))
    result = run_module(project_info.main, {})
    assert result['failed'] is True
    assert result['request_details']['status'] == 401
    assert len(server.calls('GET', '/projects')) == 2
    assert len(lock_waits()) == 1
