# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

import pytest

from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.semaphore import normalize_time
from ansible_collections.ramanavelineni.semaphoreui.plugins.modules import schedule, schedule_info


@pytest.fixture
def project(server):
    server.route('GET', '/projects', 'projects_one')
    base = '/project/%d' % server.fixtures['projects_one']['body'][0]['id']
    tid = server.fixtures['template_create']['body']['id']
    server.route('GET', base + '/templates', 'templates_one')
    server.route('GET', base + '/repositories', 'repositories_one')
    server.route('GET', base + '/schedules', 'schedules_project_list')
    server.route('GET', '%s/templates/%d/schedules' % (base, tid), 'schedules_template_pollers')
    return base


def sid(server, fixture='schedule_create'):
    return server.fixtures[fixture]['body']['id']


def single(server, fixture):
    answer = server.response(fixture)
    answer['status'] = 200
    return answer


def test_create_cron(server, project, run_module):
    server.route('GET', project + '/schedules', 'schedules_empty')
    server.route('GET', '%s/templates/%d/schedules' % (project, server.fixtures['template_create']['body']['id']),
                 'schedules_empty')
    server.route('POST', project + '/schedules', 'schedule_create')
    result = run_module(schedule.main, dict(project='homelab', name='nightly', template='site', cron='0 3 * * *'))
    assert result['changed'] is True
    assert result['schedule']['kind'] == 'cron'
    body = server.calls('POST', project + '/schedules')[0]['body']
    assert body['cron_format'] == '0 3 * * *' and body['active'] is True and body['type'] == ''


def test_create_needs_template_and_timing(server, project, run_module):
    result = run_module(schedule.main, dict(project='homelab', name='new'))
    assert result['failed'] is True
    assert 'template, cron or run_at' in result['msg']


def test_no_change(server, project, run_module):
    result = run_module(schedule.main, dict(project='homelab', name='nightly', template='site', cron='0 3 * * *'))
    assert result['changed'] is False


def test_poller_found_through_template_list(server, project, run_module):
    result = run_module(schedule.main, dict(project='homelab', name='on-push', repository='ansible', cron='*/5 * * * *'))
    assert result['changed'] is False
    assert result['schedule']['kind'] == 'poller'


def test_update_sends_single_read_back(server, project, run_module):
    server.route('GET', '%s/schedules/%d' % (project, sid(server)), single(server, 'schedule_get'))
    server.route('PUT', '%s/schedules/%d' % (project, sid(server)), 'schedule_update')
    result = run_module(schedule.main, dict(project='homelab', name='nightly', active=False))
    assert result['changed'] is True
    body = server.calls('PUT')[0]['body']
    assert body['active'] is False
    assert body['id'] == sid(server) and body['cron_format'] == '0 3 * * *'
    assert 'tpl_name' not in body


def test_poller_cannot_be_deactivated(server, project, run_module):
    poller = sid(server, 'schedule_create_poller')
    server.route('GET', '%s/schedules/%d' % (project, poller), single(server, 'schedule_create_poller'))
    result = run_module(schedule.main, dict(project='homelab', name='on-push', active=False))
    assert result['failed'] is True
    assert 'state: absent' in result['msg']
    assert server.calls('PUT') == []


def test_poller_to_cron(server, project, run_module):
    poller = sid(server, 'schedule_create_poller')
    server.route('GET', '%s/schedules/%d' % (project, poller), single(server, 'schedule_create_poller'))
    server.route('PUT', '%s/schedules/%d' % (project, poller), 'schedule_update')
    result = run_module(schedule.main, dict(project='homelab', name='on-push', repository=''))
    assert result['changed'] is True
    assert result['schedule']['kind'] == 'cron'
    assert server.calls('PUT')[0]['body']['repository_id'] is None


def test_run_at(server, project, run_module):
    server.route('POST', project + '/schedules', 'schedule_create')
    run_module(schedule.main, dict(project='homelab', name='once', template='site', run_at='2099-01-01T05:00:00+02:00',
                                   delete_after_run=True))
    body = server.calls('POST', project + '/schedules')[0]['body']
    assert body['type'] == 'run_at' and body['cron_format'] == '' and body['delete_after_run'] is True


def test_cron_and_run_at_exclusive(server, project, run_module):
    result = run_module(schedule.main, dict(project='homelab', name='x', cron='* * * * *', run_at='2099-01-01T00:00:00Z'))
    assert result['failed'] is True
    assert 'mutually exclusive' in result['msg']


def test_bad_cron_reported(server, project, run_module):
    server.route('GET', '%s/schedules/%d' % (project, sid(server)), single(server, 'schedule_get'))
    server.route('PUT', '%s/schedules/%d' % (project, sid(server)), 'schedule_update_bad_cron')
    result = run_module(schedule.main, dict(project='homelab', name='nightly', cron='bad cron'))
    assert result['failed'] is True
    assert 'expected exactly 5 fields' in result['msg']


def test_delete(server, project, run_module):
    server.route('DELETE', '%s/schedules/%d' % (project, sid(server)), 'schedule_delete')
    result = run_module(schedule.main, dict(project='homelab', name='nightly', state='absent'))
    assert result['changed'] is True


def test_schedule_info_includes_pollers(server, project, run_module):
    result = run_module(schedule_info.main, dict(project='homelab'))
    assert [(s['name'], s['kind']) for s in result['schedules']] == [('nightly', 'cron'), ('on-push', 'poller')]


@pytest.mark.parametrize('value, expected', [
    ('2026-10-01T03:00:00Z', '2026-10-01T03:00:00Z'),
    ('2026-10-01T05:00:00+02:00', '2026-10-01T03:00:00Z'),
    ('2026-10-01T03:00:00.000000000Z', '2026-10-01T03:00:00Z'),
    ('2026-10-01T03:00:00.5Z', '2026-10-01T03:00:00.500000Z'),
    (None, None),
    ('not a time', 'not a time'),
])
def test_normalize_time(value, expected):
    assert normalize_time(value) == expected
