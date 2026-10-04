# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""task and task_info, on the responses of the recorder's task area.

The area runs real tasks: tk-slow takes a few seconds and was recorded
waiting, running and done; tk-fail fails; one tk-slow task was stopped while
it ran. Where a test needs an answer that was not recorded, it edits a
recorded one in place and says so.
"""

import json
import time

import pytest
import yaml

from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils import task as task_utils
from ansible_collections.ramanavelineni.semaphoreui.plugins.modules import task, task_info

PROJECT = 'fixtures-task'
STANDARD_KEYS = set(['changed', 'diff', 'invocation', 'warnings', 'deprecations'])


def pid(server):
    return server.fixtures['task_projects_list']['body'][0]['id']


def base(server):
    return '/project/%d' % pid(server)


def tid(server, fixture='task_start'):
    return server.fixtures[fixture]['body']['id']


def template_id(server, name):
    return [t['id'] for t in server.fixtures['task_templates']['body'] if t['name'] == name][0]


def task_path(server, fixture='task_start'):
    return '%s/tasks/%d' % (base(server), tid(server, fixture))


def edited(server, fixture, **changes):
    """A recorded response with fields of its body changed: hand-edited, not what a server answered."""
    response = server.response(fixture)
    response['body'].update(changes)
    return response


def with_template(server, name, **changes):
    """The recorded template list with one template changed: hand-edited."""
    listing = server.response('task_templates')
    for tpl in listing['body']:
        if tpl['name'] == name:
            tpl.update(changes)
    server.route('GET', base(server) + '/templates', listing)


@pytest.fixture
def project(server):
    """The project and its templates, as every task of the modules reads them first."""
    server.route('GET', '/projects', 'task_projects_list')
    server.route('GET', base(server) + '/templates', 'task_templates')
    return server


@pytest.fixture
def lifecycle(project):
    """A tk-slow task that is seen waiting, then running, then done."""
    project.route('POST', base(project) + '/tasks', 'task_start')
    project.route('GET', task_path(project), 'task_get_waiting', 'task_get_running', 'task_get_success')
    project.route('GET', task_path(project) + '/output', 'task_output')
    return project


def sleeps():
    return [call.args[0] for call in time.sleep.call_args_list]


def posts(server):
    return [r for r in server.requests if r['method'] == 'POST' and not r['path'].startswith('/auth/')]


# -- task: started -------------------------------------------------------------


def test_start_waits_until_the_task_is_over(lifecycle, run_module):
    result = run_module(task.main, dict(
        project=PROJECT, template='tk-slow', task_message='recorded', variables=dict(who='world'), arguments=['--flag']))
    assert result['changed'] is True
    assert result.get('failed') is not True, result.get('msg')
    ran = result['task']
    assert (ran['id'], ran['status'], ran['finished']) == (tid(lifecycle), 'success', True)
    assert (ran['project'], ran['template'], ran['template_id']) == (PROJECT, 'tk-slow', template_id(lifecycle, 'tk-slow'))
    assert (ran['message'], ran['variables'], ran['arguments']) == ('recorded', dict(who='world'), ['--flag'])
    assert ran['start'] and ran['end']
    assert ran['output'][0] == 'Task tk-slow added to queue'
    # Semaphore stores a line with its line break; the result has none.
    assert ran['output'][1] == "Started task #%d of template 'tk-slow'" % tid(lifecycle)
    assert ran['output'][-1] == 'tk-slow done'
    # What was sent: both JSON values as strings.
    assert posts(lifecycle)[0]['body'] == dict(
        template_id=template_id(lifecycle, 'tk-slow'), message='recorded',
        environment=json.dumps(dict(who='world')), arguments=json.dumps(['--flag']))
    # Read three times (waiting, running, success), with a pause of poll_interval before each.
    assert len(lifecycle.calls('GET', task_path(lifecycle))) == 3
    assert sleeps()[:3] == [5, 5, 5]


def test_poll_interval_is_the_pause_between_reads(lifecycle, run_module):
    run_module(task.main, dict(project=PROJECT, template='tk-slow', poll_interval=2))
    assert sleeps()[:3] == [2, 2, 2]


def test_a_task_that_is_over_at_once_is_not_waited_for(project, run_module):
    project.route('POST', base(project) + '/tasks', edited(project, 'task_start_quick', status='success'))
    project.route('GET', task_path(project, 'task_start_quick') + '/output', 'task_output')
    result = run_module(task.main, dict(project=PROJECT, template='tk-quick'))
    assert result['task']['status'] == 'success'
    assert project.calls('GET', task_path(project, 'task_start_quick')) == []


def test_output_is_read_until_it_stops_growing(lifecycle, run_module):
    short = lifecycle.response('task_output')
    short['body'] = short['body'][:1]
    lifecycle.route('GET', task_path(lifecycle) + '/output', short, 'task_output')
    result = run_module(task.main, dict(project=PROJECT, template='tk-slow'))
    # One line at first, six a moment later, six again: three reads.
    assert len(lifecycle.calls('GET', task_path(lifecycle) + '/output')) == 3
    assert len(result['task']['output']) == len(lifecycle.fixtures['task_output']['body'])
    assert sleeps()[3:] == [task_utils.OUTPUT_SETTLE] * 2


@pytest.mark.parametrize('lines, expected', [(2, ['tk-slow started', 'tk-slow done']), (-1, None), (200, None)])
def test_output_lines_caps_the_output(lifecycle, run_module, lines, expected):
    result = run_module(task.main, dict(project=PROJECT, template='tk-slow', output_lines=lines))
    everything = [o['output'].rstrip('\n') for o in lifecycle.fixtures['task_output']['body']]
    assert result['task']['output'] == (expected or everything)


def test_output_lines_zero_reads_no_output(lifecycle, run_module):
    result = run_module(task.main, dict(project=PROJECT, template='tk-slow', output_lines=0))
    assert result['task']['output'] == []
    assert lifecycle.calls('GET', task_path(lifecycle) + '/output') == []


def test_start_without_waiting(lifecycle, run_module):
    result = run_module(task.main, dict(project=PROJECT, template='tk-slow', wait=False))
    assert result['changed'] is True
    assert (result['task']['id'], result['task']['status'], result['task']['finished']) == (tid(lifecycle), 'waiting', False)
    assert result['task']['output'] == []
    assert lifecycle.calls('GET', task_path(lifecycle)) == []
    assert sleeps() == []


def test_start_in_check_mode_starts_nothing(project, run_module):
    result = run_module(task.main, dict(project=PROJECT, template='tk-slow', task_message='m', variables=dict(a=1),
                                        arguments=['-x'], secret_variables=dict(pw='hunter2-not-real')),
                        check_mode=True)
    assert result['changed'] is True
    assert posts(project) == []
    shown = result['task']
    assert (shown['id'], shown['status'], shown['finished'], shown['template']) == (None, '', False, 'tk-slow')
    assert (shown['message'], shown['variables'], shown['arguments']) == ('m', dict(a=1), ['-x'])
    assert 'hunter2-not-real' not in json.dumps(result)


def test_a_failed_task_fails_the_module(project, run_module):
    project.route('POST', base(project) + '/tasks', 'task_start_failing')
    project.route('GET', task_path(project, 'task_start_failing'), 'task_get_error')
    project.route('GET', task_path(project, 'task_start_failing') + '/output', 'task_output_error')
    result = run_module(task.main, dict(project=PROJECT, template='tk-fail'))
    assert result['failed'] is True
    # It was started, whatever became of it.
    assert result['changed'] is True
    assert result['msg'] == ("Task %d of template 'tk-fail' failed (status error). Last line of its output: "
                             'Failed to run task: exit status 127' % tid(project, 'task_start_failing'))
    assert result['task']['status'] == 'error'
    assert result['task']['output'][-1] == 'Failed to run task: exit status 127'


def test_a_task_someone_stopped_fails_the_module(project, run_module):
    project.route('POST', base(project) + '/tasks', 'task_start_to_stop')
    project.route('GET', task_path(project, 'task_start_to_stop'), 'task_get_stopped')
    project.route('GET', task_path(project, 'task_start_to_stop') + '/output', 'task_output_stopped')
    result = run_module(task.main, dict(project=PROJECT, template='tk-slow'))
    assert result['failed'] is True
    assert 'was stopped' in result['msg']
    assert result['task']['status'] == 'stopped'


def test_wait_timeout_fails_and_leaves_the_task(project, run_module):
    project.route('POST', base(project) + '/tasks', 'task_start')
    project.route('GET', task_path(project), 'task_get_running')
    result = run_module(task.main, dict(project=PROJECT, template='tk-slow', wait_timeout=12, poll_interval=5))
    assert result['failed'] is True and result['changed'] is True
    assert result['msg'] == ("Task %d of template 'tk-slow' is still running after 12 seconds (wait_timeout). It goes on "
                             'in Semaphore; read it with task_info, or stop it with state: stopped.' % tid(project))
    assert result['task']['status'] == 'running'
    # 0, 5 and 10 seconds are under the limit, 15 is over it: three pauses, three reads.
    assert sleeps() == [5, 5, 5]
    assert len(posts(project)) == 1


def test_wait_timeout_can_stop_the_task(project, run_module):
    project.route('POST', base(project) + '/tasks', 'task_start')
    project.route('GET', task_path(project), 'task_get_running')
    project.route('POST', task_path(project) + '/stop', 'task_stop')
    result = run_module(task.main, dict(project=PROJECT, template='tk-slow', wait_timeout=5, stop_on_timeout=True))
    assert result['failed'] is True
    assert result['msg'].endswith('(wait_timeout). Semaphore was asked to stop it.')
    assert project.calls('POST', task_path(project) + '/stop')[0]['body'] == dict(force=False)


def test_a_task_that_waits_for_a_confirmation_fails_the_module(project, run_module):
    project.route('POST', base(project) + '/tasks', 'task_start')
    # Hand-edited: no task of the recording waits for a confirmation (that takes a Terraform plan).
    project.route('GET', task_path(project), edited(project, 'task_get_running', status='waiting_confirmation'))
    result = run_module(task.main, dict(project=PROJECT, template='tk-slow'))
    assert result['failed'] is True
    assert 'waits for a confirmation in Semaphore' in result['msg']
    assert result['task']['status'] == 'waiting_confirmation'
    assert len(project.calls('GET', task_path(project))) == 1


def test_a_refused_start_is_reported(project, run_module):
    project.route('POST', base(project) + '/tasks', 'task_start_unknown_template')
    result = run_module(task.main, dict(project=PROJECT, template='tk-slow', secret_variables=dict(pw='hunter2-not-real')))
    assert result['failed'] is True
    assert 'returned HTTP 404' in result['msg']
    assert 'hunter2-not-real' not in json.dumps(result)
    assert result['request_details']['request']['secret'] == '********'


def test_secret_variables_are_sent_and_not_returned(lifecycle, run_module):
    result = run_module(task.main, dict(project=PROJECT, template='tk-slow', secret_variables=dict(pw='hunter2-not-real')))
    assert posts(lifecycle)[0]['body']['secret'] == json.dumps(dict(pw='hunter2-not-real'))
    assert 'hunter2-not-real' not in json.dumps(result)


def test_unknown_template(project, run_module):
    result = run_module(task.main, dict(project=PROJECT, template='nope'))
    assert result['failed'] is True
    assert result['msg'] == "Template 'nope' does not exist in project 'fixtures-task'."
    assert posts(project) == []


def test_unknown_template_in_check_mode_is_a_change(project, run_module):
    result = run_module(task.main, dict(project=PROJECT, template='nope'), check_mode=True)
    assert result['changed'] is True
    assert result['task'] == {}
    # A warning is a string, or a dict from ansible-core 2.19 on.
    warnings = json.dumps(result['warnings'])
    assert "Template 'nope' does not exist" in warnings and 'Check mode assumes' in warnings


def test_project_by_id(server, run_module):
    server.route('GET', '/project/7', 'project_get')
    server.route('GET', '/project/7/templates', 'task_templates')
    server.route('POST', '/project/7/tasks', 'task_start')
    result = run_module(task.main, dict(project_id=7, template='tk-slow', wait=False))
    assert result['task']['project'] == server.fixtures['project_get']['body']['name']
    assert server.calls('GET', '/projects') == []


# -- task: what a template has to allow ----------------------------------------


@pytest.mark.parametrize('options, switch', [
    (dict(arguments=['--flag']), 'allow_override_args_in_task: true'),
    (dict(git_branch='other'), 'allow_override_branch_in_task: true'),
])
def test_an_override_the_template_does_not_allow_is_refused(project, run_module, options, switch):
    result = run_module(task.main, dict(project=PROJECT, template='tk-quick', **options))
    assert result['failed'] is True
    assert "Template 'tk-quick' does not let a task set %s" % list(options)[0] in result['msg']
    assert switch in result['msg']
    assert posts(project) == []


def test_an_allowed_branch_is_sent(project, run_module):
    with_template(project, 'tk-quick', allow_override_branch_in_task=True)
    project.route('POST', base(project) + '/tasks', 'task_start_quick')
    run_module(task.main, dict(project=PROJECT, template='tk-quick', git_branch='other', playbook='other.sh', wait=False))
    assert posts(project)[0]['body'] == dict(template_id=template_id(project, 'tk-quick'), git_branch='other',
                                             playbook='other.sh')


def test_task_params_of_another_app_are_refused(project, run_module):
    result = run_module(task.main, dict(project=PROJECT, template='tk-quick', task_params=dict(limit=['a'])))
    assert result['failed'] is True
    assert result['msg'] == 'task_params limit are not valid for a template of app bash (valid: none).'


@pytest.mark.parametrize('param, value, switch', [
    ('limit', ['web01'], 'allow_override_limit'),
    ('tags', ['deploy'], 'allow_override_tags'),
    ('skip_tags', ['slow'], 'allow_override_skip_tags'),
    ('debug', True, 'allow_debug'),
])
def test_ansible_task_params_need_the_templates_switch(project, run_module, param, value, switch):
    # Hand-edited: the recorded templates are of app bash.
    with_template(project, 'tk-quick', app='ansible', task_params={})
    result = run_module(task.main, dict(project=PROJECT, template='tk-quick', task_params={param: value}))
    assert result['failed'] is True
    assert 'does not let a task set task_params.%s' % param in result['msg']
    assert '%s: true' % switch in result['msg']
    assert posts(project) == []

    with_template(project, 'tk-quick', app='ansible', task_params={switch: True})
    project.route('POST', base(project) + '/tasks', 'task_start_quick')
    run_module(task.main, dict(project=PROJECT, template='tk-quick', task_params={param: value}, wait=False))
    assert posts(project)[0]['body']['params'] == {param: value}


def test_ansible_task_params_without_a_switch_and_a_limit_as_text(project, run_module):
    with_template(project, 'tk-quick', app='ansible', task_params=dict(allow_override_limit=True))
    project.route('POST', base(project) + '/tasks', 'task_start_quick')
    run_module(task.main, dict(project=PROJECT, template='tk-quick', wait=False,
                               task_params=dict(dry_run=True, diff=True, limit='web01')))
    assert posts(project)[0]['body']['params'] == dict(dry_run=True, diff=True, limit=['web01'])


def test_terraform_auto_approve(project, run_module):
    with_template(project, 'tk-quick', app='tofu', task_params={})
    result = run_module(task.main, dict(project=PROJECT, template='tk-quick', task_params=dict(auto_approve=True)))
    assert result['failed'] is True and 'allow_auto_approve: true' in result['msg']
    # A template that approves by itself needs no permission for it.
    with_template(project, 'tk-quick', app='tofu', task_params=dict(auto_approve=True))
    project.route('POST', base(project) + '/tasks', 'task_start_quick')
    result = run_module(task.main, dict(project=PROJECT, template='tk-quick', wait=False,
                                        task_params=dict(auto_approve=True, plan=True)))
    assert result.get('failed') is not True
    assert posts(project)[0]['body']['params'] == dict(auto_approve=True, plan=True)


def test_task_params_of_an_app_the_module_does_not_know_are_sent_as_given(project, run_module):
    with_template(project, 'tk-quick', app='pulumi')
    project.route('POST', base(project) + '/tasks', 'task_start_quick')
    run_module(task.main, dict(project=PROJECT, template='tk-quick', wait=False, task_params=dict(stack='dev')))
    assert posts(project)[0]['body']['params'] == dict(stack='dev')


def test_inventory_override(project, run_module):
    result = run_module(task.main, dict(project=PROJECT, template='tk-quick', inventory='other'))
    assert result['failed'] is True and 'only for a template of app ansible' in result['msg']

    with_template(project, 'tk-quick', app='ansible', task_params={})
    result = run_module(task.main, dict(project=PROJECT, template='tk-quick', inventory='other'))
    assert result['failed'] is True and 'allow_override_inventory: true' in result['msg']

    with_template(project, 'tk-quick', app='ansible', task_params=dict(allow_override_inventory=True))
    # Hand-written: the task area records no inventory list.
    project.route('GET', base(project) + '/inventory', dict(status=200, body=[dict(id=41, name='other')]))
    project.route('POST', base(project) + '/tasks', 'task_start_quick')
    run_module(task.main, dict(project=PROJECT, template='tk-quick', inventory='other', wait=False))
    assert posts(project)[0]['body']['inventory_id'] == 41

    result = run_module(task.main, dict(project=PROJECT, template='tk-quick', inventory='gone'))
    assert result['failed'] is True and "Inventory 'gone' does not exist" in result['msg']


def test_build_task_id_is_for_deploy_templates(project, run_module):
    result = run_module(task.main, dict(project=PROJECT, template='tk-quick', build_task_id=3))
    assert result['failed'] is True
    assert result['msg'] == "build_task_id is only for a template of type deploy; 'tk-quick' is not one."

    build = tid(project, 'task_start_build')
    project.route('POST', base(project) + '/tasks', 'task_start_deploy')
    project.route('GET', task_path(project, 'task_start_deploy'), 'task_get_deploy_success')
    project.route('GET', task_path(project, 'task_start_deploy') + '/output', 'task_output')
    result = run_module(task.main, dict(project=PROJECT, template='tk-deploy', build_task_id=build))
    assert posts(project)[0]['body'] == dict(template_id=template_id(project, 'tk-deploy'), build_task_id=build)
    assert result['task']['build_task_id'] == build


def test_a_build_task_reports_its_version(project, run_module):
    project.route('POST', base(project) + '/tasks', 'task_start_build')
    project.route('GET', task_path(project, 'task_start_build'), 'task_get_build_success')
    project.route('GET', task_path(project, 'task_start_build') + '/output', 'task_output')
    assert run_module(task.main, dict(project=PROJECT, template='tk-build'))['task']['version'] == '1.0.0'


@pytest.mark.parametrize('options, message', [
    (dict(template='tk-quick', task_id=3), 'task_id is only for state: stopped'),
    (dict(template='tk-quick', poll_interval=0), 'poll_interval must be 1 or more'),
    (dict(template='tk-quick', wait_timeout=-1), 'wait_timeout must be 0 or more'),
])
def test_options_that_cannot_work(project, run_module, options, message):
    result = run_module(task.main, dict(project=PROJECT, **options))
    assert result['failed'] is True and message in result['msg']
    assert posts(project) == []


@pytest.mark.parametrize('options, message', [
    (dict(project=PROJECT), 'state is started but all of the following are missing: template'),
    (dict(project=PROJECT, state='stopped'), 'state is stopped but all of the following are missing: task_id'),
    (dict(template='tk-quick'), 'one of the following is required: project, project_id'),
    (dict(project=PROJECT, project_id=1, template='tk-quick'), 'parameters are mutually exclusive: project|project_id'),
])
def test_what_the_argument_spec_refuses(server, run_module, options, message):
    result = run_module(task.main, options)
    assert result['failed'] is True and message in result['msg']
    assert server.requests == []


# -- task: stopped -------------------------------------------------------------


@pytest.fixture
def running(project):
    """A task that runs, and is stopped once Semaphore was asked."""
    path = task_path(project, 'task_start_to_stop')
    project.route('GET', path, edited(project, 'task_get_stopped', status='running', end=None), 'task_get_stopped')
    project.route('POST', path + '/stop', 'task_stop')
    project.route('GET', path + '/output', 'task_output_stopped')
    return project


@pytest.mark.parametrize('force', [False, True])
def test_stop_a_running_task(running, run_module, force):
    stop_id = tid(running, 'task_start_to_stop')
    result = run_module(task.main, dict(project=PROJECT, state='stopped', task_id=stop_id, force=force))
    assert result['changed'] is True
    assert result.get('failed') is not True, result.get('msg')
    assert (result['task']['id'], result['task']['status']) == (stop_id, 'stopped')
    assert result['task']['output'][-1] == 'tk-slow started'
    assert posts(running) == running.calls('POST', task_path(running, 'task_start_to_stop') + '/stop')
    assert posts(running)[0]['body'] == dict(force=force)


def test_stop_in_check_mode_sends_nothing(running, run_module):
    result = run_module(task.main, dict(project=PROJECT, state='stopped', task_id=tid(running, 'task_start_to_stop')),
                        check_mode=True)
    assert result['changed'] is True
    assert result['task']['status'] == 'running'
    assert posts(running) == []


def test_stop_without_waiting(running, run_module):
    result = run_module(task.main, dict(project=PROJECT, state='stopped', wait=False,
                                        task_id=tid(running, 'task_start_to_stop')))
    assert result['changed'] is True
    assert sleeps() == []
    assert len(posts(running)) == 1


@pytest.mark.parametrize('fixture, status', [
    ('task_get_success', 'success'), ('task_get_error', 'error'), ('task_get_stopped', 'stopped')])
def test_a_task_that_is_over_is_not_asked_to_stop(project, run_module, fixture, status):
    # Semaphore answers 204 to that request and sets the task to "stopped", whatever it ended with.
    stop_id = project.fixtures[fixture]['body']['id']
    project.route('GET', '%s/tasks/%d' % (base(project), stop_id), fixture)
    for check_mode in (False, True):
        result = run_module(task.main, dict(project=PROJECT, state='stopped', task_id=stop_id), check_mode=check_mode)
        assert result['changed'] is False
        assert result['task']['status'] == status
    assert posts(project) == []


def test_stop_a_task_that_does_not_exist(project, run_module):
    missing = tid(project) + 100000
    project.route('GET', '%s/tasks/%d' % (base(project), missing), 'task_get_missing')
    result = run_module(task.main, dict(project=PROJECT, state='stopped', task_id=missing))
    assert result['failed'] is True
    assert result['msg'] == "Task %d does not exist in project 'fixtures-task'." % missing
    assert posts(project) == []


def test_a_stop_that_does_not_take_fails(project, run_module):
    path = task_path(project, 'task_start_to_stop')
    # Hand-edited: the recorded task stopped at once.
    project.route('GET', path, edited(project, 'task_get_stopped', status='running', end=None),
                  edited(project, 'task_get_stopped', status='stopping', end=None))
    project.route('POST', path + '/stop', 'task_stop')
    result = run_module(task.main, dict(project=PROJECT, state='stopped', wait_timeout=10,
                                        task_id=tid(project, 'task_start_to_stop')))
    assert result['failed'] is True
    assert 'is still stopping after 10 seconds' in result['msg'] and 'force: true' in result['msg']
    # One request to stop it, not a second one when the wait ran out.
    assert len(posts(project)) == 1


# -- task_info -----------------------------------------------------------------


def test_info_one_task(project, run_module):
    project.route('GET', task_path(project), 'task_get_success')
    result = run_module(task_info.main, dict(project=PROJECT, task_id=tid(project)))
    assert result['changed'] is False
    assert [(t['id'], t['status'], t['template'], t['output']) for t in result['tasks']] == [
        (tid(project), 'success', 'tk-slow', [])]
    assert project.calls('GET', task_path(project) + '/output') == []


def test_info_one_task_with_output(project, run_module):
    project.route('GET', task_path(project), 'task_get_success')
    project.route('GET', task_path(project) + '/output', 'task_output')
    result = run_module(task_info.main, dict(project=PROJECT, task_id=tid(project), output_lines=2))
    assert result['tasks'][0]['output'] == ['tk-slow started', 'tk-slow done']
    # A read is a read: no pause, no second look.
    assert len(project.calls('GET', task_path(project) + '/output')) == 1
    assert sleeps() == []


def test_info_a_task_that_does_not_exist(project, run_module):
    missing = tid(project) + 100000
    project.route('GET', '%s/tasks/%d' % (base(project), missing), 'task_get_missing')
    result = run_module(task_info.main, dict(project=PROJECT, task_id=missing))
    assert result.get('failed') is not True
    assert result['tasks'] == []


def test_info_last_tasks_of_the_project(project, run_module):
    project.route('GET', base(project) + '/tasks/last?limit=3', 'task_list_last')
    result = run_module(task_info.main, dict(project=PROJECT, limit=3))
    recorded = project.fixtures['task_list_last']['body']
    assert [t['id'] for t in result['tasks']] == sorted((t['id'] for t in recorded), reverse=True)
    assert [t['template'] for t in result['tasks']] == [t['tpl_alias'] for t in recorded]
    assert result['tasks'][0]['finished'] is True


def test_info_default_limit(project, run_module):
    project.route('GET', base(project) + '/tasks/last?limit=20', 'task_list_last')
    assert len(run_module(task_info.main, dict(project=PROJECT))['tasks']) == 3


def test_info_tasks_of_a_template(project, run_module):
    path = '%s/templates/%d/tasks/last?limit=20' % (base(project), template_id(project, 'tk-slow'))
    project.route('GET', path, 'task_list_template')
    result = run_module(task_info.main, dict(project=PROJECT, template='tk-slow'))
    assert [(t['template'], t['status']) for t in result['tasks']] == [('tk-slow', 'stopped'), ('tk-slow', 'success')]
    assert result['tasks'][1]['variables'] == dict(who='world')
    assert result['tasks'][1]['arguments'] == ['--flag']


def test_info_output_of_every_listed_task(project, run_module):
    project.route('GET', base(project) + '/tasks/last?limit=3', 'task_list_last')
    for listed in project.fixtures['task_list_last']['body']:
        project.route('GET', '%s/tasks/%d/output' % (base(project), listed['id']), 'task_output')
    result = run_module(task_info.main, dict(project=PROJECT, limit=3, output_lines=1))
    assert [t['output'] for t in result['tasks']] == [['tk-slow done']] * 3


def test_info_unknown_template(project, run_module):
    result = run_module(task_info.main, dict(project=PROJECT, template='nope'))
    assert result['failed'] is True
    assert result['msg'] == "Template 'nope' does not exist in project 'fixtures-task'."


@pytest.mark.parametrize('limit', [0, 201, -5])
def test_info_limit_is_checked(server, run_module, limit):
    result = run_module(task_info.main, dict(project=PROJECT, limit=limit))
    assert result['failed'] is True
    assert result['msg'] == 'limit must be between 1 and 200. Got %d.' % limit


def test_info_task_id_and_template_exclude_each_other(server, run_module):
    result = run_module(task_info.main, dict(project=PROJECT, task_id=1, template='tk-slow'))
    assert result['failed'] is True and 'mutually exclusive: task_id|template' in result['msg']


# -- what the docs say is returned ---------------------------------------------


def documented_fields(module, key):
    return set(yaml.safe_load(module.RETURN)[key]['contains'])


def test_task_returns_what_it_documents(lifecycle, run_module):
    result = run_module(task.main, dict(project=PROJECT, template='tk-slow'))
    assert set(result) - STANDARD_KEYS == set(yaml.safe_load(task.RETURN)) == set(['task'])
    assert set(result['task']) == documented_fields(task, 'task')
    assert set(yaml.safe_load(task.RETURN)['task']['sample']) == documented_fields(task, 'task')


def test_task_info_returns_what_it_documents(project, run_module):
    project.route('GET', task_path(project), 'task_get_success')
    result = run_module(task_info.main, dict(project=PROJECT, task_id=tid(project)))
    assert set(result) - STANDARD_KEYS == set(yaml.safe_load(task_info.RETURN)) == set(['tasks'])
    assert set(result['tasks'][0]) == documented_fields(task_info, 'tasks')
    assert set(yaml.safe_load(task_info.RETURN)['tasks']['sample'][0]) == documented_fields(task_info, 'tasks')
    # One shape for both modules.
    assert documented_fields(task_info, 'tasks') == documented_fields(task, 'task')


def test_fields_stored_as_json_that_is_not_json_are_returned_as_they_are():
    view = task_utils.task_view(dict(id=1, template_id=2, arguments='-v --diff', environment='not json'), 'p', {2: 't'})
    assert (view['arguments'], view['variables'], view['template']) == ('-v --diff', 'not json', 't')
