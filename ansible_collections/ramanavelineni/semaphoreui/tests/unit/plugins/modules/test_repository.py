# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

import pytest

from ansible_collections.ramanavelineni.semaphoreui.plugins.modules import repository

REPO = dict(project='homelab', name='ansible', git_url='git@github.com:example/ansible.git',
            git_branch='main', ssh_key='deploy')


@pytest.fixture
def project(server):
    server.route('GET', '/projects', 'projects_one')
    base = '/project/%d' % server.fixtures['projects_one']['body'][0]['id']
    server.route('GET', base + '/keys', 'keys_with_deploy')
    return base


def ids(server):
    return server.fixtures['repository_create']['body']['id'], server.fixtures['key_create']['body']['id']


def test_create(server, project, run_module):
    server.route('GET', project + '/repositories', 'repositories_empty')
    server.route('POST', project + '/repositories', 'repository_create')
    result = run_module(repository.main, REPO)
    repo_id, key_id = ids(server)

    assert result['changed'] is True
    assert result['repository']['id'] == repo_id
    assert result['repository']['ssh_key'] == 'deploy'
    assert server.calls('POST', project + '/repositories')[0]['body'] == dict(
        project_id=int(project.split('/')[-1]), name='ansible', git_url=REPO['git_url'],
        git_branch='main', ssh_key_id=key_id)


def test_create_needs_url_branch_and_key(server, project, run_module):
    server.route('GET', project + '/repositories', 'repositories_empty')
    result = run_module(repository.main, dict(project='homelab', name='ansible', git_url=REPO['git_url']))
    assert result['failed'] is True
    assert 'ssh_key' in result['msg'] and 'git_branch' in result['msg']


def test_local_path_needs_no_branch(server, project, run_module):
    server.route('GET', project + '/repositories', 'repositories_empty')
    server.route('POST', project + '/repositories', 'repository_create')
    result = run_module(repository.main, dict(project='homelab', name='local', git_url='/srv/playbooks', ssh_key='None'))
    assert result['changed'] is True
    assert server.calls('POST', project + '/repositories')[0]['body']['git_branch'] == ''


def test_unknown_key(server, project, run_module):
    server.route('GET', project + '/repositories', 'repositories_empty')
    result = run_module(repository.main, dict(REPO, ssh_key='missing'))
    assert result['failed'] is True
    assert "Key 'missing' does not exist" in result['msg']


def test_create_check_mode(server, project, run_module):
    server.route('GET', project + '/repositories', 'repositories_empty')
    result = run_module(repository.main, REPO, check_mode=True)
    assert result['changed'] is True
    assert 'id' not in result['repository']
    assert server.calls('POST', project + '/repositories') == []


def test_no_change(server, project, run_module):
    server.route('GET', project + '/repositories', 'repositories_one')
    result = run_module(repository.main, REPO)
    assert result['changed'] is False
    assert server.calls('PUT') == []


def test_update_sends_whole_object(server, project, run_module):
    repo_id, key_id = ids(server)
    server.route('GET', project + '/repositories', 'repositories_one')
    server.route('PUT', '%s/repositories/%d' % (project, repo_id), 'repository_update')
    result = run_module(repository.main, dict(project='homelab', name='ansible', git_branch='develop'))
    assert result['changed'] is True
    assert result['diff']['before']['git_branch'] == 'main'
    assert server.calls('PUT')[0]['body'] == dict(
        id=repo_id, project_id=int(project.split('/')[-1]), name='ansible',
        git_url=REPO['git_url'], git_branch='develop', ssh_key_id=key_id)


def test_update_check_mode(server, project, run_module):
    server.route('GET', project + '/repositories', 'repositories_one')
    result = run_module(repository.main, dict(project='homelab', name='ansible', git_branch='develop'), check_mode=True)
    assert result['changed'] is True
    assert result['repository']['git_branch'] == 'develop'
    assert server.calls('PUT') == []


def test_delete(server, project, run_module):
    repo_id, dummy = ids(server)
    server.route('GET', project + '/repositories', 'repositories_one')
    server.route('GET', '%s/repositories/%d/refs' % (project, repo_id), 'repository_refs_unused')
    server.route('DELETE', '%s/repositories/%d' % (project, repo_id), 'repository_delete')
    stored = run_module(repository.main, dict(project='homelab', name='ansible'))['repository']
    result = run_module(repository.main, dict(project='homelab', name='ansible', state='absent'))
    assert result['changed'] is True
    assert len(server.calls('DELETE')) == 1
    # The diff shows what is deleted, in the shape an update shows it: with the key's name.
    assert result['diff'] == dict(before=stored, after={})
    assert stored['ssh_key'] == 'deploy' and stored['git_url']


def test_delete_in_use_lists_users(server, project, run_module):
    repo_id, dummy = ids(server)
    refs = server.response('repository_refs_unused')
    refs['body']['templates'] = [dict(id=3, name='deploy-site')]
    server.route('GET', project + '/repositories', 'repositories_one')
    server.route('GET', '%s/repositories/%d/refs' % (project, repo_id), refs)
    result = run_module(repository.main, dict(project='homelab', name='ansible', state='absent'))
    assert result['failed'] is True
    assert 'still used by templates deploy-site' in result['msg']
    assert server.calls('DELETE') == []


def test_delete_missing(server, project, run_module):
    server.route('GET', project + '/repositories', 'repositories_empty')
    result = run_module(repository.main, dict(project='homelab', name='ansible', state='absent'))
    assert result['changed'] is False
