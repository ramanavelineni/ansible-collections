# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

import json

from ansible_collections.ramanavelineni.harbor.plugins.modules import project, project_info
from ansible_collections.ramanavelineni.harbor.tests.unit.plugins.conftest import transport_error

GIB = 1024 ** 3


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
    result = run_module(project.main, dict(name='fixtures-core', public=True,
                                           metadata=dict(severity='high', auto_scan=True), quota_gb=-1))
    assert result['changed'] is True
    assert server.calls('PUT', '/projects/%d' % pid(server))[0]['body'] == dict(
        metadata=dict(severity='high', public='true'))
    assert server.calls('PUT', '/quotas/%d' % qid(server))[0]['body'] == dict(hard=dict(storage=-1))
    assert result['diff']['before']['public'] is False and result['diff']['after']['public'] is True


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
    if server.version == '2.14':
        assert result['failed'] is True and 'needs Harbor 2.15' in result['msg']
    else:
        assert result['changed'] is True


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
    assert json.loads(result['request_details']['request'])['project_name'] == 'fixtures-core'
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
