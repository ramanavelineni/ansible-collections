# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

import copy
import json

import pytest
import yaml

from ansible_collections.ramanavelineni.semaphoreui.plugins.modules import project, project_restore

PROJECT = 'bk-fixtures'
RESTORED = 'bk-fixtures-restored'


def backup(server):
    return copy.deepcopy(server.fixtures['backup_get']['body'])


def restores(server):
    return server.calls('POST', '/projects/restore')


def test_does_nothing_when_the_project_exists(server, run_module):
    server.route('GET', '/projects', 'backup_projects')
    for check_mode in (False, True):
        result = run_module(project_restore.main, dict(backup=backup(server)), check_mode=check_mode)
        assert result['changed'] is False
        assert result['project']['name'] == PROJECT and result['project']['max_parallel_tasks'] == 2
        assert result['diff']['before'] == result['diff']['after'] == result['project']
    assert restores(server) == []


def test_the_existing_project_is_not_compared_with_the_backup(server, run_module):
    server.route('GET', '/projects', 'backup_projects')
    other = backup(server)
    other['meta']['max_parallel_tasks'] = 9
    other['templates'] = []
    result = run_module(project_restore.main, dict(backup=other))
    assert result['changed'] is False and result['project']['max_parallel_tasks'] == 2


def test_restores_under_another_name(server, run_module):
    server.route('GET', '/projects', 'backup_projects')
    server.route('POST', '/projects/restore', 'backup_restore')
    result = run_module(project_restore.main, dict(backup=backup(server), name=RESTORED))
    assert result['changed'] is True
    created = server.fixtures['backup_restore']['body']
    assert result['project'] == dict(id=created['id'], name=RESTORED, alert=False, alert_chat='',
                                     max_parallel_tasks=2, type='')
    assert result['diff'] == dict(before={}, after=result['project'])
    # The whole backup goes out, with the name the task gave.
    sent = restores(server)[0]['body']
    assert sent == dict(backup(server), meta=dict(backup(server)['meta'], name=RESTORED))


def test_the_result_is_what_the_project_module_returns(server, run_module):
    server.route('GET', '/projects', 'backup_projects')
    server.route('POST', '/projects/restore', 'backup_restore')
    restored = run_module(project_restore.main, dict(backup=backup(server), name=RESTORED))['project']
    server.route('GET', '/projects', 'backup_projects_restored')
    assert run_module(project.main, dict(name=RESTORED))['project'] == restored


def test_restores_from_a_file(server, run_module, tmp_path):
    server.route('GET', '/projects', 'backup_projects')
    server.route('POST', '/projects/restore', 'backup_restore')
    src = tmp_path / 'backup.json'
    src.write_text(json.dumps(backup(server)))
    result = run_module(project_restore.main, dict(src=str(src), name=RESTORED))
    assert result['changed'] is True
    assert restores(server)[0]['body']['meta']['name'] == RESTORED
    # The file is read, not rewritten.
    assert json.loads(src.read_text()) == backup(server)


def test_check_mode_sends_nothing(server, run_module):
    server.route('GET', '/projects', 'backup_projects')
    result = run_module(project_restore.main, dict(backup=backup(server), name=RESTORED), check_mode=True)
    assert result['changed'] is True
    assert result['project'] == dict(name=RESTORED, alert=False, alert_chat='', max_parallel_tasks=2, type='')
    assert restores(server) == []


def test_check_mode_predicts_what_a_real_run_returns(server, run_module):
    server.route('GET', '/projects', 'backup_projects')
    server.route('POST', '/projects/restore', 'backup_restore')
    real = run_module(project_restore.main, dict(backup=backup(server), name=RESTORED))
    checked = run_module(project_restore.main, dict(backup=backup(server), name=RESTORED), check_mode=True)
    assert dict(real['project'], id=None) == dict(checked['project'], id=None)
    assert real['project']['id'] and 'id' not in checked['project']


@pytest.mark.parametrize('given, said', [
    (dict(backup={}), 'it has no "meta" section'),
    (dict(backup=dict(meta='homelab')), 'it has no "meta" section'),
    (dict(backup=dict(meta=dict(alert=False))), 'names no project (meta.name), and the task gives no name'),
    (dict(backup=dict(meta=dict(name='  '))), 'names no project'),
    (dict(backup=dict(meta=dict(name='x')), name=''), 'names no project'),
])
def test_what_is_not_a_backup_is_refused_before_any_request(server, run_module, given, said):
    result = run_module(project_restore.main, given)
    assert result['failed'] is True and said in result['msg']
    # Semaphore would have created a project without a name from the first three.
    assert [r for r in server.requests if not r['path'].startswith('/auth/') and r['path'] != '/info'] == []


def test_a_file_that_cannot_be_used_is_refused(server, run_module, tmp_path):
    missing = run_module(project_restore.main, dict(src=str(tmp_path / 'missing.json')))
    assert missing['failed'] is True and 'Cannot read src' in missing['msg']
    garbage = tmp_path / 'garbage.json'
    garbage.write_text('{"meta": ')
    result = run_module(project_restore.main, dict(src=str(garbage)))
    assert result['failed'] is True and 'does not hold JSON' in result['msg']
    listed = tmp_path / 'list.json'
    listed.write_text('[]')
    assert 'it has no "meta" section' in run_module(project_restore.main, dict(src=str(listed)))['msg']


def test_src_or_backup(server, run_module):
    assert 'one of the following is required: src, backup' in run_module(project_restore.main, {})['msg']
    both = run_module(project_restore.main, dict(src='/tmp/x.json', backup=dict(meta=dict(name='x'))))
    assert 'mutually exclusive' in both['msg']


def test_a_backup_semaphore_refuses_whole(server, run_module):
    server.route('GET', '/projects', 'backup_projects', 'backup_projects_after_broken')
    server.route('POST', '/projects/restore', 'backup_restore_broken')
    broken = backup(server)
    broken['templates'][0]['repository'] = 'no-such-repository'
    result = run_module(project_restore.main, dict(backup=broken, name='bk-fixtures-broken'))
    assert result['failed'] is True
    assert 'returned HTTP 400: (empty body)' in result['msg'] and 'Nothing was created' in result['msg']
    assert result['request_details']['status'] == 400
    assert len(server.calls('GET', '/projects')) == 2


def test_a_restore_that_fails_half_way_names_what_it_left(server, run_module):
    server.route('GET', '/projects', 'backup_projects', 'backup_projects_after_partial')
    server.route('POST', '/projects/restore', 'backup_restore_partial')
    partial = dict(meta=dict(name='bk-fixtures-partial'),
                   schedules=[dict(name='nightly', template='no-such-template', cron_format='0 3 * * *')])
    result = run_module(project_restore.main, dict(backup=partial))
    left = [p for p in server.fixtures['backup_projects_after_partial']['body'] if p['name'] == 'bk-fixtures-partial']
    assert result['failed'] is True
    assert "Semaphore created project 'bk-fixtures-partial' (id %d) before it failed" % left[0]['id'] in result['msg']
    assert 'Nothing was created' not in result['msg']


def test_the_recorded_restore_left_keys_empty_and_secret_variables_out(server):
    # What the documentation says of a restored project, checked on what the servers answered.
    keys = dict((k['name'], k) for k in server.fixtures['backup_restored_keys']['body'])
    assert keys['deploy']['type'] == 'ssh' and keys['deploy']['empty'] is True
    assert 'API_KEY' not in keys
    environments = server.fixtures['backup_restored_environments']['body']
    assert [e['name'] for e in environments] == ['vars'] and json.loads(environments[0]['env']) == dict(TZ='UTC')


def test_a_name_that_exists_by_the_time_of_the_restore(server, run_module):
    # Another run created the project between the lookup and the restore: Semaphore's own refusal is shown.
    empty = server.response('backup_projects')
    empty['body'] = []
    server.route('GET', '/projects', empty, 'backup_projects')
    server.route('POST', '/projects/restore', 'backup_restore_exists')
    result = run_module(project_restore.main, dict(backup=backup(server)))
    assert result['failed'] is True and "project with name 'bk-fixtures' already exists" in result['msg']
    assert 'Nothing was created. Run the task again' in result['msg'] and 'half filled' not in result['msg']
    assert len(server.calls('GET', '/projects')) == 1


@pytest.mark.parametrize('check_mode', [False, True], ids=['real', 'check'])
def test_result_has_the_documented_keys(server, run_module, check_mode):
    server.route('GET', '/projects', 'backup_projects')
    server.route('POST', '/projects/restore', 'backup_restore')
    result = run_module(project_restore.main, dict(backup=backup(server), name=RESTORED), check_mode=check_mode)
    assert set(result) - set(['changed', 'diff', 'invocation', 'warnings', 'deprecations']) == set(yaml.safe_load(project_restore.RETURN))
