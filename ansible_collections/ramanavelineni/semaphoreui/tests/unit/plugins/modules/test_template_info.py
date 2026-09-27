# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

import pytest

from ansible_collections.ramanavelineni.semaphoreui.plugins.modules import template_info


@pytest.fixture
def project(server):
    server.route('GET', '/projects', 'projects_one')
    base = '/project/%d' % server.fixtures['projects_one']['body'][0]['id']
    server.route('GET', base + '/repositories', 'repositories_one')
    server.route('GET', base + '/inventory', 'inventories_one')
    server.route('GET', base + '/environment', 'variable_groups_for_templates')
    server.route('GET', base + '/views', 'views_two')
    server.route('GET', base + '/keys', 'keys_with_deploy')
    return base


def single(server, fixture):
    answer = server.response(fixture)
    answer['status'] = 200
    return answer


def test_lists_templates_with_vaults(server, project, run_module):
    tid = server.fixtures['template_create']['body']['id']
    server.route('GET', project + '/templates', 'templates_one')
    server.route('GET', '%s/templates/%d' % (project, tid), 'template_get')
    result = run_module(template_info.main, dict(project='homelab'))
    assert result['changed'] is False
    tpl = result['templates'][0]
    assert tpl['name'] == 'site'
    assert tpl['repository'] == 'ansible' and tpl['inventory'] == 'homelab' and tpl['view'] == 'k8s'
    assert tpl['variable_groups'] == ['empty']
    # The list has no vaults; they come from the single read.
    assert tpl['vaults'] == [dict(name='default', type='password', key='deploy', script='')]
    assert tpl['survey_vars'][0]['name'] == 'host'
    assert len(server.calls('GET', '%s/templates/%d' % (project, tid))) == 1


def test_filter_by_name_reads_only_matches(server, project, run_module):
    tofu = server.fixtures['template_create_tofu']['body']
    server.route('GET', project + '/templates', 'templates_two')
    server.route('GET', '%s/templates/%d' % (project, tofu['id']), single(server, 'template_create_tofu'))
    server.route('GET', '%s/inventory/%d' % (project, tofu['inventory_id']), 'inventory_get_workspace')
    result = run_module(template_info.main, dict(project='homelab', name='infra'))
    assert [t['name'] for t in result['templates']] == ['infra']
    # The workspace inventory is hidden from the inventory list but still named.
    assert result['templates'][0]['inventory'] == 'default'
    assert result['templates'][0]['app'] == 'tofu'
    site = server.fixtures['template_create']['body']['id']
    assert server.calls('GET', '%s/templates/%d' % (project, site)) == []


def test_no_templates(server, project, run_module):
    server.route('GET', project + '/templates', 'templates_empty')
    assert run_module(template_info.main, dict(project='homelab'))['templates'] == []
