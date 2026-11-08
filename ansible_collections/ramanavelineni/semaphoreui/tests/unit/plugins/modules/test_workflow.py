# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""workflow, workflow_info, workflow_run and workflow_approval, on the responses of the recorder's workflow area.

The area builds wf-release: wf-ok -> approval "Go on?" -> wf-next, all
on_success. An update adds wf-fail after wf-ok on_failure. A run waits at
the approval, is approved and succeeds; one fails; one is stopped while its
task runs. Ids are read from the recordings, since every recording gives out
new ones. Where a test needs an answer that was not recorded, it edits a
recorded one and says so.
"""

import pytest

from ansible_collections.ramanavelineni.semaphoreui.plugins.modules import (
    workflow,
    workflow_approval,
    workflow_info,
    workflow_run,
)

PROJECT = 'fixtures-workflow'

RELEASE_NODES = [
    dict(key='build', template='wf-ok', task_params=dict(task_message='from the workflow')),
    dict(key='sign-off', kind='approval', approval_message='Go on?', approval_timeout=3600),
    dict(key='next', template='wf-next'),
]
RELEASE_EDGES = [
    dict(source='build', destination='sign-off', condition='on_success'),
    dict(source='sign-off', destination='next', condition='on_success'),
]


def body(server, name):
    return server.fixtures[name]['body']


def base(server):
    return '/project/%d' % body(server, 'workflow_projects')[0]['id']


def wid(server):
    return body(server, 'workflow_create')['id']


def wf_path(server, more=''):
    return '%s/workflows/%d%s' % (base(server), wid(server), more)


def template_id(server, name):
    return [t['id'] for t in body(server, 'workflow_templates') if t['name'] == name][0]


def node_ids(server, fixture):
    return [n['id'] for n in body(server, fixture)['nodes']]


@pytest.fixture
def project(workflow_server):
    workflow_server.route('GET', '/projects', 'workflow_projects')
    workflow_server.route('GET', base(workflow_server) + '/templates', 'workflow_templates')
    return workflow_server


@pytest.fixture
def stored(project):
    """wf-release exists as it was created."""
    project.route('GET', base(project) + '/workflows', 'workflow_list')
    project.route('GET', wf_path(project), 'workflow_get')
    return project


def writes(server):
    return [r for r in server.requests if r['method'] != 'GET' and not r['path'].startswith('/auth/')]


def release(**more):
    return dict(dict(project=PROJECT, name='wf-release', nodes=RELEASE_NODES, edges=RELEASE_EDGES), **more)


# -- workflow --------------------------------------------------------------------


def test_a_new_workflow_is_sent_with_numbered_nodes_and_edges_between_the_numbers(project, run_module):
    project.route('GET', base(project) + '/workflows', 'workflow_list_empty')
    project.route('POST', base(project) + '/workflows', 'workflow_create')
    project.route('GET', wf_path(project), 'workflow_get')
    result = run_module(workflow.main, release(description='recorded'))
    assert result['changed'] is True
    sent = project.calls('POST', base(project) + '/workflows')[0]['body']
    assert sent['nodes'] == [
        dict(id=1, kind='task', template_id=template_id(project, 'wf-ok'), position_x=0, position_y=0,
             task_params=dict(message='from the workflow')),
        dict(id=2, kind='approval', approval_message='Go on?', approval_timeout=3600, position_x=300, position_y=0),
        dict(id=3, kind='task', template_id=template_id(project, 'wf-next'), position_x=600, position_y=0),
    ]
    assert sent['edges'] == [dict(source_node_id=1, destination_node_id=2, condition='on_success'),
                             dict(source_node_id=2, destination_node_id=3, condition='on_success')]
    stored_ids = node_ids(project, 'workflow_get')
    assert [(n['key'], n['id']) for n in result['workflow']['nodes']] == list(zip(['build', 'sign-off', 'next'], stored_ids))
    assert result['workflow']['edges'][0]['source'] == 'build'


def test_2_19_gets_no_survey_with_a_new_workflow(project, run_module):
    if project.version >= '2.20':
        pytest.skip('2.20 stores a survey')
    project.route('GET', base(project) + '/workflows', 'workflow_list_empty')
    project.route('POST', base(project) + '/workflows', 'workflow_create')
    project.route('GET', wf_path(project), 'workflow_get')
    run_module(workflow.main, release())
    assert 'survey_vars' not in project.calls('POST', base(project) + '/workflows')[0]['body']


def test_the_stored_graph_declared_again_is_no_change(stored, run_module):
    result = run_module(workflow.main, release(description='recorded'))
    assert result['changed'] is False
    assert writes(stored) == []
    assert [n['key'] for n in result['workflow']['nodes']] == ['build', 'sign-off', 'next']


def test_other_keys_and_another_node_order_are_still_the_stored_graph(stored, run_module):
    nodes = [dict(RELEASE_NODES[2], key='c'), dict(RELEASE_NODES[0], key='a'), dict(RELEASE_NODES[1], key='b')]
    edges = [dict(source='a', destination='b', condition='on_success'), dict(source='b', destination='c')]
    result = run_module(workflow.main, release(nodes=nodes, edges=edges))
    assert result['changed'] is False
    assert writes(stored) == []


def test_an_added_node_saves_the_graph_and_keeps_the_stored_nodes_fields(stored, run_module):
    stored.route('PUT', wf_path(stored), 'workflow_update')
    stored.route('GET', wf_path(stored), 'workflow_get', 'workflow_get_updated')
    nodes = RELEASE_NODES + [dict(key='cleanup', template='wf-fail')]
    edges = RELEASE_EDGES + [dict(source='build', destination='cleanup', condition='on_failure')]
    result = run_module(workflow.main, release(nodes=nodes, edges=edges))
    assert result['changed'] is True
    sent = stored.calls('PUT', wf_path(stored))[0]['body']
    assert [(n['id'], n['kind'], n.get('template_id'), n['position_x'], n['position_y'], n.get('convergence_mode'))
            for n in sent['nodes']] == [
        (1, 'task', template_id(stored, 'wf-ok'), 0, 0, 'all'),
        (2, 'approval', None, 300, 0, 'all'),
        (3, 'task', template_id(stored, 'wf-next'), 600, 0, 'all'),
        (4, 'task', template_id(stored, 'wf-fail'), 300, 150, None),
    ]
    assert sorted((e['source_node_id'], e['destination_node_id'], e['condition']) for e in sent['edges']) == [
        (1, 2, 'on_success'), (1, 4, 'on_failure'), (2, 3, 'on_success')]
    assert sent['name'] == 'wf-release' and 'revision' not in sent
    assert [n['key'] for n in result['workflow']['nodes']] == ['build', 'sign-off', 'next', 'cleanup']
    assert [n['key'] for n in result['diff']['before']['nodes']] == ['node%d' % i for i in node_ids(stored, 'workflow_get')]


def test_check_mode_shows_the_new_graph_and_writes_nothing(stored, run_module):
    nodes = RELEASE_NODES + [dict(key='cleanup', template='wf-fail')]
    edges = RELEASE_EDGES + [dict(source='build', destination='cleanup', condition='on_failure')]
    result = run_module(workflow.main, release(nodes=nodes, edges=edges), check_mode=True)
    assert result['changed'] is True
    assert writes(stored) == []
    assert [(n['key'], n['id'], n['template']) for n in result['workflow']['nodes']][-1] == ('cleanup', None, 'wf-fail')


def test_a_description_change_sends_the_stored_graph_back_renumbered(stored, run_module):
    stored.route('PUT', wf_path(stored), 'workflow_update')
    result = run_module(workflow.main, dict(project=PROJECT, name='wf-release', description='changed'))
    assert result['changed'] is True
    sent = stored.calls('PUT', wf_path(stored))[0]['body']
    assert sent['description'] == 'changed'
    assert [n['id'] for n in sent['nodes']] == [1, 2, 3]
    assert [(e['source_node_id'], e['destination_node_id']) for e in sent['edges']] == [(1, 2), (2, 3)]
    assert all('workflow_template_id' not in n for n in sent['nodes'])


def test_state_absent_deletes_the_workflow(stored, run_module):
    stored.route('DELETE', wf_path(stored), 'workflow_delete')
    result = run_module(workflow.main, dict(project=PROJECT, name='wf-release', state='absent'))
    assert result['changed'] is True
    assert len(stored.calls('DELETE', wf_path(stored))) == 1


def test_state_absent_for_a_missing_workflow_is_no_change(project, run_module):
    project.route('GET', base(project) + '/workflows', 'workflow_list_empty')
    result = run_module(workflow.main, dict(project=PROJECT, name='wf-release', state='absent'))
    assert result['changed'] is False
    assert writes(project) == []


def test_a_node_with_a_missing_template_fails_before_any_write(stored, run_module):
    nodes = [dict(RELEASE_NODES[0], template='wf-gone')] + RELEASE_NODES[1:]
    result = run_module(workflow.main, release(nodes=nodes))
    assert result['failed'] is True
    assert "Template 'wf-gone' of node 'build' does not exist" in result['msg']
    assert writes(stored) == []


def test_empty_nodes_fail_before_any_request(workflow_server, run_module):
    # Recorded as noworkflow_create_empty: 2.19 answers such a create with 400 "at least one node".
    result = run_module(workflow.main, dict(project=PROJECT, name='wf-release', nodes=[]))
    assert result['failed'] is True
    assert 'nodes cannot be empty' in result['msg']
    assert [r['path'] for r in workflow_server.requests if not r['path'].startswith('/auth/')] == ['/info']


@pytest.mark.parametrize('nodes, edges, named', [
    ([dict(key='wait', kind='delay', delay_seconds=30)], [], "kind delay (node 'wait')"),
    ([dict(key='a', template='wf-ok', survey_inputs=[dict(var='v', workflow_var='w')])], [], "survey_inputs (node 'a')"),
    ([dict(key='a', template='wf-ok'), dict(key='b', template='wf-next')],
     [dict(source='a', destination='b', input_mode='by_name')], 'input_mode (edge a -> b)'),
])
def test_2_19_refuses_what_only_2_20_stores(stored, run_module, nodes, edges, named):
    if stored.version >= '2.20':
        pytest.skip('2.20 stores it')
    result = run_module(workflow.main, release(nodes=nodes, edges=edges))
    assert result['failed'] is True
    assert named in result['msg'] and 'needs 2.20' in result['msg']
    assert writes(stored) == []


def test_a_server_without_workflows_fails_before_reading_the_project(server, run_module):
    if server.version != '2.18':
        pytest.skip('only 2.18 of the recorded stock servers has no workflows')
    result = run_module(workflow.main, release())
    assert result['failed'] is True
    assert 'has no workflows' in result['msg']
    assert [r['path'] for r in server.requests if not r['path'].startswith('/auth/')] == ['/info']


# -- workflow_info ---------------------------------------------------------------


def test_info_returns_each_workflow_with_its_graph(stored, run_module):
    result = run_module(workflow_info.main, dict(project=PROJECT))
    assert result['changed'] is False
    [found] = result['workflows']
    ids = node_ids(stored, 'workflow_get')
    assert found['name'] == 'wf-release'
    assert [(n['key'], n['kind'], n['template']) for n in found['nodes']] == [
        ('node%d' % ids[0], 'task', 'wf-ok'), ('node%d' % ids[1], 'approval', None), ('node%d' % ids[2], 'task', 'wf-next')]
    assert [(e['source'], e['destination'], e['condition']) for e in found['edges']] == [
        ('node%d' % ids[0], 'node%d' % ids[1], 'on_success'), ('node%d' % ids[1], 'node%d' % ids[2], 'on_success')]


def test_info_with_a_name_nobody_has_returns_nothing(stored, run_module):
    assert run_module(workflow_info.main, dict(project=PROJECT, name='wf-other'))['workflows'] == []


# -- workflow_run ----------------------------------------------------------------


def run_path(server, run_id, more=''):
    return wf_path(server, '/runs/%d%s' % (run_id, more))


def start_path(server):
    return wf_path(server, '/runs' if server.version >= '2.20' else '/run')


def test_a_run_that_reaches_an_approval_is_returned_without_failing(stored, run_module):
    run_id = body(stored, 'workflow_run_start')['id']
    stored.route('POST', start_path(stored), 'workflow_run_start')
    stored.route('GET', run_path(stored, run_id), 'workflow_run_get_approval')
    result = run_module(workflow_run.main, dict(project=PROJECT, workflow='wf-release'))
    assert result.get('failed') is not True
    assert result['changed'] is True
    assert result['run']['status'] == 'approval' and result['run']['finished'] is False
    # 2.20 gives every node an "approval" key, null where there is none; the pending one is the answer.
    approval_node = [n['node']['id'] for n in body(stored, 'workflow_run_get_approval')['nodes']
                     if (n.get('approval') or {}).get('status') == 'pending'][0]
    assert result['run']['pending_approvals'] == [approval_node]


def test_2_19_starts_a_run_without_a_body(stored, run_module):
    if stored.version >= '2.20':
        pytest.skip('2.20 takes the survey answers')
    run_id = body(stored, 'workflow_run_start')['id']
    stored.route('POST', start_path(stored), 'workflow_run_start')
    stored.route('GET', run_path(stored, run_id), 'workflow_run_get_approval')
    run_module(workflow_run.main, dict(project=PROJECT, workflow='wf-release'))
    assert stored.calls('POST', start_path(stored))[0]['body'] is None


def test_variables_on_2_19_fail_before_a_run_starts(stored, run_module):
    if stored.version >= '2.20':
        pytest.skip('2.20 has a workflow survey')
    result = run_module(workflow_run.main, dict(project=PROJECT, workflow='wf-release', variables=dict(release='2')))
    assert result['failed'] is True and 'variables need Semaphore 2.20' in result['msg']
    assert writes(stored) == []


def test_waiting_for_a_run_by_id_is_no_change_and_ends_with_its_result(stored, run_module):
    run_id = body(stored, 'workflow_run_start')['id']
    # The recorded running answer is of another run (the slow one); its id doesn't matter here.
    stored.route('GET', run_path(stored, run_id), 'workflow_run_get_running', 'workflow_run_get_success')
    result = run_module(workflow_run.main, dict(project=PROJECT, workflow='wf-release', run_id=run_id))
    assert result['changed'] is False
    assert result['run']['status'] == 'success' and result['run']['finished'] is True
    assert writes(stored) == []


def test_a_failed_run_fails_and_names_the_failed_task(stored, run_module):
    run_id = body(stored, 'workflow_run_start_failing')['id']
    stored.route('POST', start_path(stored), 'workflow_run_start_failing')
    stored.route('GET', run_path(stored, run_id), 'workflow_run_get_failed')
    result = run_module(workflow_run.main, dict(project=PROJECT, workflow='wf-release'))
    assert result['failed'] is True
    assert 'failed' in result['msg'] and 'wf-fail' in result['msg']
    assert result['run']['status'] == 'failed'


def test_a_run_still_going_after_wait_timeout_fails_and_is_left_running(stored, run_module):
    run_id = body(stored, 'workflow_run_start_slow')['id']
    stored.route('POST', start_path(stored), 'workflow_run_start_slow')
    stored.route('GET', run_path(stored, run_id), 'workflow_run_get_running')
    result = run_module(workflow_run.main, dict(project=PROJECT, workflow='wf-release', wait_timeout=10, poll_interval=5))
    assert result['failed'] is True and 'still running after 10 seconds' in result['msg']
    assert stored.calls('POST', run_path(stored, run_id, '/stop')) == []


def test_stop_on_timeout_asks_semaphore_to_stop_the_run(stored, run_module):
    run_id = body(stored, 'workflow_run_start_slow')['id']
    stored.route('POST', start_path(stored), 'workflow_run_start_slow')
    stored.route('GET', run_path(stored, run_id), 'workflow_run_get_running')
    stored.route('POST', run_path(stored, run_id, '/stop'), 'workflow_run_stop')
    result = run_module(workflow_run.main, dict(project=PROJECT, workflow='wf-release', wait_timeout=5,
                                                poll_interval=5, stop_on_timeout=True))
    assert result['failed'] is True
    assert len(stored.calls('POST', run_path(stored, run_id, '/stop'))) == 1


def test_stopping_a_running_run(stored, run_module):
    run_id = body(stored, 'workflow_run_start_slow')['id']
    stored.route('GET', run_path(stored, run_id), 'workflow_run_get_running', 'workflow_run_get_stopped')
    stored.route('POST', run_path(stored, run_id, '/stop'), 'workflow_run_stop')
    result = run_module(workflow_run.main, dict(project=PROJECT, workflow='wf-release', state='stopped', run_id=run_id))
    assert result['changed'] is True and result.get('failed') is not True
    assert result['run']['status'] == 'stopped'
    assert len(stored.calls('POST', run_path(stored, run_id, '/stop'))) == 1


def test_stopping_a_run_that_is_over_sends_nothing(stored, run_module):
    run_id = body(stored, 'workflow_run_start')['id']
    stored.route('GET', run_path(stored, run_id), 'workflow_run_get_success')
    result = run_module(workflow_run.main, dict(project=PROJECT, workflow='wf-release', state='stopped', run_id=run_id))
    assert result['changed'] is False
    assert writes(stored) == []


def test_a_run_id_the_workflow_does_not_have_fails(stored, run_module):
    stored.route('GET', run_path(stored, 999999), 'workflow_run_get_missing')
    result = run_module(workflow_run.main, dict(project=PROJECT, workflow='wf-release', run_id=999999))
    assert result['failed'] is True and 'has no run 999999' in result['msg']


def test_running_a_missing_workflow_fails(project, run_module):
    project.route('GET', base(project) + '/workflows', 'workflow_list_empty')
    result = run_module(workflow_run.main, dict(project=PROJECT, workflow='wf-release'))
    assert result['failed'] is True and "Workflow 'wf-release' does not exist" in result['msg']


# -- workflow_approval -----------------------------------------------------------


@pytest.fixture
def waiting(stored):
    """Run of the approval scenario, waiting at its approval node."""
    run_id = body(stored, 'workflow_run_start')['id']
    stored.route('GET', run_path(stored, run_id), 'workflow_run_get_approval')
    stored.route('GET', run_path(stored, run_id, '/approvals'), 'workflow_approvals_pending')
    stored.route('POST', run_path(stored, run_id, '/approvals/%d' % approval_node(stored)), 'workflow_approve')
    return stored


def approval_node(server):
    return body(server, 'workflow_approvals_pending')[0]['workflow_node_id']


def test_the_one_pending_approval_is_approved(waiting, run_module):
    run_id = body(waiting, 'workflow_run_start')['id']
    result = run_module(workflow_approval.main, dict(project=PROJECT, workflow='wf-release', run_id=run_id,
                                                     decision='approved'))
    assert result['changed'] is True
    [sent] = waiting.calls('POST', run_path(waiting, run_id, '/approvals/%d' % approval_node(waiting)))
    assert sent['body'] == dict(status='approved')
    assert result['approval']['status'] == 'approved' and result['approval']['node_id'] == approval_node(waiting)


def test_check_mode_approves_nothing(waiting, run_module):
    run_id = body(waiting, 'workflow_run_start')['id']
    result = run_module(workflow_approval.main, dict(project=PROJECT, workflow='wf-release', run_id=run_id,
                                                     decision='approved'), check_mode=True)
    assert result['changed'] is True and result['approval']['status'] == 'approved'
    assert writes(waiting) == []


def test_the_same_decision_again_is_no_change(waiting, run_module):
    run_id = body(waiting, 'workflow_run_start')['id']
    waiting.route('GET', run_path(waiting, run_id, '/approvals'), 'workflow_approvals_resolved')
    result = run_module(workflow_approval.main, dict(project=PROJECT, workflow='wf-release', run_id=run_id,
                                                     decision='approved'))
    assert result['changed'] is False
    assert writes(waiting) == []


def test_the_other_decision_after_one_was_given_fails(waiting, run_module):
    # Semaphore itself answers 400 "approval has already been resolved" (workflow_approve_again).
    run_id = body(waiting, 'workflow_run_start')['id']
    waiting.route('GET', run_path(waiting, run_id, '/approvals'), 'workflow_approvals_resolved')
    result = run_module(workflow_approval.main, dict(project=PROJECT, workflow='wf-release', run_id=run_id,
                                                     decision='rejected'))
    assert result['failed'] is True and 'already approved' in result['msg']
    assert writes(waiting) == []


def test_several_pending_approvals_need_node_id(waiting, run_module):
    run_id = body(waiting, 'workflow_run_start')['id']
    # Hand-edited: the recorded run waits at one approval; here a second one waits too.
    listing = waiting.response('workflow_approvals_pending')
    listing['body'].append(dict(listing['body'][0], id=99, workflow_node_id=4242))
    waiting.route('GET', run_path(waiting, run_id, '/approvals'), listing)
    result = run_module(workflow_approval.main, dict(project=PROJECT, workflow='wf-release', run_id=run_id,
                                                     decision='approved'))
    assert result['failed'] is True
    assert 'more than one approval' in result['msg'] and '4242' in result['msg']
    assert writes(waiting) == []
