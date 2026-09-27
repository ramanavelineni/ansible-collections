# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

import pytest

from ansible_collections.ramanavelineni.semaphoreui.plugins.modules import inventory, inventory_info

INV = dict(project='homelab', name='homelab', type='file', inventory='inventories/homelab/hosts',
           repository='ansible', ssh_key='deploy')


@pytest.fixture
def project(server):
    server.route('GET', '/projects', 'projects_one')
    base = '/project/%d' % server.fixtures['projects_one']['body'][0]['id']
    server.route('GET', base + '/keys', 'keys_with_deploy')
    server.route('GET', base + '/repositories', 'repositories_one')
    return base


def ids(server):
    f = server.fixtures
    return f['inventory_create']['body']['id'], f['key_create']['body']['id'], f['repository_create']['body']['id']


def test_create(server, project, run_module):
    server.route('GET', project + '/inventory', 'inventories_empty')
    server.route('POST', project + '/inventory', 'inventory_create')
    inv_id, key_id, repo_id = ids(server)
    result = run_module(inventory.main, INV)
    assert result['changed'] is True
    assert result['inventory']['id'] == inv_id
    assert result['inventory']['repository'] == 'ansible'
    assert result['inventory']['ssh_key'] == 'deploy'
    assert server.calls('POST', project + '/inventory')[0]['body'] == dict(
        project_id=int(project.split('/')[-1]), name='homelab', type='file', inventory=INV['inventory'],
        repository_id=repo_id, ssh_key_id=key_id, become_key_id=None)


def test_create_needs_type_and_inventory(server, project, run_module):
    server.route('GET', project + '/inventory', 'inventories_empty')
    result = run_module(inventory.main, dict(project='homelab', name='homelab'))
    assert result['failed'] is True
    assert 'type, inventory' in result['msg']


def test_create_check_mode(server, project, run_module):
    server.route('GET', project + '/inventory', 'inventories_empty')
    result = run_module(inventory.main, INV, check_mode=True)
    assert result['changed'] is True
    assert server.calls('POST', project + '/inventory') == []


def test_no_change(server, project, run_module):
    server.route('GET', project + '/inventory', 'inventories_one')
    result = run_module(inventory.main, INV)
    assert result['changed'] is False
    assert server.calls('PUT') == []


def test_update_keeps_unmanaged_fields(server, project, run_module):
    inv_id, key_id, repo_id = ids(server)
    server.route('GET', project + '/inventory', 'inventories_one')
    server.route('PUT', '%s/inventory/%d' % (project, inv_id), 'inventory_update')
    result = run_module(inventory.main, dict(project='homelab', name='homelab', become_key='deploy'))
    assert result['changed'] is True
    assert result['diff']['before']['become_key'] is None
    assert result['inventory']['become_key'] == 'deploy'
    body = server.calls('PUT')[0]['body']
    assert body['become_key_id'] == key_id
    assert body['repository_id'] == repo_id
    assert body['inventory'] == INV['inventory']
    assert body['id'] == inv_id


def test_empty_string_clears_reference(server, project, run_module):
    inv_id, dummy, dummy2 = ids(server)
    server.route('GET', project + '/inventory', 'inventories_one_updated')
    server.route('PUT', '%s/inventory/%d' % (project, inv_id), 'inventory_update')
    result = run_module(inventory.main, dict(project='homelab', name='homelab', become_key=''))
    assert result['changed'] is True
    assert server.calls('PUT')[0]['body']['become_key_id'] is None


def test_empty_string_on_unset_reference_is_no_change(server, project, run_module):
    server.route('GET', project + '/inventory', 'inventories_one')
    result = run_module(inventory.main, dict(project='homelab', name='homelab', become_key=''))
    assert result['changed'] is False


def test_absolute_path_update_fails_with_explanation(server, project, run_module):
    listing = server.response('inventories_one')
    listing['body'][0]['inventory'] = '/etc/ansible/hosts'
    listing['body'][0]['repository_id'] = None
    server.route('GET', project + '/inventory', listing)
    result = run_module(inventory.main, dict(project='homelab', name='homelab', become_key='deploy'))
    assert result['failed'] is True
    assert 'outside its working directory' in result['msg']
    assert server.calls('PUT') == []


def test_unknown_repository(server, project, run_module):
    server.route('GET', project + '/inventory', 'inventories_one')
    result = run_module(inventory.main, dict(project='homelab', name='homelab', repository='other'))
    assert result['failed'] is True
    assert "Repository 'other' does not exist" in result['msg']


def test_delete(server, project, run_module):
    inv_id, dummy, dummy2 = ids(server)
    server.route('GET', project + '/inventory', 'inventories_one')
    server.route('GET', '%s/inventory/%d/refs' % (project, inv_id), 'inventory_refs_unused')
    server.route('DELETE', '%s/inventory/%d' % (project, inv_id), 'inventory_delete')
    result = run_module(inventory.main, dict(project='homelab', name='homelab', state='absent'))
    assert result['changed'] is True


def test_delete_in_use(server, project, run_module):
    inv_id, dummy, dummy2 = ids(server)
    refs = server.response('inventory_refs_unused')
    refs['body']['templates'] = [dict(id=1, name='site')]
    server.route('GET', project + '/inventory', 'inventories_one')
    server.route('GET', '%s/inventory/%d/refs' % (project, inv_id), refs)
    result = run_module(inventory.main, dict(project='homelab', name='homelab', state='absent'))
    assert result['failed'] is True
    assert 'still used by templates site' in result['msg']


def test_inventory_info(server, project, run_module):
    server.route('GET', project + '/inventory', 'inventories_one_updated')
    result = run_module(inventory_info.main, dict(project='homelab'))
    inv = result['inventories'][0]
    assert inv['repository'] == 'ansible' and inv['ssh_key'] == 'deploy' and inv['become_key'] == 'deploy'
