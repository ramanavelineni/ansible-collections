# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

import json
import os
import stat

import pytest
import yaml

from ansible_collections.ramanavelineni.semaphoreui.plugins.modules import project_backup

PROJECT = 'bk-fixtures'


def pid(server):
    return server.fixtures['backup_project_get']['body']['id']


@pytest.fixture
def backed_up(server):
    """The project and its backup, as recorded."""
    server.route('GET', '/projects', 'backup_projects')
    server.route('GET', '/project/%d/backup' % pid(server), 'backup_get')
    return server.fixtures['backup_get']['body']


def test_returns_the_backup_and_changes_nothing(server, backed_up, run_module):
    result = run_module(project_backup.main, dict(project=PROJECT))
    assert result['changed'] is False
    assert result['backup'] == backed_up
    assert result['file'] == ''
    assert [r['method'] for r in server.requests if not r['path'].startswith('/auth/')] == ['GET', 'GET', 'GET']


def test_the_recorded_backup_holds_no_secret_and_no_id(server, backed_up):
    # What the documentation says of a backup, checked on what the servers wrote.
    assert backed_up['meta']['name'] == PROJECT
    assert sorted(k['name'] for k in backed_up['keys']) == ['API_KEY', 'None', 'deploy']
    assert all(sorted(k) == ['name', 'owner', 'synchronized', 'type'] for k in backed_up['keys'])
    assert backed_up['repositories'][0]['ssh_key'] == 'deploy'
    text = json.dumps(backed_up)
    assert '"id"' not in text and 'PRIVATE KEY' not in text and 'not-a-real' not in text
    assert ('workflows' in backed_up) is (server.version != '2.18')


def test_by_project_id_reads_no_project_list(server, backed_up, run_module):
    server.route('GET', '/project/%d' % pid(server), 'backup_project_get')
    del server.routes[('GET', '/projects')]
    result = run_module(project_backup.main, dict(project_id=pid(server)))
    assert result['backup'] == backed_up


def test_writes_the_file_once(server, backed_up, run_module, tmp_path):
    dest = str(tmp_path / 'backup.json')
    result = run_module(project_backup.main, dict(project=PROJECT, dest=dest))
    assert result['changed'] is True and result['file'] == dest
    assert result['diff'] == dict(before={}, after=backed_up)
    with open(dest, encoding='utf-8') as f:
        text = f.read()
    assert json.loads(text) == backed_up and text.endswith('}\n')
    assert stat.S_IMODE(os.stat(dest).st_mode) == 0o600
    # Nothing is left next to it.
    assert os.listdir(str(tmp_path)) == ['backup.json']

    again = run_module(project_backup.main, dict(project=PROJECT, dest=dest))
    assert again['changed'] is False
    assert again['diff'] == dict(before=backed_up, after=backed_up)


def test_layout_of_the_file_is_no_difference(server, backed_up, run_module, tmp_path):
    dest = tmp_path / 'backup.json'
    dest.write_text(json.dumps(backed_up))
    os.chmod(str(dest), 0o600)
    assert run_module(project_backup.main, dict(project=PROJECT, dest=str(dest)))['changed'] is False
    assert dest.read_text() == json.dumps(backed_up)


def test_a_file_that_differs_is_replaced(server, backed_up, run_module, tmp_path):
    dest = tmp_path / 'backup.json'
    old = dict(backed_up, meta=dict(backed_up['meta'], max_parallel_tasks=9))
    dest.write_text(json.dumps(old))
    result = run_module(project_backup.main, dict(project=PROJECT, dest=str(dest)))
    assert result['changed'] is True
    assert result['diff']['before'] == old and result['diff']['after'] == backed_up
    assert json.loads(dest.read_text()) == backed_up


def test_a_file_that_is_not_json_is_replaced(server, backed_up, run_module, tmp_path):
    dest = tmp_path / 'backup.json'
    dest.write_text('half a file')
    assert run_module(project_backup.main, dict(project=PROJECT, dest=str(dest)))['changed'] is True
    assert json.loads(dest.read_text()) == backed_up


def test_permissions_are_set(server, backed_up, run_module, tmp_path):
    dest = str(tmp_path / 'backup.json')
    run_module(project_backup.main, dict(project=PROJECT, dest=dest, mode='0640'))
    assert stat.S_IMODE(os.stat(dest).st_mode) == 0o640
    # The same backup with other permissions is a change, of the permissions only.
    before = os.stat(dest).st_mtime_ns
    result = run_module(project_backup.main, dict(project=PROJECT, dest=dest))
    assert result['changed'] is True
    assert stat.S_IMODE(os.stat(dest).st_mode) == 0o600
    assert os.stat(dest).st_mtime_ns == before


def test_check_mode_writes_nothing(server, backed_up, run_module, tmp_path):
    dest = str(tmp_path / 'backup.json')
    result = run_module(project_backup.main, dict(project=PROJECT, dest=dest), check_mode=True)
    assert result['changed'] is True and result['backup'] == backed_up
    assert not os.path.exists(dest)
    run_module(project_backup.main, dict(project=PROJECT, dest=dest))
    os.chmod(dest, 0o644)
    assert run_module(project_backup.main, dict(project=PROJECT, dest=dest), check_mode=True)['changed'] is True
    assert stat.S_IMODE(os.stat(dest).st_mode) == 0o644


@pytest.mark.parametrize('options, said', [
    (dict(mode='rw'), 'mode must be an octal number'),
    (dict(mode='600 '), 'mode must be an octal number'),
    (dict(dest='{dir}'), 'is a directory'),
    (dict(dest='{dir}/missing/backup.json'), 'does not exist on the host this module runs on'),
])
def test_what_cannot_be_written_fails_with_a_message(server, backed_up, run_module, tmp_path, options, said):
    options = dict((k, v.replace('{dir}', str(tmp_path))) for k, v in options.items())
    result = run_module(project_backup.main, dict(dict(project=PROJECT, dest=str(tmp_path / 'b.json')), **options))
    assert result['failed'] is True and said in result['msg']
    assert 'Traceback' not in result['msg'] and 'Unexpected' not in result['msg']


def test_a_directory_that_takes_no_file_fails_with_a_message(server, backed_up, run_module, tmp_path):
    if os.geteuid() == 0:
        pytest.skip('root writes anywhere')
    os.chmod(str(tmp_path), 0o500)
    try:
        result = run_module(project_backup.main, dict(project=PROJECT, dest=str(tmp_path / 'backup.json')))
    finally:
        os.chmod(str(tmp_path), 0o700)
    assert result['failed'] is True and 'Cannot write dest' in result['msg']


def test_missing_project_fails_in_check_mode_too(server, run_module):
    server.route('GET', '/projects', 'backup_projects')
    for check_mode in (False, True):
        result = run_module(project_backup.main, dict(project='no-such-project'), check_mode=check_mode)
        assert result['failed'] is True and "Project 'no-such-project' does not exist" in result['msg']


def test_an_answer_that_is_no_backup_fails(server, backed_up, run_module):
    # Hand-written: no server was seen to answer this.
    server.route('GET', '/project/%d/backup' % pid(server), dict(status=200, body=[]))
    result = run_module(project_backup.main, dict(project=PROJECT))
    assert result['failed'] is True and 'did not return a backup' in result['msg']


def test_one_of_project_and_project_id(server, run_module):
    assert 'one of the following is required: project, project_id' in run_module(project_backup.main, {})['msg']
    both = run_module(project_backup.main, dict(project=PROJECT, project_id=1))
    assert 'mutually exclusive' in both['msg']
    assert server.requests == []


@pytest.mark.parametrize('check_mode', [False, True], ids=['real', 'check'])
def test_result_has_the_documented_keys(server, backed_up, run_module, tmp_path, check_mode):
    result = run_module(project_backup.main, dict(project=PROJECT, dest=str(tmp_path / 'b.json')), check_mode=check_mode)
    assert set(result) - set(['changed', 'diff', 'invocation', 'warnings', 'deprecations']) == set(yaml.safe_load(project_backup.RETURN))
