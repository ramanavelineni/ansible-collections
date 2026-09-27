# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

import pytest

from ansible_collections.ramanavelineni.semaphoreui.plugins.modules import key_store_info, repository_info


@pytest.fixture
def project(server):
    server.route('GET', '/projects', 'projects_one')
    base = '/project/%d' % server.fixtures['projects_one']['body'][0]['id']
    server.route('GET', base + '/keys', 'keys_with_deploy')
    server.route('GET', base + '/repositories', 'repositories_one')
    return base


def test_key_store_info(server, project, run_module):
    result = run_module(key_store_info.main, dict(project='homelab'))
    assert result['changed'] is False
    names = [k['name'] for k in result['key_store']]
    assert names == sorted(names) and 'None' in names and 'deploy' in names
    deploy = [k for k in result['key_store'] if k['name'] == 'deploy'][0]
    assert deploy['type'] == 'ssh'
    assert deploy['repositories'] == ['ansible']
    assert set(deploy) == set(['id', 'name', 'type', 'project_id', 'repositories'])


def test_key_store_info_by_name(server, project, run_module):
    result = run_module(key_store_info.main, dict(project='homelab', name='None'))
    assert [k['name'] for k in result['key_store']] == ['None']


def test_repository_info(server, project, run_module):
    result = run_module(repository_info.main, dict(project='homelab'))
    assert [r['name'] for r in result['repositories']] == ['ansible']
    assert result['repositories'][0]['ssh_key'] == 'deploy'


def test_repository_info_by_name(server, project, run_module):
    assert run_module(repository_info.main, dict(project='homelab', name='other'))['repositories'] == []
