# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

import json

import pytest

from ansible_collections.ramanavelineni.semaphoreui.plugins.modules import template

SITE = dict(project='homelab', name='site', playbook='site.yml', repository='ansible', inventory='homelab',
            variable_groups=['empty'], view='k8s', arguments=['-v'], task_params=dict(limit=['web']),
            survey_vars=[dict(name='host', title='Host')], vaults=[dict(key='deploy')])


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


def tid(server, fixture='template_create'):
    return server.fixtures[fixture]['body']['id']


def existing(server, project, get='template_get', listing='templates_one'):
    server.route('GET', project + '/templates', listing)
    server.route('GET', '%s/templates/%d' % (project, tid(server)), get)
    server.route('PUT', '%s/templates/%d' % (project, tid(server)), 'template_update')


def test_create(server, project, run_module):
    server.route('GET', project + '/templates', 'templates_empty')
    server.route('POST', project + '/templates', 'template_create')
    result = run_module(template.main, SITE)
    assert result['changed'] is True
    assert result['template']['id'] == tid(server)
    body = server.calls('POST', project + '/templates')[0]['body']
    f = server.fixtures
    assert body['repository_id'] == f['repository_create']['body']['id']
    assert body['inventory_id'] == f['inventory_create']['body']['id']
    assert body['view_id'] == f['view_create']['body']['id']
    assert body['environment_ids'] == [body['environment_id']]
    assert body['arguments'] == '["-v"]'
    assert body['type'] == ''
    assert body['survey_vars'] == [dict(name='host', title='Host', type='', required=False, description='',
                                        default_value='')]
    assert body['vaults'] == [dict(id=0, name='default', type='password', vault_key_id=f['key_create']['body']['id'],
                                   script=None)]


def test_create_needs_references(server, project, run_module):
    server.route('GET', project + '/templates', 'templates_empty')
    result = run_module(template.main, dict(project='homelab', name='site', playbook='site.yml'))
    assert result['failed'] is True
    assert 'repository, variable_groups, inventory' in result['msg']


def test_create_check_mode(server, project, run_module):
    server.route('GET', project + '/templates', 'templates_empty')
    result = run_module(template.main, SITE, check_mode=True)
    assert result['changed'] is True
    assert server.calls('POST', project + '/templates') == []


def test_unknown_task_param_fails(server, project, run_module):
    server.route('GET', project + '/templates', 'templates_empty')
    result = run_module(template.main, dict(SITE, task_params=dict(auto_approve=True)))
    assert result['failed'] is True
    assert 'auto_approve' in result['msg'] and 'app ansible' in result['msg']


def test_no_change(server, project, run_module):
    existing(server, project)
    result = run_module(template.main, SITE)
    assert result['changed'] is False
    assert server.calls('PUT') == []


def test_update_keeps_everything_else(server, project, run_module):
    existing(server, project)
    result = run_module(template.main, dict(project='homelab', name='site', description='updated'))
    assert result['changed'] is True
    body = server.calls('PUT')[0]['body']
    current = server.fixtures['template_get']['body']
    for field in ('repository_id', 'inventory_id', 'view_id', 'environment_ids', 'arguments', 'task_params', 'vaults',
                  'survey_vars'):
        assert body[field] == current[field], field
    assert body['description'] == 'updated'
    assert 'permissions' not in body and 'tasks' not in body


def test_task_params_merge(server, project, run_module):
    existing(server, project)
    result = run_module(template.main, dict(project='homelab', name='site', task_params=dict(tags=['x'])))
    assert result['changed'] is True
    assert server.calls('PUT')[0]['body']['task_params'] == dict(limit=['web'], tags=['x'])


def test_vaults_keep_their_ids(server, project, run_module):
    existing(server, project)
    result = run_module(template.main, dict(project='homelab', name='site',
                                            vaults=[dict(key='deploy'), dict(name='extra', key='deploy')]))
    assert result['changed'] is True
    vaults = server.calls('PUT')[0]['body']['vaults']
    current_id = server.fixtures['template_get']['body']['vaults'][0]['id']
    assert [(v['name'], v['id']) for v in vaults] == [('default', current_id), ('extra', 0)]


def test_clear_view(server, project, run_module):
    existing(server, project)
    result = run_module(template.main, dict(project='homelab', name='site', view=''))
    assert result['changed'] is True
    assert server.calls('PUT')[0]['body']['view_id'] is None


def test_workspace_inventory_survives_update(server, project, run_module):
    tofu = server.response('template_create_tofu')
    tofu['status'] = 200  # served as the single read of the template it created
    tofu_id = tofu['body']['id']
    workspace_id = tofu['body']['inventory_id']
    server.route('GET', project + '/templates', 'templates_two')
    server.route('GET', '%s/templates/%d' % (project, tofu_id), tofu)
    server.route('GET', '%s/inventory/%d' % (project, workspace_id), 'inventory_get_workspace')
    server.route('PUT', '%s/templates/%d' % (project, tofu_id), 'template_update')
    result = run_module(template.main, dict(project='homelab', name='infra', description='d'))
    assert result['changed'] is True
    assert result['template']['inventory'] == 'default'
    assert server.calls('PUT')[0]['body']['inventory_id'] == workspace_id


def test_text_survey_needs_2_19(server, project, run_module):
    existing(server, project)
    result = run_module(template.main, dict(project='homelab', name='site',
                                            survey_vars=[dict(name='notes', title='Notes', type='text')]))
    if server.version == '2.18':
        assert result['failed'] is True
        assert 'needs 2.19' in result['msg']
    else:
        assert result['changed'] is True
        assert server.calls('PUT')[0]['body']['survey_vars'][0]['type'] == 'text'


def test_deploy_needs_build_template(server, project, run_module):
    server.route('GET', project + '/templates', 'templates_empty')
    result = run_module(template.main, dict(SITE, name='deploy', type='deploy'))
    assert result['failed'] is True
    assert 'build_template' in result['msg']


def test_rejected_update(server, project, run_module):
    existing(server, project)
    server.route('PUT', '%s/templates/%d' % (project, tid(server)), 'template_update_id_mismatch')
    result = run_module(template.main, dict(project='homelab', name='site', description='x'))
    assert result['failed'] is True
    assert 'template id in URL and in body must be the same' in result['msg']


def test_delete_in_use(server, project, run_module):
    refs = server.response('template_refs_unused')
    refs['body']['schedules'] = [dict(id=1, name='nightly')]
    server.route('GET', project + '/templates', 'templates_one')
    server.route('GET', '%s/templates/%d/refs' % (project, tid(server)), refs)
    result = run_module(template.main, dict(project='homelab', name='site', state='absent'))
    assert result['failed'] is True
    assert 'still used by schedules nightly' in result['msg']


def test_delete(server, project, run_module):
    server.route('GET', project + '/templates', 'templates_one')
    server.route('GET', '%s/templates/%d/refs' % (project, tid(server)), 'template_refs_unused')
    server.route('DELETE', '%s/templates/%d' % (project, tid(server)), 'template_delete')
    result = run_module(template.main, dict(project='homelab', name='site', state='absent'))
    assert result['changed'] is True


def test_result_has_no_secret_or_raw_ids_only(server, project, run_module):
    existing(server, project)
    result = run_module(template.main, dict(project='homelab', name='site'))
    tpl = result['template']
    assert tpl['repository'] == 'ansible' and tpl['inventory'] == 'homelab' and tpl['view'] == 'k8s'
    assert tpl['variable_groups'] == ['empty']
    assert json.dumps(tpl['vaults']) == json.dumps([dict(name='default', type='password', key='deploy', script='')])


def with_stored(server, **fields):
    """Change the recorded template before it is routed (hand-edited: no recorded server stores these)."""
    server.fixtures['template_get']['body'].update(fields)
    return server.fixtures['template_get']['body']


def test_unchanged_survey_vars_go_back_as_stored(server, project, run_module):
    # 2.19 stores `target`; `colour` stands for a field a later version adds.
    stored = with_stored(server, survey_vars=[dict(name='host', title='Host', target='env', colour='red')])
    existing(server, project)
    result = run_module(template.main, dict(project='homelab', name='site', description='updated'))
    assert result['changed'] is True
    assert server.calls('PUT')[0]['body']['survey_vars'] == stored['survey_vars']


def test_changed_survey_var_keeps_unmanaged_fields(server, project, run_module):
    with_stored(server, survey_vars=[dict(name='host', title='Host', target='env', colour='red',
                                          values=[dict(name='a', value='a')]),
                                     dict(name='gone', title='Gone', target='env')])
    existing(server, project)
    result = run_module(template.main, dict(project='homelab', name='site', survey_vars=[
        dict(name='host', title='Target host', required=True), dict(name='new', title='New')]))
    assert result['changed'] is True
    assert server.calls('PUT')[0]['body']['survey_vars'] == [
        dict(name='host', title='Target host', type='', required=True, description='', default_value='',
             target='env', colour='red'),
        dict(name='new', title='New', type='', required=False, description='', default_value=''),
    ]


def test_unknown_survey_type_round_trips(server, project, run_module):
    stored = with_stored(server, survey_vars=[dict(name='host', title='Host', type='secret')])
    existing(server, project)
    result = run_module(template.main, dict(project='homelab', name='site', description='updated'))
    assert result['changed'] is True
    assert result['template']['survey_vars'][0]['type'] == 'secret'
    assert server.calls('PUT')[0]['body']['survey_vars'] == stored['survey_vars']


def test_unknown_template_type_round_trips(server, project, run_module):
    with_stored(server, type='workflow')
    existing(server, project)
    result = run_module(template.main, dict(project='homelab', name='site', description='updated'))
    assert result['changed'] is True
    assert result['template']['type'] == 'workflow'
    assert server.calls('PUT')[0]['body']['type'] == 'workflow'


def test_unchanged_arguments_go_back_as_stored(server, project, run_module):
    with_stored(server, arguments='-v --diff')
    existing(server, project)
    result = run_module(template.main, dict(project='homelab', name='site', description='updated'))
    assert result['changed'] is True
    assert server.calls('PUT')[0]['body']['arguments'] == '-v --diff'


def test_changed_arguments_are_written_as_a_list(server, project, run_module):
    with_stored(server, arguments='-v --diff')
    existing(server, project)
    result = run_module(template.main, dict(project='homelab', name='site', arguments=['-v', '--diff']))
    assert result['changed'] is True
    assert server.calls('PUT')[0]['body']['arguments'] == '["-v", "--diff"]'
