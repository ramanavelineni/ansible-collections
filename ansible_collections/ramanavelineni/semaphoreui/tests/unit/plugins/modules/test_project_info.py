# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

import pytest

from ansible_collections.ramanavelineni.semaphoreui.plugins.modules import project_info


def test_lists_all(server, run_module):
    server.route('GET', '/projects', 'projects_one_updated')
    result = run_module(project_info.main, {})
    assert result['changed'] is False
    assert [p['name'] for p in result['projects']] == ['homelab']


def test_filters_by_name(server, run_module):
    server.route('GET', '/projects', 'projects_one_updated')
    assert run_module(project_info.main, dict(name='other'))['projects'] == []
    assert len(run_module(project_info.main, dict(name='homelab'))['projects']) == 1


def test_empty(server, run_module):
    server.route('GET', '/projects', 'projects_empty')
    assert run_module(project_info.main, {})['projects'] == []


# -- by id ----------------------------------------------------------------------
#
# No route for GET /projects is set in these tests: a module that reads the
# list, which Semaphore cuts off at 200 rows, fails them.

def test_by_id_returns_that_project_from_the_recorded_answer(server, run_module):
    pid = server.fixtures['project_get']['body']['id']
    server.route('GET', '/project/%d' % pid, 'project_get')
    result = run_module(project_info.main, dict(id=pid))
    assert result.get('failed') is not True, result.get('msg')
    assert result['changed'] is False
    # The recorded answer leaves out false and zero fields.
    assert result['projects'] == [dict(id=pid, name='homelab', alert=False, alert_chat='', max_parallel_tasks=0, type='')]


def test_by_id_returns_the_fields_semaphore_sends(server, run_module):
    # Hand-written in the shape of the recorded project_get.
    server.route('GET', '/project/7', dict(status=200, body=dict(
        created='2026-10-03T22:36:11.143205Z', id=7, name='site', type='', alert=True, alert_chat='ops',
        max_parallel_tasks=3)))
    result = run_module(project_info.main, dict(id=7), check_mode=True)
    assert result['projects'] == [dict(id=7, name='site', alert=True, alert_chat='ops', max_parallel_tasks=3, type='')]


@pytest.mark.parametrize('answer', ['project_get_deleted', dict(status=403, body=None)], ids=['404', '403'])
def test_by_id_a_missing_project_is_an_empty_list(server, run_module, answer):
    server.route('GET', '/project/7', answer)
    result = run_module(project_info.main, dict(id=7))
    assert result.get('failed') is not True, result.get('msg')
    assert result['projects'] == []


def test_by_id_a_server_error_fails(server, run_module):
    server.route('GET', '/project/7', dict(status=500, body=dict(error='database is locked')))
    result = run_module(project_info.main, dict(id=7))
    assert result['failed'] is True
    assert result['request_details']['status'] == 500


def test_id_and_name_exclude_each_other(server, run_module):
    result = run_module(project_info.main, dict(id=7, name='homelab'))
    assert result['failed'] is True
    assert result['msg'] == 'parameters are mutually exclusive: name|id'
    assert server.requests == []
