# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

import json

import pytest

from ansible_collections.ramanavelineni.harbor.plugins.modules import project, project_info
from ansible_collections.ramanavelineni.harbor.tests.unit.plugins.conftest import transport_error

GIB = 1024 ** 3


def reporting_2_14(server):
    """The recorded /systeminfo, hand-edited to an older Harbor: 2.14 is no longer recorded, but
    the modules still refuse what it would ignore."""
    info = server.response('systeminfo')
    info['body']['harbor_version'] = 'v2.14.6-f435c950'
    server.route('GET', '/systeminfo', info)


def pid(server):
    return int(server.fixtures['project_create']['headers']['location'].rsplit('/', 1)[-1])


def qid(server):
    return server.fixtures['quotas_created']['body'][0]['id']


def existing(server, listing='projects_with_created', quotas='quotas_created'):
    server.route('GET', '/projects', listing)
    server.route('GET', '/registries', 'registries_empty')
    server.route('GET', '/quotas', quotas)


def creating(server):
    server.route('GET', '/projects', 'projects_before')
    server.route('POST', '/projects', 'project_create')
    server.route('GET', '/projects/%d' % pid(server), 'project_get')
    server.route('GET', '/quotas', 'quotas_created')


def test_create(server, run_module):
    creating(server)
    result = run_module(project.main, dict(name='fixtures-core', metadata=dict(auto_scan=True), quota_gb=5))
    assert result['changed'] is True
    assert result['project']['project_id'] == pid(server)
    assert result['project']['quota_gb'] == 5
    assert server.calls('POST', '/projects')[0]['body'] == dict(
        project_name='fixtures-core', metadata=dict(auto_scan='true', public='false'), storage_limit=5 * GIB)


def test_create_check_mode(server, run_module):
    server.route('GET', '/projects', 'projects_before')
    result = run_module(project.main, dict(name='fixtures-core', public=True), check_mode=True)
    assert result['changed'] is True
    assert result['project']['public'] is True
    assert server.calls('POST') == []


def test_no_change(server, run_module):
    existing(server, 'projects_with_updated', 'quotas_created_updated')
    result = run_module(project.main, dict(name='fixtures-core', public=True,
                                           metadata=dict(severity='HIGH', auto_scan='true'), quota_gb=-1))
    assert result['changed'] is False
    assert server.calls('PUT') == []


def test_update_sends_only_changed_keys(server, run_module):
    existing(server)
    server.route('PUT', '/projects/%d' % pid(server), 'project_update')
    server.route('PUT', '/quotas/%d' % qid(server), 'quota_update')
    server.route('GET', '/projects/%d' % pid(server), 'project_get_updated')
    server.route('GET', '/quotas', 'quotas_created', 'quotas_created_updated')
    result = run_module(project.main, dict(name='fixtures-core', public=True,
                                           metadata=dict(severity='high', auto_scan=True), quota_gb=-1))
    assert result['changed'] is True
    assert server.calls('PUT', '/projects/%d' % pid(server))[0]['body'] == dict(
        metadata=dict(severity='high', public='true'))
    assert server.calls('PUT', '/quotas/%d' % qid(server))[0]['body'] == dict(hard=dict(storage=-1))
    assert result['diff']['before']['public'] is False and result['diff']['after']['public'] is True
    assert result['project']['quota_gb'] == -1
    assert result['project']['metadata'] == dict(severity='high', auto_scan='true')
    assert not result.get('warnings')


def test_update_check_mode(server, run_module):
    existing(server)
    result = run_module(project.main, dict(name='fixtures-core', quota_gb=10), check_mode=True)
    assert result['changed'] is True
    assert result['project']['quota_gb'] == 10
    assert server.calls('PUT') == []


def test_unmanaged_options_unchanged(server, run_module):
    existing(server)
    result = run_module(project.main, dict(name='fixtures-core'))
    assert result['changed'] is False


def test_metadata_validation(server, run_module):
    for metadata, message in ((dict(nope=1), 'not a Harbor project setting'),
                              (dict(severity='huge'), 'metadata.severity must be one of'),
                              (dict(auto_scan='maybe'), 'must be a boolean'),
                              (dict(proxy_speed_kb='fast'), 'must be an integer'),
                              (dict(public='true'), 'use the public option'),
                              (dict(retention_id='1'), 'tag_retention')):
        result = run_module(project.main, dict(name='x', metadata=metadata))
        assert result['failed'] is True, metadata
        assert message in result['msg'], (metadata, result['msg'])
    assert server.calls('POST') == [] and server.calls('PUT') == []


def test_newer_metadata_key_needs_2_15(server, run_module):
    creating(server)
    result = run_module(project.main, dict(name='fixtures-core', metadata=dict(proxy_cache_local_on_not_found=True)))
    assert result['changed'] is True


def test_newer_metadata_key_is_refused_on_2_14(server, run_module):
    reporting_2_14(server)
    creating(server)
    result = run_module(project.main, dict(name='fixtures-core', metadata=dict(proxy_cache_local_on_not_found=True)))
    assert result['failed'] is True and 'needs Harbor 2.15' in result['msg']
    assert server.calls('POST') == []


def test_negligible_severity_is_none(server, run_module):
    existing(server)
    server.route('PUT', '/projects/%d' % pid(server), 'project_update')
    run_module(project.main, dict(name='fixtures-core', metadata=dict(severity='Negligible')))
    assert server.calls('PUT')[0]['body'] == dict(metadata=dict(severity='none'))


def test_proxy_registry_cannot_change(server, run_module):
    listing = server.response('projects_with_created')
    proxy = server.response('project_get_proxy')['body']
    listing['body'] = [proxy]
    registries = server.response('registries_one')
    registries['body'].append(dict(registries['body'][0], id=registries['body'][0]['id'] + 1, name='other'))
    server.route('GET', '/projects', listing)
    server.route('GET', '/registries', registries)
    server.route('GET', '/quotas', 'quotas_created')
    result = run_module(project.main, dict(name=proxy['name'], proxy_registry='other'))
    assert result['failed'] is True
    assert 'cannot change' in result['msg']
    same = run_module(project.main, dict(name=proxy['name'], proxy_registry=registries['body'][0]['name']))
    assert same['changed'] is False


def test_unknown_registry(server, run_module):
    server.route('GET', '/projects', 'projects_before')
    server.route('GET', '/registries', 'registries_empty')
    result = run_module(project.main, dict(name='new', proxy_registry='hub'))
    assert result['failed'] is True and "Registry 'hub' does not exist" in result['msg']


def test_delete_requires_confirmation(server, run_module):
    existing(server)
    result = run_module(project.main, dict(name='fixtures-core', state='absent'))
    assert result['failed'] is True and 'confirm_delete' in result['msg']
    assert server.calls('DELETE') == []


def test_delete(server, run_module):
    existing(server)
    server.route('DELETE', '/projects/%d' % pid(server), 'project_delete')
    result = run_module(project.main, dict(name='fixtures-core', state='absent', confirm_delete=True))
    assert result['changed'] is True and result['project'] == {}
    assert [r['path'] for r in server.calls('DELETE')] == ['/projects/%d' % pid(server)]


def test_delete_with_repositories_fails(server, run_module):
    listing = server.response('projects_with_created')
    for p in listing['body']:
        p['repo_count'] = 3
    existing(server, listing)
    result = run_module(project.main, dict(name='fixtures-core', state='absent', confirm_delete=True))
    assert result['failed'] is True and '3 repositories' in result['msg']
    assert server.calls('DELETE') == []


def test_delete_missing_is_no_change(server, run_module):
    server.route('GET', '/projects', 'projects_before')
    result = run_module(project.main, dict(name='fixtures-core', state='absent', confirm_delete=True))
    assert result['changed'] is False


def test_rejected_create_is_reported(server, run_module):
    server.route('GET', '/projects', 'projects_before')
    server.route('POST', '/projects', 'project_create_conflict')
    result = run_module(project.main, dict(name='fixtures-core'))
    assert result['failed'] is True
    assert 'HTTP 409' in result['msg'] and 'already exists' in result['msg']
    assert result['request_details']['request']['project_name'] == 'fixtures-core'
    assert 's3cret-pw' not in json.dumps(result)


def test_lists_follow_pages(server, run_module):
    first = server.response('projects_before')
    row = first['body'][0]
    first['body'] = [dict(row, project_id=1000 + i, name='p%03d' % i) for i in range(100)]
    first['headers'] = {'x-total-count': '101'}
    second = server.response('projects_before')
    second['body'] = [dict(row, project_id=2000, name='last')]
    second['headers'] = {'x-total-count': '101'}
    server.route('GET', '/projects', first, second)
    server.route('GET', '/registries', 'registries_empty')
    result = run_module(project.main, dict(name='last', state='absent', confirm_delete=True), check_mode=True)
    assert result['changed'] is True
    assert [c['query']['page'] for c in server.calls('GET', '/projects')] == [['1'], ['2']]


def test_reads_retried(server, run_module):
    server.route('GET', '/projects', transport_error(), 'projects_before')
    result = run_module(project.main, dict(name='fixtures-core', state='absent', confirm_delete=True))
    assert result['changed'] is False
    assert len(server.calls('GET', '/projects')) == 2


def test_creates_not_retried(server, run_module):
    server.route('GET', '/projects', 'projects_before')
    server.route('POST', '/projects', transport_error(), 'project_create')
    result = run_module(project.main, dict(name='fixtures-core'))
    assert result['failed'] is True and 'without an HTTP response' in result['msg']
    assert len(server.calls('POST', '/projects')) == 1


def test_untested_version_warns(server, run_module):
    info = server.response('systeminfo')
    info['body']['harbor_version'] = 'v2.9.0-abc'
    server.route('GET', '/systeminfo', info)
    server.route('GET', '/projects', 'projects_before')
    result = run_module(project.main, dict(name='fixtures-core', state='absent', confirm_delete=True))
    assert 'v2.9.0-abc' in json.dumps(result.get('warnings', []))


def test_project_info(server, run_module):
    server.route('GET', '/projects', 'projects_with_updated')
    server.route('GET', '/registries', 'registries_empty')
    server.route('GET', '/quotas', 'quotas_all')
    result = run_module(project_info.main, {})
    names = [p['name'] for p in result['projects']]
    assert names == sorted(names) and 'library' in names and 'fixtures-core' in names
    core = [p for p in result['projects'] if p['name'] == 'fixtures-core'][0]
    assert core['public'] is True and core['metadata']['severity'] == 'high'
    assert run_module(project_info.main, dict(name='nope'))['projects'] == []


def test_quota_on_a_project_without_quota_fails(server, run_module):
    existing(server)
    server.route('GET', '/quotas', dict(status=200, body=[], headers={}))
    result = run_module(project.main, dict(name='fixtures-core', quota_gb=5))
    assert result['failed'] is True
    assert 'has no quota' in result['msg']
    assert server.calls('PUT') == []


# -- a user who is not an administrator ----------------------------------------
# Registries and quotas are refused to anyone but an administrator. Hand-written:
# no fixture was recorded as a non-admin. The body follows Harbor's error model.

FORBIDDEN = dict(status=403, body=dict(errors=[dict(code='FORBIDDEN', message='forbidden')]), headers={})


def as_non_admin(server, listing='projects_with_created', denied=None):
    denied = denied or FORBIDDEN
    server.route('GET', '/projects', listing)
    server.route('GET', '/registries', denied)
    server.route('GET', '/quotas', denied)


def proxy_listing(server):
    listing = server.response('projects_with_created')
    listing['body'] = [server.response('project_get_proxy')['body']]
    return listing


def test_registries_only_read_when_needed(server, run_module):
    existing(server)
    result = run_module(project.main, dict(name='fixtures-core'))
    assert result['changed'] is False
    assert server.calls('GET', '/registries') == []


def test_non_admin_updates_metadata(server, run_module):
    as_non_admin(server)
    server.route('PUT', '/projects/%d' % pid(server), 'project_update')
    server.route('GET', '/projects/%d' % pid(server), 'project_get_updated')
    result = run_module(project.main, dict(name='fixtures-core', public=True))
    assert result['changed'] is True
    assert result['project']['public'] is True
    assert result['project']['quota_gb'] is None
    assert server.calls('PUT')[0]['body'] == dict(metadata=dict(public='true'))
    assert server.calls('GET', '/registries') == []
    # The refused quota read is not repeated after the write.
    assert len(server.calls('GET', '/quotas')) == 1
    assert not result.get('warnings')


def test_non_admin_no_change(server, run_module):
    as_non_admin(server)
    result = run_module(project.main, dict(name='fixtures-core'))
    assert result['changed'] is False
    assert result['project']['quota_gb'] is None


def test_non_admin_cannot_set_quota(server, run_module):
    as_non_admin(server)
    result = run_module(project.main, dict(name='fixtures-core', public=True, quota_gb=5))
    assert result['failed'] is True
    assert 'may not read project quotas' in result['msg'] and 'administrator' in result['msg']
    assert server.calls('PUT') == []


def test_non_admin_cannot_use_proxy_registry(server, run_module):
    as_non_admin(server, 'projects_before')
    result = run_module(project.main, dict(name='new', proxy_registry='hub'))
    assert result['failed'] is True
    assert 'may not read registries' in result['msg']
    assert server.calls('POST') == []


def test_non_admin_proxy_project_has_no_registry_name(server, run_module):
    listing = proxy_listing(server)
    as_non_admin(server, listing)
    result = run_module(project.main, dict(name=listing['body'][0]['name']))
    assert result['changed'] is False
    assert result['project']['registry_id'] == listing['body'][0]['registry_id']
    assert result['project']['proxy_registry'] is None


def test_non_admin_create_with_a_quota_warns_that_harbor_applied_its_default(server, run_module):
    # Harbor 2.15.4 handler/project.go:131 stores the default quota per
    # project for a non-administrator, whatever storage_limit says.
    creating(server)
    server.route('GET', '/quotas', FORBIDDEN)
    result = run_module(project.main, dict(name='fixtures-core', quota_gb=7))
    assert result['changed'] is True
    assert result['project']['project_id'] == pid(server)
    assert result['project']['quota_gb'] is None
    assert len(result['warnings']) == 1
    assert 'default quota per project' in json.dumps(result['warnings'])


def test_non_admin_create_without_a_quota_does_not_warn(server, run_module):
    creating(server)
    server.route('GET', '/quotas', FORBIDDEN)
    result = run_module(project.main, dict(name='fixtures-core'))
    assert result['changed'] is True
    assert result['project']['quota_gb'] is None
    assert not result.get('warnings')


def test_create_reports_the_quota_harbor_stored(server, run_module):
    # quotas_created holds 5 GiB: what Harbor stores when it substitutes its
    # default for the 7 GiB the task asked for.
    creating(server)
    result = run_module(project.main, dict(name='fixtures-core', quota_gb=7))
    assert result['changed'] is True
    assert result['project']['quota_gb'] == 5
    assert result['diff']['after']['quota_gb'] == 5
    assert len(result['warnings']) == 1
    assert 'quota_gb' in json.dumps(result['warnings'])


def test_create_with_the_stored_quota_does_not_warn(server, run_module):
    creating(server)
    result = run_module(project.main, dict(name='fixtures-core', quota_gb=5))
    assert result['project']['quota_gb'] == 5
    assert not result.get('warnings')


def test_quota_of_one_gib_is_accepted(server, run_module):
    creating(server)
    result = run_module(project.main, dict(name='fixtures-core', quota_gb=1))
    assert result['changed'] is True
    assert server.calls('POST', '/projects')[0]['body']['storage_limit'] == GIB


def test_other_quota_failures_are_reported(server, run_module):
    existing(server)
    server.route('GET', '/quotas', dict(status=500, body=dict(errors=[dict(code='UNKNOWN', message='boom')]),
                                        headers={}))
    result = run_module(project.main, dict(name='fixtures-core'))
    assert result['failed'] is True and 'HTTP 500' in result['msg']


@pytest.mark.parametrize('denied', [FORBIDDEN, 'robot_configurations_forbidden'], ids=['403', 'recorded-401'])
def test_project_info_non_admin(server, run_module, denied):
    listing = server.response('projects_with_created')
    listing['body'].append(server.response('project_get_proxy')['body'])
    as_non_admin(server, listing, server.response(denied) if isinstance(denied, str) else denied)
    result = run_module(project_info.main, {})
    assert 'failed' not in result
    assert len(result['projects']) == len(listing['body'])
    assert all(p['quota_gb'] is None and p['proxy_registry'] is None for p in result['projects'])


def test_project_info_reads_registries_only_for_proxy_projects(server, run_module):
    server.route('GET', '/projects', 'projects_with_created')
    server.route('GET', '/quotas', 'quotas_all')
    result = run_module(project_info.main, {})
    assert 'failed' not in result
    assert server.calls('GET', '/registries') == []


def test_project_info_other_failures_are_reported(server, run_module):
    server.route('GET', '/projects', 'projects_with_created')
    server.route('GET', '/quotas', dict(status=500, body=None, headers={}))
    result = run_module(project_info.main, {})
    assert result['failed'] is True and 'HTTP 500' in result['msg']


# -- the result of an update is read back --------------------------------------

def test_update_result_is_what_harbor_stored(server, run_module):
    # Hand-edited answer: the recorded project after the update, with a repository
    # count and a severity the module could not have computed.
    stored = server.response('project_get_updated')
    stored['body']['repo_count'] = 3
    stored['body']['metadata']['severity'] = 'critical'
    existing(server)
    server.route('PUT', '/projects/%d' % pid(server), 'project_update')
    server.route('GET', '/projects/%d' % pid(server), stored)
    result = run_module(project.main, dict(name='fixtures-core', public=True, metadata=dict(severity='high')))
    assert result['changed'] is True
    assert result['project']['repo_count'] == 3
    assert result['project']['metadata']['severity'] == 'critical'
    assert result['diff']['after'] == result['project']
    # Harbor stored another severity than was sent: the next run changes it again.
    assert len(result['warnings']) == 1
    assert 'severity' in json.dumps(result['warnings']) and 'public' not in json.dumps(result['warnings'])
    # One read after the write; the quota was not written, so it is not read again.
    assert [(r['method'], r['path']) for r in server.requests[-2:]] == [
        ('PUT', '/projects/%d' % pid(server)), ('GET', '/projects/%d' % pid(server))]
    assert len(server.calls('GET', '/quotas')) == 1


def test_quota_is_read_back_after_it_is_written(server, run_module):
    existing(server)
    server.route('PUT', '/quotas/%d' % qid(server), 'quota_update')
    server.route('GET', '/projects/%d' % pid(server), 'project_get')
    server.route('GET', '/quotas', 'quotas_created', 'quotas_created_updated')
    result = run_module(project.main, dict(name='fixtures-core', quota_gb=-1))
    assert result['changed'] is True
    assert result['project']['quota_gb'] == -1
    assert not result.get('warnings')
    assert len(server.calls('GET', '/quotas')) == 2
    assert server.calls('PUT', '/projects/%d' % pid(server)) == []


def test_quota_that_was_not_stored_is_reported(server, run_module):
    # The quota read after the write still shows the old limit (the recorded
    # answer from before the update, served twice).
    existing(server)
    server.route('PUT', '/quotas/%d' % qid(server), 'quota_update')
    server.route('GET', '/projects/%d' % pid(server), 'project_get')
    result = run_module(project.main, dict(name='fixtures-core', quota_gb=-1))
    assert result['project']['quota_gb'] == 5
    assert 'quota_gb' in json.dumps(result['warnings'])


def test_update_check_mode_predicts_the_real_result(server, run_module):
    existing(server)
    server.route('PUT', '/projects/%d' % pid(server), 'project_update')
    server.route('PUT', '/quotas/%d' % qid(server), 'quota_update')
    server.route('GET', '/projects/%d' % pid(server), 'project_get_updated')
    args = dict(name='fixtures-core', public=True, metadata=dict(severity='high', auto_scan=True), quota_gb=-1)
    server.route('GET', '/quotas', 'quotas_created', 'quotas_created_updated')
    real = run_module(project.main, args)
    server.route('GET', '/quotas', 'quotas_created')
    check = run_module(project.main, args, check_mode=True)
    assert check['project'] == real['project']
    assert check['diff'] == real['diff']


def test_non_admin_update_survives_a_refused_quota_read_after_the_write(server, run_module):
    # Hand-written: the quota is readable before the write and refused after it.
    existing(server)
    server.route('PUT', '/quotas/%d' % qid(server), 'quota_update')
    server.route('GET', '/projects/%d' % pid(server), 'project_get')
    server.route('GET', '/quotas', 'quotas_created', FORBIDDEN)
    result = run_module(project.main, dict(name='fixtures-core', quota_gb=-1))
    assert result['changed'] is True
    assert result['project']['quota_gb'] == -1


# -- proxy-cache options of Harbor 2.16 ---------------------------------------

def on_2_15(server):
    return server.version == '2.15'


def proxy_project(server, fixture='project_get_proxy'):
    """An existing proxy-cache project: the recorded one, as the only project listed."""
    listing = server.response('projects_with_created')
    proxy = server.response(fixture)['body']
    listing['body'] = [proxy]
    server.route('GET', '/projects', listing)
    server.route('GET', '/registries', 'registries_one')
    server.route('GET', '/quotas', 'quotas_created')
    return proxy


FILTER = dict(proxy_cache_filter_kind='regex', proxy_cache_filter_pattern='^library/.*', proxy_referrer_api=True)


def test_proxy_filter_is_set_on_a_proxy_project(server, run_module):
    proxy = proxy_project(server)
    path = '/projects/%d' % proxy['project_id']
    server.route('PUT', path, 'project_update_proxy_filter')
    server.route('GET', path, 'project_get_proxy_filtered')
    result = run_module(project.main, dict(name=proxy['name'], metadata=FILTER))
    if on_2_15(server):
        # 2.15 drops the keys (recorded), so the module refuses them first.
        assert result['failed'] is True and 'needs Harbor 2.16' in result['msg']
        assert server.calls('PUT') == []
        return
    assert result['changed'] is True
    assert server.calls('PUT', path)[0]['body'] == dict(metadata=dict(
        proxy_cache_filter_kind='regex', proxy_cache_filter_pattern='^library/.*', proxy_referrer_api='true'))
    assert result['project']['metadata']['proxy_cache_filter_pattern'] == '^library/.*'
    assert not result.get('warnings')


def test_stored_proxy_filter_is_no_change(server, run_module):
    if on_2_15(server):
        pytest.skip('2.15 does not store the proxy-cache filter (see the test above)')
    proxy = proxy_project(server, 'project_get_proxy_filtered')
    result = run_module(project.main, dict(name=proxy['name'], metadata=FILTER))
    assert result['changed'] is False
    assert server.calls('PUT') == []


def test_proxy_only_keys_fail_on_a_project_that_is_no_proxy(server, run_module):
    existing(server)
    result = run_module(project.main, dict(name='fixtures-core', metadata=dict(proxy_referrer_api=True)))
    assert result['failed'] is True
    if on_2_15(server):
        assert 'needs Harbor 2.16' in result['msg']
    else:
        assert 'only applies to a proxy-cache project' in result['msg']
    assert server.calls('PUT') == []


@pytest.mark.parametrize('metadata, message', [
    (dict(proxy_cache_filter_kind='glob'), 'metadata.proxy_cache_filter_kind must be one of , doublestar, regex'),
    (dict(proxy_cache_filter_pattern=5), 'metadata.proxy_cache_filter_pattern must be a string'),
    (dict(proxy_referrer_api='yes please'), 'metadata.proxy_referrer_api must be a boolean'),
])
def test_proxy_filter_values_are_checked_first(server, run_module, metadata, message):
    # Harbor answers 400 for an unknown kind (recorded on 2.16) but stores any
    # proxy_referrer_api text.
    result = run_module(project.main, dict(name='x', metadata=metadata))
    assert result['failed'] is True
    assert message in result['msg']
    assert server.calls('PUT') == [] and server.calls('POST') == []


def test_recorded_unknown_filter_kind_is_refused_by_harbor(server):
    answer = server.fixtures['project_update_proxy_bad_kind']
    assert answer['status'] == (200 if on_2_15(server) else 400)


def creating_proxy_with_days(server):
    created = server.fixtures['project_create_proxy_days']
    new_id = int(created['headers']['location'].rsplit('/', 1)[-1])
    server.route('GET', '/projects', 'projects_before')
    server.route('GET', '/registries', 'registries_one')
    server.route('POST', '/projects', 'project_create_proxy_days')
    server.route('GET', '/projects/%d' % new_id, 'project_get_proxy_days')
    server.route('GET', '/quotas', 'quotas_created')
    return server.fixtures['registries_one']['body'][0]['name']


def test_retention_days_goes_out_with_a_new_proxy_project(server, run_module):
    registry_name = creating_proxy_with_days(server)
    result = run_module(project.main, dict(name='fixtures-core-proxy-days', proxy_registry=registry_name,
                                           retention_days=3))
    if on_2_15(server):
        # 2.15 ignores the field and keeps 7 days (recorded), so the module refuses it.
        assert result['failed'] is True and 'retention_days needs Harbor 2.16' in result['msg']
        assert server.calls('POST') == []
        return
    assert result['changed'] is True
    body = server.calls('POST', '/projects')[0]['body']
    assert body['retention_days'] == 3 and body['registry_id'] == server.fixtures['registries_one']['body'][0]['id']


def test_recorded_retention_days_end_up_in_the_retention_rule(server):
    rule = server.fixtures['project_proxy_days_retention']['body']['rules'][0]
    assert rule['params']['nDaysSinceLastPull'] == (7 if on_2_15(server) else 3)


def test_retention_days_fail_for_a_new_project_that_is_no_proxy(server, run_module):
    creating(server)
    result = run_module(project.main, dict(name='fixtures-core', retention_days=3))
    assert result['failed'] is True
    if on_2_15(server):
        assert 'retention_days needs Harbor 2.16' in result['msg']
    else:
        # What Harbor answers too (recorded), only before anything is created.
        assert 'only applies to a new proxy-cache project' in result['msg']
        assert server.fixtures['project_create_days_not_proxy']['status'] == 400
    assert server.calls('POST') == []


@pytest.mark.parametrize('days', [-1, 18251])
def test_retention_days_range(server, run_module, days):
    registry_name = creating_proxy_with_days(server)
    result = run_module(project.main, dict(name='fixtures-core-proxy-days', proxy_registry=registry_name,
                                           retention_days=days))
    assert result['failed'] is True and 'retention_days must be between 0 and 18250' in result['msg']
    assert server.calls('POST') == []


def test_retention_days_are_left_alone_for_an_existing_project(server, run_module):
    proxy = proxy_project(server)
    result = run_module(project.main, dict(name=proxy['name'], retention_days=3))
    assert result['changed'] is False
    assert server.calls('PUT') == []
