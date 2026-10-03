# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

import json

import pytest

from ansible_collections.ramanavelineni.semaphoreui.plugins.modules import key_store

PRIVATE_KEY = '-----BEGIN OPENSSH PRIVATE KEY-----\nunit-test\n-----END OPENSSH PRIVATE KEY-----'
SSH = dict(project='homelab', name='deploy', type='ssh', ssh=dict(login='git', private_key=PRIVATE_KEY))


@pytest.fixture
def project(server):
    """Routes for the project lookup; returns the key API base path."""
    server.route('GET', '/projects', 'projects_one')
    base = '/project/%d' % server.fixtures['projects_one']['body'][0]['id']
    server.route('GET', base + '/repositories', 'repositories_empty')
    return base


def key_id(server):
    return server.fixtures['key_create']['body']['id']


def test_create_ssh_key(server, project, run_module):
    server.route('GET', project + '/keys', 'keys_new_project')
    server.route('POST', project + '/keys', 'key_create')
    result = run_module(key_store.main, SSH)

    assert result['changed'] is True
    assert result['secret_updated'] is True
    assert result['key']['id'] == key_id(server)
    assert result['key']['type'] == 'ssh'
    body = server.calls('POST', project + '/keys')[0]['body']
    assert body == dict(project_id=int(project.split('/')[-1]), name='deploy', type='ssh',
                        ssh=dict(login='git', passphrase='', private_key=PRIVATE_KEY))
    assert 'unit-test' not in json.dumps(result)


def test_create_needs_secret(server, project, run_module):
    server.route('GET', project + '/keys', 'keys_new_project')
    result = run_module(key_store.main, dict(project='homelab', name='deploy', type='ssh'))
    assert result['failed'] is True
    assert 'ssh.private_key' in result['msg']
    assert server.calls('POST', project + '/keys') == []


def test_create_none_key_needs_no_secret(server, project, run_module):
    server.route('GET', project + '/keys', 'keys_new_project')
    server.route('POST', project + '/keys', 'key_create')
    result = run_module(key_store.main, dict(project='homelab', name='public', type='none'))
    assert result['changed'] is True
    assert result['secret_updated'] is False
    assert server.calls('POST', project + '/keys')[0]['body'] == dict(
        project_id=int(project.split('/')[-1]), name='public', type='none')


def test_create_check_mode(server, project, run_module):
    server.route('GET', project + '/keys', 'keys_new_project')
    result = run_module(key_store.main, SSH, check_mode=True)
    assert result['changed'] is True
    assert 'id' not in result['key']
    assert server.calls('POST', project + '/keys') == []


def test_always_resends_secret(server, project, run_module):
    server.route('GET', project + '/keys', 'keys_with_deploy')
    server.route('PUT', '%s/keys/%d' % (project, key_id(server)), 'key_update')
    result = run_module(key_store.main, SSH)
    assert result['changed'] is True
    assert result['secret_updated'] is True
    body = server.calls('PUT')[0]['body']
    # Without override_secret the server ignores the secret; id and
    # project_id must be in the body.
    assert body['override_secret'] is True
    assert body['id'] == key_id(server)
    assert body['project_id'] == int(project.split('/')[-1])
    assert body['ssh']['private_key'] == PRIVATE_KEY


def test_on_create_leaves_existing_secret(server, project, run_module):
    server.route('GET', project + '/keys', 'keys_with_deploy')
    result = run_module(key_store.main, dict(SSH, update_secret='on_create'))
    assert result['changed'] is False
    assert result['secret_updated'] is False
    assert server.calls('PUT') == []


def test_existing_key_without_secret_is_left_alone(server, project, run_module):
    server.route('GET', project + '/keys', 'keys_with_deploy')
    result = run_module(key_store.main, dict(project='homelab', name='deploy', type='ssh'))
    assert result['changed'] is False
    assert server.calls('PUT') == []


def test_type_change_in_place(server, project, run_module):
    server.route('GET', project + '/keys', 'keys_with_deploy')
    server.route('PUT', '%s/keys/%d' % (project, key_id(server)), 'key_update')
    result = run_module(key_store.main, dict(project='homelab', name='deploy', type='login_password',
                                             login_password=dict(password='pw'), update_secret='on_create'))
    assert result['changed'] is True
    assert result['diff']['before']['type'] == 'ssh'
    assert result['diff']['after']['type'] == 'login_password'
    assert server.calls('PUT')[0]['body']['login_password'] == dict(login='', password='pw')


def test_type_change_needs_secret(server, project, run_module):
    server.route('GET', project + '/keys', 'keys_with_deploy')
    result = run_module(key_store.main, dict(project='homelab', name='deploy', type='login_password'))
    assert result['failed'] is True
    assert 'needs the secret' in result['msg']


def test_type_change_to_none(server, project, run_module):
    server.route('GET', project + '/keys', 'keys_with_deploy')
    server.route('PUT', '%s/keys/%d' % (project, key_id(server)), 'key_update')
    result = run_module(key_store.main, dict(project='homelab', name='deploy', type='none'))
    assert result['changed'] is True
    assert result['secret_updated'] is False
    assert server.calls('PUT')[0]['body']['type'] == 'none'


def test_repository_key_secret_skipped_with_warning(server, project, run_module):
    server.route('GET', project + '/keys', 'keys_with_deploy')
    server.route('GET', project + '/repositories', 'repositories_one')
    result = run_module(key_store.main, SSH)
    assert result['changed'] is False
    assert result['secret_updated'] is False
    assert result['repositories'] == ['ansible']
    assert 'force_repository_key_update' in json.dumps(result['warnings'])
    assert server.calls('PUT') == []


def test_repository_key_type_change_fails_without_force(server, project, run_module):
    server.route('GET', project + '/keys', 'keys_with_deploy')
    server.route('GET', project + '/repositories', 'repositories_one')
    result = run_module(key_store.main, dict(project='homelab', name='deploy', type='none'))
    assert result['failed'] is True
    assert 'force_repository_key_update' in result['msg']
    assert server.calls('PUT') == []


def test_repository_key_forced(server, project, run_module):
    server.route('GET', project + '/keys', 'keys_with_deploy')
    server.route('GET', project + '/repositories', 'repositories_one')
    server.route('PUT', '%s/keys/%d' % (project, key_id(server)), 'key_update')
    result = run_module(key_store.main, dict(SSH, force_repository_key_update=True))
    assert result['changed'] is True
    assert len(server.calls('PUT')) == 1


def test_rejected_update_is_reported(server, project, run_module):
    server.route('GET', project + '/keys', 'keys_with_deploy')
    server.route('PUT', '%s/keys/%d' % (project, key_id(server)), 'key_update_id_mismatch')
    result = run_module(key_store.main, SSH)
    assert result['failed'] is True
    assert 'Access key id in URL and in body must be the same' in result['msg']
    # json.dumps escapes the key's newlines, so look for a part without any.
    assert 'unit-test' not in json.dumps(result)
    assert result['request_details']['request']['ssh']['private_key'] == '********'
    assert result['request_details']['request']['name'] == 'deploy'


def test_option_for_other_type_fails(server, project, run_module):
    result = run_module(key_store.main, dict(project='homelab', name='deploy', type='none',
                                             ssh=dict(private_key=PRIVATE_KEY)))
    assert result['failed'] is True
    assert 'only valid with type: ssh' in result['msg']


def test_delete(server, project, run_module):
    server.route('GET', project + '/keys', 'keys_with_deploy')
    server.route('GET', '%s/keys/%d/refs' % (project, key_id(server)), 'key_refs_unused')
    server.route('DELETE', '%s/keys/%d' % (project, key_id(server)), 'key_delete')
    result = run_module(key_store.main, dict(project='homelab', name='deploy', state='absent'))
    assert result['changed'] is True
    assert len(server.calls('DELETE')) == 1


def test_delete_in_use_lists_users(server, project, run_module):
    server.route('GET', project + '/keys', 'keys_with_deploy')
    server.route('GET', project + '/repositories', 'repositories_one')
    server.route('GET', '%s/keys/%d/refs' % (project, key_id(server)), 'key_refs_used_by_repository')
    result = run_module(key_store.main, dict(project='homelab', name='deploy', state='absent'))
    assert result['failed'] is True
    assert "still used by repositories ansible" in result['msg']
    assert server.calls('DELETE') == []


def test_delete_missing(server, project, run_module):
    server.route('GET', project + '/keys', 'keys_new_project')
    result = run_module(key_store.main, dict(project='homelab', name='deploy', state='absent'))
    assert result['changed'] is False


def test_unknown_project(server, run_module):
    server.route('GET', '/projects', 'projects_empty')
    result = run_module(key_store.main, dict(project='homelab', name='deploy', type='none'))
    assert result['failed'] is True
    assert "Project 'homelab' does not exist" in result['msg']
