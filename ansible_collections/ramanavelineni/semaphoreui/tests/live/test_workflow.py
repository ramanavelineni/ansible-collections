# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""Workflows on a real server: build one, change it, run it through an approval, fail, stop, delete.

Needs a server with workflows (features.workflows in /info): the official
2.19 images, or 2.20. On a server without them only the first test runs, and
checks that every workflow module fails clearly. The templates are the task
suite's: bash scripts that need nothing from outside the container (see
test_task.py).
"""

import pytest

from ansible_collections.ramanavelineni.semaphoreui.plugins.modules import (
    inventory,
    key_store,
    project,
    repository,
    template,
    variable_group,
    workflow,
    workflow_approval,
    workflow_info,
    workflow_run,
)

PROJECT = 'live-workflow'
SLOW_SECONDS = 20
FAST = dict(project=PROJECT, poll_interval=1)

NODES = [
    dict(key='build', template='live-ok', task_params=dict(task_message='from the workflow')),
    dict(key='sign-off', kind='approval', approval_message='Go on?', approval_timeout=3600),
    dict(key='deploy', template='live-next'),
]
EDGES = [
    dict(source='build', destination='sign-off', condition='on_success'),
    dict(source='sign-off', destination='deploy', condition='on_success'),
]


def has_workflows(sem):
    return bool((sem.api.get('/info').get('features') or {}).get('workflows'))


@pytest.fixture(scope='module')
def built(sem):
    if not has_workflows(sem):
        pytest.skip('this server has no workflows')
    sem.ok(project, name=PROJECT)
    sem.ok(key_store, project=PROJECT, name='live-none', type='none')
    sem.ok(repository, project=PROJECT, name='live-local', git_url='/dev', git_branch='', ssh_key='live-none')
    sem.ok(inventory, project=PROJECT, name='live-inventory', type='static', inventory='localhost', ssh_key='live-none')
    sem.ok(variable_group, project=PROJECT, name='live-plain')
    sem.ok(variable_group, project=PROJECT, name='live-slow', env=dict(BASH_ENV='$(sleep %d)' % SLOW_SECONDS))
    common = dict(project=PROJECT, app='bash', playbook='null', repository='live-local', inventory='live-inventory')
    for name in ('live-ok', 'live-next'):
        sem.ok(template, name=name, variable_groups=['live-plain'], **common)
    sem.ok(template, name='live-slow', variable_groups=['live-slow'], **common)
    sem.ok(template, name='live-surveyed', variable_groups=['live-plain'],
           survey_vars=[dict(name='release', title='Release')], **common)
    sem.ok(template, name='live-fail', variable_groups=['live-plain'], **dict(common, playbook='live-missing.sh'))
    yield sem
    # The workflows go first: a build of 2.20 has refused to delete a project
    # whose workflows had runs (409), which left it for the next round.
    for found in sem.ok(workflow_info, project=PROJECT)['workflows']:
        sem.ok(workflow, project=PROJECT, name=found['name'], state='absent')


def test_a_server_without_workflows_fails_clearly(sem):
    if has_workflows(sem):
        pytest.skip('this server has workflows')
    sem.ok(project, name=PROJECT)
    for module, args in ((workflow, dict(name='wf', nodes=NODES)), (workflow_info, {}),
                         (workflow_run, dict(workflow='wf')),
                         (workflow_approval, dict(workflow='wf', run_id=1, decision='approved'))):
        result = sem.run(module, project=PROJECT, **args)
        assert result.get('failed') and 'has no workflows' in result['msg'], (module.__name__, result.get('msg'))


def test_create_then_the_same_graph_twice_is_no_change(built):
    created = built.ok(workflow, project=PROJECT, name='live-release', nodes=NODES, edges=EDGES)
    assert created['changed'] is True
    assert [n['key'] for n in created['workflow']['nodes']] == ['build', 'sign-off', 'deploy']
    assert built.ok(workflow, project=PROJECT, name='live-release', nodes=NODES, edges=EDGES)['changed'] is False
    renamed = [dict(NODES[2], key='c'), dict(NODES[0], key='a'), dict(NODES[1], key='b')]
    edges = [dict(source='a', destination='b', condition='on_success'), dict(source='b', destination='c')]
    assert built.ok(workflow, project=PROJECT, name='live-release', nodes=renamed, edges=edges)['changed'] is False


def test_check_mode_creates_nothing(built):
    result = built.ok(workflow, check_mode=True, project=PROJECT, name='live-planned', nodes=NODES, edges=EDGES)
    assert result['changed'] is True
    assert built.ok(workflow_info, project=PROJECT, name='live-planned')['workflows'] == []


def test_an_added_node_is_saved_once_and_the_stored_positions_stay(built):
    built.ok(workflow, project=PROJECT, name='live-grow', nodes=NODES, edges=EDGES)
    before = built.ok(workflow_info, project=PROJECT, name='live-grow')['workflows'][0]
    nodes = NODES + [dict(key='cleanup', template='live-fail')]
    edges = EDGES + [dict(source='build', destination='cleanup', condition='on_failure')]
    assert built.ok(workflow, project=PROJECT, name='live-grow', nodes=nodes, edges=edges)['changed'] is True
    second = built.ok(workflow, project=PROJECT, name='live-grow', nodes=nodes, edges=edges)
    assert second['changed'] is False
    after = second['workflow']
    assert [(n['position_x'], n['position_y']) for n in after['nodes'][:3]] == \
        [(n['position_x'], n['position_y']) for n in before['nodes']]
    assert sorted((e['source'], e['destination'], e['condition']) for e in after['edges']) == [
        ('build', 'cleanup', 'on_failure'), ('build', 'sign-off', 'on_success'), ('sign-off', 'deploy', 'on_success')]


def test_a_description_change_keeps_the_graph(built):
    built.ok(workflow, project=PROJECT, name='live-described', nodes=NODES, edges=EDGES)
    assert built.ok(workflow, project=PROJECT, name='live-described', description='now described')['changed'] is True
    again = built.ok(workflow, project=PROJECT, name='live-described', description='now described', nodes=NODES,
                     edges=EDGES)
    assert again['changed'] is False
    assert again['workflow']['description'] == 'now described'


def test_a_run_waits_at_the_approval_and_ends_after_it(built):
    built.ok(workflow, project=PROJECT, name='live-release', nodes=NODES, edges=EDGES)
    started = built.ok(workflow_run, workflow='live-release', **FAST)
    run = started['run']
    assert (started['changed'], run['status'], len(run['pending_approvals'])) == (True, 'approval', 1)
    decision = dict(project=PROJECT, workflow='live-release', run_id=run['id'])
    approved = built.ok(workflow_approval, decision='approved', **decision)
    assert (approved['changed'], approved['approval']['status']) == (True, 'approved')
    assert built.ok(workflow_approval, decision='approved', **decision)['changed'] is False
    refused = built.run(workflow_approval, decision='rejected', **decision)
    assert refused.get('failed') and 'already approved' in refused['msg']
    ended = built.ok(workflow_run, workflow='live-release', run_id=run['id'], **FAST)
    assert (ended['changed'], ended['run']['status'], ended['run']['finished']) == (False, 'success', True)


def test_a_failed_run_fails_the_module(built):
    built.ok(workflow, project=PROJECT, name='live-broken', nodes=[dict(key='only', template='live-fail')])
    result = built.run(workflow_run, workflow='live-broken', **FAST)
    assert result.get('failed') and 'live-fail' in result['msg']
    assert result['run']['status'] == 'failed'


def test_a_running_run_is_stopped(built):
    built.ok(workflow, project=PROJECT, name='live-slow', nodes=[dict(key='only', template='live-slow')])
    started = built.ok(workflow_run, workflow='live-slow', wait=False, **FAST)['run']
    stopped = built.ok(workflow_run, workflow='live-slow', state='stopped', run_id=started['id'], **FAST)
    assert (stopped['changed'], stopped['run']['status']) == (True, 'stopped')
    again = built.ok(workflow_run, workflow='live-slow', state='stopped', run_id=started['id'], **FAST)
    assert again['changed'] is False


def test_what_only_2_20_stores(built):
    nodes = [dict(key='wait', kind='delay', delay_seconds=1), dict(key='go', template='live-ok')]
    edges = [dict(source='wait', destination='go', condition='on_success')]
    if not built.at_least(20):
        result = built.run(workflow, project=PROJECT, name='live-newer', nodes=nodes, edges=edges)
        assert result.get('failed') and 'needs 2.20' in result['msg']
        return
    survey = [dict(name='release', title='Release', default_value='1.0')]
    nodes[1] = dict(key='go', template='live-surveyed', survey_inputs=[dict(var='release', workflow_var='release')])
    created = built.ok(workflow, project=PROJECT, name='live-newer', nodes=nodes, edges=edges, survey_vars=survey)
    assert created['changed'] is True
    again = built.ok(workflow, project=PROJECT, name='live-newer', nodes=nodes, edges=edges, survey_vars=survey)
    assert again['changed'] is False
    run = built.ok(workflow_run, workflow='live-newer', variables=dict(release='2.0'), **FAST)['run']
    assert (run['status'], run['variables']) == ('success', dict(release='2.0'))


def test_delete_then_delete_again_is_no_change(built):
    built.ok(workflow, project=PROJECT, name='live-gone', nodes=NODES, edges=EDGES)
    assert built.ok(workflow, project=PROJECT, name='live-gone', state='absent')['changed'] is True
    assert built.ok(workflow, project=PROJECT, name='live-gone', state='absent')['changed'] is False
    assert built.ok(workflow_info, project=PROJECT, name='live-gone')['workflows'] == []
