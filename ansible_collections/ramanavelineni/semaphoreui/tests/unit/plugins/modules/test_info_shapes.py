# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""An _info module returns each object exactly as its manage module does."""

from ansible_collections.ramanavelineni.semaphoreui.plugins.modules import (
    inventory,
    inventory_info,
    project,
    project_info,
    repository,
    repository_info,
    user,
    user_info,
)


def test_project(server, run_module):
    server.route('GET', '/projects', 'projects_one')
    managed = run_module(project.main, dict(name='homelab'))
    listed = run_module(project_info.main, dict(name='homelab'))
    assert managed['changed'] is False
    assert listed['projects'] == [managed['project']]
    assert set(listed['projects'][0]) == set(['id', 'name', 'alert', 'alert_chat', 'max_parallel_tasks', 'type'])


def test_repository(server, run_module):
    server.route('GET', '/projects', 'projects_one')
    base = '/project/%d' % server.fixtures['projects_one']['body'][0]['id']
    server.route('GET', base + '/keys', 'keys_with_deploy')
    server.route('GET', base + '/repositories', 'repositories_one')
    managed = run_module(repository.main, dict(project='homelab', name='ansible'))
    listed = run_module(repository_info.main, dict(project='homelab', name='ansible'))
    assert managed['changed'] is False
    assert listed['repositories'] == [managed['repository']]


def test_inventory(server, run_module):
    server.route('GET', '/projects', 'projects_one')
    base = '/project/%d' % server.fixtures['projects_one']['body'][0]['id']
    server.route('GET', base + '/keys', 'keys_with_deploy')
    server.route('GET', base + '/repositories', 'repositories_one')
    server.route('GET', base + '/inventory', 'inventories_one')
    name = server.fixtures['inventories_one']['body'][0]['name']
    managed = run_module(inventory.main, dict(project='homelab', name=name))
    listed = run_module(inventory_info.main, dict(project='homelab', name=name))
    assert managed['changed'] is False
    assert listed['inventories'] == [managed['inventory']]


def test_user(server, run_module):
    server.route('GET', '/user', 'user_me')
    server.route('GET', '/users', 'user_list')
    login = server.fixtures['user_me']['body']['username']
    managed = run_module(user.main, dict(login=login))
    listed = run_module(user_info.main, dict(login=login))
    assert managed['changed'] is False
    assert listed['users'] == [managed['user']]
