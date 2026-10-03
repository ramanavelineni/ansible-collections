# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""Option values the modules refuse or adjust themselves, and answers they have to cope with.

Each of these branches was run by no other test.
"""

import json

import pytest

from ansible_collections.ramanavelineni.harbor.plugins.module_utils.replication import normalize_filter
from ansible_collections.ramanavelineni.harbor.plugins.modules import (
    configuration,
    garbage_collection_info,
    log_rotation,
    log_rotation_info,
    project,
    registry,
    replication,
    robot_account,
    scan_all,
    scan_all_info,
    tag_immutability_info,
    tag_retention,
    tag_retention_info,
)

PURGE = '/system/purgeaudit/schedule'
SCAN_ALL = '/system/scanAll/schedule'
ACCESS = [dict(resource='repository', action='pull')]
SERVER_ERROR = dict(status=500, body=dict(errors=[dict(code='UNKNOWN', message='internal server error')]), headers={})


def location_id(server, fixture):
    return int(server.fixtures[fixture]['headers']['location'].rsplit('/', 1)[-1])


def only_the_login_check(server):
    return [r['path'] for r in server.requests] == ['/systeminfo']


# -- robot accounts -----------------------------------------------------------------

@pytest.mark.parametrize('args, message', [
    # A system permission on a project robot.
    (dict(level='project', project='fixtures-robot', permissions=[dict(kind='system', access=ACCESS)]),
     'cannot have system permissions'),
    # A system permission takes "/" and nothing else.
    (dict(permissions=[dict(kind='system', namespace='library', access=ACCESS)]), 'System permissions take namespace "/"'),
    # A project permission of a system robot has to say which project.
    (dict(permissions=[dict(access=ACCESS)]), 'needs namespace'),
    (dict(permissions=[]), 'permissions cannot be empty'),
], ids=['system-permission-on-project-robot', 'system-namespace', 'project-permission-without-namespace', 'empty'])
def test_robot_permissions_checked_before_writing(server, run_module, args, message):
    server.route('GET', '/projects', 'robot_projects_by_name')
    server.route('GET', '/robots', 'robot_list_system_empty')
    result = run_module(robot_account.main, dict(dict(name='ci'), **args))
    assert result['failed'] is True
    assert message in result['msg']
    assert server.calls('POST') == []


@pytest.mark.parametrize('namespace', [None, '/'])
def test_robot_system_permission_goes_out_with_the_root_namespace(server, run_module, namespace):
    rid = server.fixtures['robot_create']['body']['id']
    server.route('GET', '/robots', 'robot_list_system_empty')
    server.route('POST', '/robots', 'robot_create')
    server.route('GET', '/robots/%d' % rid, 'robot_get')
    permission = dict(kind='system', access=[dict(resource='project', action='list')])
    if namespace:
        permission['namespace'] = namespace
    result = run_module(robot_account.main, dict(name='fixtures-robot-sys', permissions=[permission]))
    assert result['changed'] is True
    assert server.calls('POST', '/robots')[0]['body']['permissions'] == [
        dict(kind='system', namespace='/', access=[dict(resource='project', action='list')])]


def test_robot_project_is_refused_for_a_system_robot(server, run_module):
    result = run_module(robot_account.main, dict(name='ci', project='fixtures-robot', permissions=[]))
    assert result['failed'] is True
    assert 'project is only valid with level: project' in result['msg']
    assert only_the_login_check(server)


@pytest.mark.parametrize('duration, accepted', [(0, False), (-2, False), (-1, True), (30, True)])
def test_robot_duration_is_never_or_a_number_of_days(server, run_module, duration, accepted):
    server.route('GET', '/robots', 'robot_list_system')
    result = run_module(robot_account.main, dict(name='fixtures-robot-sys', duration=duration), check_mode=True)
    if accepted:
        assert result.get('failed') is not True
        assert result['robot_account']['duration'] == duration
    else:
        assert result['failed'] is True
        assert 'duration must be -1' in result['msg']
        assert only_the_login_check(server)


def test_two_robots_of_one_name_are_refused(server, run_module):
    # Hand-edited: the recorded robot listed twice, under two ids. Harbor's
    # filter matches the stored name exactly, so this should not happen; the
    # module must not pick one.
    listing = server.response('robot_list_system')
    twin = dict(listing['body'][0], id=listing['body'][0]['id'] + 1)
    listing['body'].append(twin)
    server.route('GET', '/robots', listing)
    result = run_module(robot_account.main, dict(name='fixtures-robot-sys', state='absent'))
    assert result['failed'] is True
    assert "More than one system robot account is named 'fixtures-robot-sys'" in result['msg']
    assert server.calls('DELETE') == []


# -- projects, registries, replication -------------------------------------------------

def test_project_quota_below_unlimited_is_refused(server, run_module):
    result = run_module(project.main, dict(name='fixtures-core', quota_gb=-2))
    assert result['failed'] is True
    assert 'quota_gb must be -1' in result['msg']
    assert only_the_login_check(server)


def test_registry_ca_certificate_goes_out_with_a_create(server, run_module):
    rid = location_id(server, 'registry_create')
    certificate = '-----BEGIN CERTIFICATE-----\nx\n-----END CERTIFICATE-----\n'
    server.route('GET', '/registries', 'registry_list_before')
    server.route('POST', '/registries', 'registry_create')
    server.route('GET', '/registries/%d' % rid, 'registry_get')
    result = run_module(registry.main, dict(name='rr-fixtures-self', type='harbor', endpoint_url='http://proxy:8080/',
                                            insecure=True, ca_certificate=certificate))
    if server.version == '2.14':
        # 2.14 ignores the field, so the module refuses it before anything is read.
        assert result['failed'] is True and '2.15' in result['msg']
        assert server.calls('POST') == []
    else:
        assert result['changed'] is True
        assert server.calls('POST', '/registries')[0]['body']['ca_certificate'] == certificate


def test_replication_negative_speed_means_unlimited(server, run_module):
    # The recorded rule has speed 0 (unlimited); a negative speed is the same thing.
    server.route('GET', '/replication/policies', 'registry_replication_list')
    server.route('GET', '/registries', 'registry_list')
    result = run_module(replication.main, dict(name='rr-fixtures-pull', speed=-1))
    assert result['changed'] is False
    assert result['replication']['speed'] == 0
    assert server.calls('PUT') == []


@pytest.mark.parametrize('filters, message', [
    ([dict(type='repository', value='library/**')], 'value of type must be one of: name, tag, label, resource'),
    ([dict(type='tag', value='v*', decoration='includes')], 'value of decoration must be one of: matches, excludes'),
], ids=['unknown-type', 'unknown-decoration'])
def test_replication_filters_refused_by_the_argument_spec(server, run_module, filters, message):
    result = run_module(replication.main, dict(name='rr-fixtures-pull', filters=filters))
    assert result['failed'] is True
    assert message in result['msg']
    # Refused before the client exists: not even the login check is sent.
    assert server.requests == []


@pytest.mark.parametrize('item, message', [
    (dict(type='repository', value='library/**'), 'Filter type must be one of name, tag, label, resource'),
    (dict(value='library/**'), 'Filter type must be one of'),
    (dict(type='tag', value='v*', decoration='includes'), 'Filter decoration must be matches or excludes'),
], ids=['unknown-type', 'no-type', 'unknown-decoration'])
def test_normalize_filter_refuses_what_the_argument_spec_would(item, message):
    # The same two checks in the helper, for a caller that has no argument spec in front of it.
    with pytest.raises(ValueError, match=message):
        normalize_filter(item)


# -- schedules -------------------------------------------------------------------------

@pytest.mark.parametrize('main', [garbage_collection_info.main, log_rotation_info.main],
                         ids=['garbage_collection_info', 'log_rotation_info'])
def test_info_refuses_a_negative_number_of_runs(server, run_module, main):
    result = run_module(main, dict(runs=-1))
    assert result['failed'] is True
    assert 'runs must be 0 or more' in result['msg']
    assert only_the_login_check(server)


@pytest.mark.parametrize('main, schedule, history, fixture', [
    (garbage_collection_info.main, '/system/gc/schedule', '/system/gc', 'system_gc_schedule_custom'),
    (log_rotation_info.main, PURGE, '/system/purgeaudit', 'system_purge_schedule_custom'),
], ids=['garbage_collection_info', 'log_rotation_info'])
def test_info_with_no_runs_asked_for_reads_no_history(server, run_module, main, schedule, history, fixture):
    server.route('GET', schedule, fixture)
    result = run_module(main, dict(runs=0))
    assert result['runs'] == []
    assert server.calls('GET', history) == []


@pytest.mark.parametrize('stored, suffix', [
    ('system_purge_schedule_none', 'there is none.'),
    ('system_purge_schedule_custom', 'there is none after this change.'),
], ids=['no-schedule', 'schedule-being-removed'])
def test_log_rotation_settings_need_a_schedule(server, run_module, stored, suffix):
    server.route('GET', PURGE, stored)
    result = run_module(log_rotation.main, dict(schedule='none', audit_retention_hour=24))
    assert result['failed'] is True
    assert result['msg'] == 'audit_retention_hour only apply to a schedule; ' + suffix
    assert server.calls('PUT') == []


@pytest.mark.parametrize('main, args', [(scan_all.main, dict(schedule='daily')), (scan_all_info.main, {})],
                         ids=['scan_all', 'scan_all_info'])
def test_scan_all_reports_a_failure_that_is_not_the_missing_scanner(server, run_module, main, args):
    # Hand-written: only the "no scanner" answer (412) has its own message.
    server.route('GET', SCAN_ALL, SERVER_ERROR)
    result = run_module(main, args)
    assert result['failed'] is True
    assert 'HTTP 500' in result['msg'] and 'internal server error' in result['msg']
    assert 'no default vulnerability scanner' not in result['msg']
    assert result['request_details']['status'] == 500


# -- the connection ----------------------------------------------------------------------

def test_url_that_cannot_be_parsed_is_refused_like_any_other_bad_url(server, run_module):
    # An unclosed IPv6 bracket makes urlsplit raise instead of returning parts.
    result = run_module(scan_all_info.main, dict(url='http://[::1'))
    assert result['failed'] is True
    assert result['msg'].startswith('url must be the address of the Harbor server')
    assert "'http://[::1'" in result['msg']
    assert server.requests == []


# -- configuration -----------------------------------------------------------------------

def test_readable_secret_is_sent_when_harbor_does_not_list_it(server, run_module):
    # Hand-edited: the recorded settings without uaa_client_secret, as a Harbor
    # that stopped returning it would answer.
    current = server.response('system_configurations')
    del current['body']['uaa_client_secret']
    server.route('GET', '/configurations', current)
    server.route('PUT', '/configurations', 'system_configurations_update')
    result = run_module(configuration.main, dict(uaa_client_secret='uaa-s3cret'))
    assert result['changed'] is True
    assert server.calls('PUT', '/configurations')[0]['body'] == dict(uaa_client_secret='uaa-s3cret')
    assert 'uaa-s3cret' not in json.dumps(result)


# -- answers in a form the tag modules don't know ------------------------------------------

def tag_project(server, answer='tag_project_get'):
    pid = location_id(server, 'tag_project_create')
    server.route('GET', '/projects', 'tag_projects_list')
    server.route('GET', '/projects/%d' % pid, answer)
    return pid


def test_unknown_decoration_is_shown_as_harbor_spells_it(server, run_module):
    # Hand-edited: the recorded rule with a decoration no recorded Harbor has.
    pid = tag_project(server)
    listing = server.response('tag_immutability_list_one')
    listing['body'][0]['tag_selectors'][0]['decoration'] = 'startsWith'
    server.route('GET', '/projects/%d/immutabletagrules' % pid, listing)
    result = run_module(tag_immutability_info.main, dict(project='fixtures-tag-policy'))
    rule = result['tag_immutability'][0]
    assert rule['tags_decoration'] == 'startsWith'
    assert rule['repositories_decoration'] == 'matches'


@pytest.mark.parametrize('extras', ['not json', '[1]', ''])
def test_unreadable_untagged_setting_counts_as_off(server, run_module, extras):
    # Hand-edited: the recorded policy with a tag selector's extras in a form Harbor doesn't write.
    pid = tag_project(server, 'tag_project_get_with_retention')
    rid = location_id(server, 'tag_retention_create')
    policy = server.response('tag_retention_get_updated')
    assert json.loads(policy['body']['rules'][1]['tag_selectors'][0]['extras']) == dict(untagged=True)
    policy['body']['rules'][1]['tag_selectors'][0]['extras'] = extras
    server.route('GET', '/retentions/%d' % rid, policy)
    result = run_module(tag_retention_info.main, dict(project='fixtures-tag-policy'))
    assert [rule['untagged'] for rule in result['tag_retention']['rules']] == [False, False, False]
    assert len(server.calls('GET', '/projects/%d' % pid)) == 1


def test_new_retention_policy_that_cannot_be_found_is_returned_as_declared(server, run_module):
    # Hand-written create answer without a Location header, and the project
    # still names no policy afterwards. The create went through, so the task
    # reports the change with what it sent and no id.
    pid = tag_project(server)
    server.route('POST', '/retentions', dict(status=201, body=None, headers={}))
    result = run_module(tag_retention.main, dict(project='fixtures-tag-policy', rules=[dict(template='always')]))
    assert result['changed'] is True
    assert result['tag_retention']['id'] is None
    assert [rule['template'] for rule in result['tag_retention']['rules']] == ['always']
    assert len(server.calls('GET', '/projects/%d' % pid)) == 2
    assert [r['path'] for r in server.requests if r['path'].startswith('/retentions/')] == []
