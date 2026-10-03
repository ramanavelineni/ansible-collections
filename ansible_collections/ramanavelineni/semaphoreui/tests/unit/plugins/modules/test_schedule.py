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


def test_run_at_is_sent_in_utc(server, project, run_module):
    server.route('POST', project + '/schedules', 'schedule_create')
    # What an unquoted YAML timestamp arrives as: a space where the T belongs.
    run_module(schedule.main, dict(project='homelab', name='once', template='site', run_at='2099-01-01 05:00:00+02:00'))
    assert server.calls('POST', project + '/schedules')[0]['body']['run_at'] == '2099-01-01T03:00:00Z'


@pytest.mark.parametrize('value', ['tomorrow', '', '2099-01-01', '2099-01-01T05:00:00', '2099-01-01 05:00:00'])
def test_run_at_needs_a_time_and_a_zone(server, project, run_module, value):
    result = run_module(schedule.main, dict(project='homelab', name='once', template='site', run_at=value))
    assert result['failed'] is True
    assert 'time zone' in result['msg'] and '2026-10-01T03:00:00Z' in result['msg']
    assert [r for r in server.requests if r['path'].startswith('/project')] == []
    assert server.calls('POST', project + '/schedules') == []


def run_at_schedule(server, stored):
    """The recorded project list with its schedule turned into a run-at one. No run-at schedule was recorded."""
    answer = server.response('schedules_project_list')
    answer['body'][0].update(type='run_at', cron_format='', run_at=stored)
    return answer


@pytest.mark.parametrize('declared', ['2099-01-01T03:00:00Z', '2099-01-01T05:00:00+02:00', '2099-01-01 03:00:00+00:00'])
def test_run_at_same_moment_is_no_change(server, project, run_module, declared):
    # Go writes a time as RFC 3339, with as many fraction digits as it has.
    server.route('GET', project + '/schedules', run_at_schedule(server, '2099-01-01T03:00:00Z'))
    result = run_module(schedule.main, dict(project='homelab', name='nightly', run_at=declared))
    assert result['changed'] is False
    assert result['schedule']['run_at'] == '2099-01-01T03:00:00Z'
    assert server.calls('PUT') == []


def test_run_at_other_moment_is_a_change(server, project, run_module):
    server.route('GET', project + '/schedules', run_at_schedule(server, '2099-01-01T03:00:00Z'))
    server.route('GET', '%s/schedules/%d' % (project, sid(server)), single(server, 'schedule_get'))
    server.route('PUT', '%s/schedules/%d' % (project, sid(server)), 'schedule_update')
    result = run_module(schedule.main, dict(project='homelab', name='nightly', run_at='2099-01-01T04:00:00+00:00'))
    assert result['changed'] is True
    assert server.calls('PUT')[0]['body']['run_at'] == '2099-01-01T04:00:00Z'


def template_list(project, server):
    return '%s/templates/%d/schedules' % (project, server.fixtures['template_create']['body']['id'])


def test_template_lists_not_read_when_the_project_list_has_the_name(server, project, run_module):
    result = run_module(schedule.main, dict(project='homelab', name='nightly', cron='0 3 * * *'))
    assert result['changed'] is False
    assert server.calls('GET', template_list(project, server)) == []


def test_template_lists_read_when_the_project_list_lacks_the_name(server, project, run_module):
    server.route('POST', project + '/schedules', 'schedule_create')
    result = run_module(schedule.main, dict(project='homelab', name='new', template='site', cron='0 4 * * *'))
    assert result['changed'] is True
    assert len(server.calls('GET', template_list(project, server))) == 1


def test_schedule_in_both_lists_counts_once(server, project, run_module):
    # No recorded version lists a schedule in both places; this is the project list's own row served twice.
    server.route('GET', project + '/schedules', 'schedules_empty')
    server.route('GET', template_list(project, server), 'schedules_project_list')
    result = run_module(schedule.main, dict(project='homelab', name='nightly', cron='0 3 * * *'))
    assert result.get('failed') is not True
    assert result['changed'] is False

    server.route('GET', project + '/schedules', 'schedules_project_list')
    info = run_module(schedule_info.main, dict(project='homelab'))
    assert [s['id'] for s in info['schedules']] == [sid(server)]


def test_schedule_info_reads_the_template_lists(server, project, run_module):
    result = run_module(schedule_info.main, dict(project='homelab', name='nightly'))
    assert [s['name'] for s in result['schedules']] == ['nightly']
    assert len(server.calls('GET', template_list(project, server))) == 1


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
    ('2026-10-01 03:00:00+00:00', '2026-10-01T03:00:00Z'),
    ('2026-10-01T03:00:00', '2026-10-01T03:00:00Z'),
    (None, None),
    ('not a time', 'not a time'),
])
def test_normalize_time(value, expected):
    assert normalize_time(value) == expected
