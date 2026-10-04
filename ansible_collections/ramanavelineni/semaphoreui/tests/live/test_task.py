# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""Tasks from start to end on a real server: run, fail, time out, stop, and read them back.

The tasks run in the server's own container and need nothing from outside it.
The repository is the local path /dev and the templates' script is null, so a
task runs `bash null` there, which does nothing and succeeds. The slow template
gets its duration from a variable group that sets BASH_ENV: bash expands that
value before it reads the script, and the value is a command substitution that
sleeps.
"""

import time

import pytest

from ansible_collections.ramanavelineni.semaphoreui.plugins.modules import (
    inventory,
    key_store,
    project,
    repository,
    task,
    task_info,
    template,
    variable_group,
)

PROJECT = 'live-task'
SLOW_SECONDS = 20
FAST = dict(project=PROJECT, poll_interval=1)


@pytest.fixture(scope='module')
def built(sem):
    """The project with its templates, built with the modules once per way of logging in."""
    sem.ok(project, name=PROJECT)
    sem.ok(key_store, project=PROJECT, name='live-none', type='none')
    sem.ok(repository, project=PROJECT, name='live-local', git_url='/dev', git_branch='', ssh_key='live-none')
    sem.ok(inventory, project=PROJECT, name='live-inventory', type='static', inventory='localhost', ssh_key='live-none')
    sem.ok(variable_group, project=PROJECT, name='live-plain')
    sem.ok(variable_group, project=PROJECT, name='live-slow', env=dict(
        BASH_ENV='$(echo "live-slow started" >&2; sleep %d; echo "live-slow done" >&2)' % SLOW_SECONDS))
    common = dict(project=PROJECT, app='bash', playbook='null', repository='live-local', inventory='live-inventory')
    sem.ok(template, name='live-quick', variable_groups=['live-plain'], **common)
    sem.ok(template, name='live-args', variable_groups=['live-plain'], allow_override_args_in_task=True, **common)
    sem.ok(template, name='live-slow', variable_groups=['live-slow'], **common)
    sem.ok(template, name='live-fail', variable_groups=['live-plain'], **dict(common, playbook='live-missing.sh'))
    return sem


def ids(sem):
    return [t['id'] for t in sem.ok(task_info, project=PROJECT, limit=200)['tasks']]


def until_finished(sem, task_id, seconds=60):
    for dummy in range(seconds):
        found = sem.ok(task_info, project=PROJECT, task_id=task_id)['tasks'][0]
        if found['finished']:
            return found
        time.sleep(1)
    raise AssertionError('task %d is still %s after %d seconds' % (task_id, found['status'], seconds))


def test_a_task_runs_to_its_end(built):
    result = built.ok(task, template='live-quick', message='live run', variables=dict(who='world'), **FAST)
    assert result['changed'] is True
    ran = result['task']
    assert (ran['status'], ran['finished'], ran['template'], ran['project']) == ('success', True, 'live-quick', PROJECT)
    assert (ran['message'], ran['variables']) == ('live run', dict(who='world'))
    assert ran['start'] and ran['end'] and ran['output']
    # task_info returns the same task, and the same lines when asked for them.
    read = built.ok(task_info, project=PROJECT, task_id=ran['id'], output_lines=200)
    assert read['changed'] is False
    assert read['tasks'] == [ran]
    assert built.ok(task_info, project=PROJECT, task_id=ran['id'])['tasks'][0]['output'] == []


def test_every_run_starts_a_new_task(built):
    first = built.ok(task, template='live-quick', **FAST)['task']['id']
    second = built.ok(task, template='live-quick', **FAST)['task']['id']
    assert second > first


def test_check_mode_starts_nothing(built):
    before = ids(built)
    result = built.ok(task, check_mode=True, template='live-quick', message='not started', **FAST)
    assert result['changed'] is True
    assert (result['task']['id'], result['task']['status'], result['task']['message']) == (None, '', 'not started')
    assert ids(built) == before


def test_a_task_that_fails_fails_the_module(built):
    result = built.run(task, template='live-fail', **FAST)
    assert result['failed'] is True and result['changed'] is True
    assert 'failed (status error)' in result['msg']
    assert result['task']['status'] == 'error'
    assert any('exit status' in line for line in result['task']['output'])


def test_secret_variables_are_not_stored(built):
    result = built.ok(task, template='live-quick', secret_variables=dict(pw='live-not-a-real-secret'), **FAST)
    assert 'live-not-a-real-secret' not in repr(result)
    status, stored = built.api.call('GET', '/project/%d/tasks/%d' % (
        [p['id'] for p in built.api.get('/projects') if p['name'] == PROJECT][0], result['task']['id']))
    assert status == 200 and 'live-not-a-real-secret' not in repr(stored)


def test_what_the_template_does_not_allow_is_refused_before_anything_starts(built):
    before = ids(built)
    result = built.run(task, template='live-quick', arguments=['--flag'], **FAST)
    assert result['failed'] is True
    assert 'does not let a task set arguments' in result['msg']
    result = built.run(task, template='live-quick', git_branch='other', **FAST)
    assert result['failed'] is True and 'git_branch' in result['msg']
    assert ids(built) == before
    allowed = built.ok(task, template='live-args', arguments=['--flag'], **FAST)
    assert allowed['task']['arguments'] == ['--flag']


def test_started_without_waiting_and_read_later(built):
    result = built.ok(task, template='live-quick', wait=False, **FAST)
    assert result['changed'] is True
    assert result['task']['id'] and result['task']['output'] == []
    assert until_finished(built, result['task']['id'])['status'] == 'success'


def test_a_wait_that_runs_out_fails_and_can_stop_the_task(built):
    result = built.run(task, template='live-slow', wait_timeout=2, stop_on_timeout=True, **FAST)
    assert result['failed'] is True
    assert 'after 2 seconds' in result['msg'] and 'asked to stop' in result['msg']
    assert until_finished(built, result['task']['id'])['status'] == 'stopped'


def test_a_wait_that_runs_out_leaves_the_task_running(built):
    result = built.run(task, template='live-slow', wait_timeout=2, **FAST)
    assert result['failed'] is True and 'goes on in Semaphore' in result['msg']
    task_id = result['task']['id']
    assert built.ok(task_info, project=PROJECT, task_id=task_id)['tasks'][0]['finished'] is False
    # Stopping it: predicted in check mode, done, and nothing left to do the second time.
    assert built.ok(task, check_mode=True, state='stopped', task_id=task_id, **FAST)['changed'] is True
    assert built.ok(task_info, project=PROJECT, task_id=task_id)['tasks'][0]['finished'] is False
    stopped = built.ok(task, state='stopped', task_id=task_id, **FAST)
    assert stopped['changed'] is True and stopped['task']['status'] == 'stopped'
    again = built.ok(task, state='stopped', task_id=task_id, **FAST)
    assert again['changed'] is False and again['task']['status'] == 'stopped'


def test_stopping_a_task_that_is_over_leaves_its_status(built):
    done = built.ok(task, template='live-quick', **FAST)['task']
    result = built.ok(task, state='stopped', task_id=done['id'], **FAST)
    assert result['changed'] is False
    # Semaphore would set it to "stopped" if it were asked.
    assert built.ok(task_info, project=PROJECT, task_id=done['id'])['tasks'][0]['status'] == 'success'


def test_a_task_that_does_not_exist(built):
    result = built.run(task, state='stopped', task_id=99999999, **FAST)
    assert result['failed'] is True and 'does not exist' in result['msg']
    assert built.ok(task_info, project=PROJECT, task_id=99999999)['tasks'] == []


def test_lists_are_newest_first_and_limited(built):
    everything = built.ok(task_info, project=PROJECT, limit=200)['tasks']
    assert [t['id'] for t in everything] == sorted((t['id'] for t in everything), reverse=True)
    assert len(everything) > 3
    assert [t['id'] for t in built.ok(task_info, project=PROJECT, limit=3)['tasks']] == [t['id'] for t in everything[:3]]
    of_template = built.ok(task_info, project=PROJECT, template='live-fail')['tasks']
    assert of_template and set(t['template'] for t in of_template) == set(['live-fail'])
    missing = built.run(task_info, project=PROJECT, template='live-not-a-template')
    assert missing['failed'] is True and 'does not exist' in missing['msg']
