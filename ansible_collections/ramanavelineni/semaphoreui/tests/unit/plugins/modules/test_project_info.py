# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

from ansible_collections.ramanavelineni.semaphoreui.plugins.modules import project_info


def test_lists_all(server, run_module):
    server.route('GET', '/projects', 'projects_one_updated')
    result = run_module(project_info.main, {})
    assert result['changed'] is False
    assert [p['name'] for p in result['projects']] == ['homelab']


def test_filters_by_name(server, run_module):
    server.route('GET', '/projects', 'projects_one_updated')
    assert run_module(project_info.main, dict(name='other'))['projects'] == []
    assert len(run_module(project_info.main, dict(name='homelab'))['projects']) == 1


def test_empty(server, run_module):
    server.route('GET', '/projects', 'projects_empty')
    assert run_module(project_info.main, {})['projects'] == []
