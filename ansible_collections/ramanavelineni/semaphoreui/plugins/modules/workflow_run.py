#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: workflow_run
short_description: Run a Semaphore UI workflow, or stop a run
version_added: 0.6.0
description:
  - Starts a run of a workflow and by default waits until it is over. The module fails when the run
    failed or was stopped, and returns the run with the state of each node.
  - A run that reaches an approval node waits for a person. The module then stops waiting and returns
    the run with RV(run.status=approval) and the nodes in RV(run.pending_approvals), without failing.
    M(ramanavelineni.semaphoreui.workflow_approval) gives the decision; this module with O(run_id)
    then waits for the rest of the run.
  - With O(run_id) and O(state=started) no run is started; the module reads that run and waits for it.
  - With O(state=stopped) it stops the run O(run_id).
  - B(This module is not idempotent:) every run with O(state=started) and no O(run_id) starts a new run.
  - Workflows need Semaphore 2.19 or later, in a build that has them, as the official images do. The
    module checks C(features.workflows) in Semaphore's C(/info) and fails clearly on a server without them.
author:
  - ramanavelineni (@ramanavelineni)
extends_documentation_fragment:
  - ramanavelineni.semaphoreui.auth
  - ramanavelineni.semaphoreui.attributes
  - ramanavelineni.semaphoreui.project
attributes:
  check_mode:
    support: partial
    details:
      - In check mode nothing is started or stopped. A run that would be started is reported as
        changed, without an id or a status.
      - Stopping a run that is already over is reported as unchanged, in check mode too.
  diff_mode:
    support: none
options:
  project_id:
    version_added: 0.6.0
  workflow:
    description: Name of the workflow.
    type: str
    required: true
  state:
    description:
      - V(started) starts a run, or with O(run_id) waits for that run.
      - V(stopped) stops the run O(run_id). A run that is already over is left as it is.
    type: str
    choices: [started, stopped]
    default: started
  run_id:
    description: Id of a run of the workflow. Required with O(state=stopped).
    type: int
  variables:
    description:
      - Answers to the workflow's survey (O(ramanavelineni.semaphoreui.workflow#module:survey_vars)),
        by variable name. A select variable takes a list of strings.
      - Semaphore fills in the defaults, refuses the run when a required variable has no value, and
        drops names that are not survey variables.
      - Only when a run is started. Needs Semaphore 2.20; 2.19 has no workflow survey.
    type: dict
  wait:
    description: Whether to wait until the run is over or waits for an approval.
    type: bool
    default: true
  wait_timeout:
    description:
      - How many seconds to wait. When they are over the module fails and says so; the run goes on
        unless O(stop_on_timeout=true).
      - The time is counted in the pauses between two reads of the run, so it is a lower bound.
    type: int
    default: 1800
  poll_interval:
    description: Seconds between two reads of the run while waiting.
    type: int
    default: 5
  stop_on_timeout:
    description: Ask Semaphore to stop the run when O(wait_timeout) is over. The module fails all the same.
    type: bool
    default: false
seealso:
  - module: ramanavelineni.semaphoreui.workflow
    description: Manages the workflow.
  - module: ramanavelineni.semaphoreui.workflow_approval
    description: Approves or rejects an approval node of a run.
  - module: ramanavelineni.semaphoreui.task_info
    description: Reads the tasks a run started, with their output.
'''

EXAMPLES = r'''
# The connection options (url and api_token, or username and password) are left out here. Set them once
# with module_defaults, or in the SEMAPHORE_URL and SEMAPHORE_API_TOKEN environment variables; the
# collection's README shows both under "Connecting".

- name: Run the release workflow
  ramanavelineni.semaphoreui.workflow_run:
    project: webshop
    workflow: release
    variables:
      release: "1.4.2"
  register: run

- name: Approve the sign-off when the run waits for it
  ramanavelineni.semaphoreui.workflow_approval:
    project: webshop
    workflow: release
    run_id: "{{ run.run.id }}"
    decision: approved
  when: run.run.status == 'approval'

- name: Wait for the rest of the run
  ramanavelineni.semaphoreui.workflow_run:
    project: webshop
    workflow: release
    run_id: "{{ run.run.id }}"

- name: Stop a run
  ramanavelineni.semaphoreui.workflow_run:
    project: webshop
    workflow: release
    state: stopped
    run_id: "{{ run.run.id }}"
'''

RETURN = r'''
run:
  description:
    - The run as Semaphore reports it at the end of the module's run.
    - In check mode, for a run that would be started, without what only Semaphore can tell.
  returned: always
  type: dict
  contains:
    id:
      description: Run id. Null in check mode for a run that would be started.
      type: int
    project:
      description: Name of the project.
      type: str
    workflow:
      description: Name of the workflow.
      type: str
    workflow_id:
      description: Id of the workflow.
      type: int
    revision_id:
      description: Revision of the workflow's graph the run executes.
      type: int
    status:
      description:
        - V(running), or V(approval) while it waits for a decision; V(success), V(failed) or V(stopped) when it is over.
        - Empty in check mode for a run that would be started.
      type: str
    finished:
      description: Whether the run is over.
      type: bool
    variables:
      description: The survey answers the run started with, after Semaphore filled in the defaults.
      type: dict
    start:
      description: When the run started.
      type: str
    end:
      description: When the run ended. Empty while it is not over.
      type: str
    root_task_id:
      description: Id of the first task the run started.
      type: int
    nodes:
      description: Each node of the run's graph with its id, kind and template, the id and status of the task it started, and the status of its approval.
      type: list
      elements: dict
    pending_approvals:
      description: Ids of the approval nodes that wait for a decision.
      type: list
      elements: int
  sample:
    id: 7
    project: webshop
    workflow: release
    workflow_id: 4
    revision_id: 2
    status: approval
    finished: false
    variables:
      release: "1.4.2"
    start: "2026-11-08T15:59:29Z"
    end: ""
    root_task_id: 52
    nodes:
      - node_id: 31
        kind: task
        template: build
        task_id: 52
        task_status: success
        approval_status: ""
      - node_id: 32
        kind: approval
        template: null
        task_id: null
        task_status: ""
        approval_status: pending
    pending_approvals: [32]
'''

import time

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.semaphore import (
    PROJECT_REQUIRED,
    SemaphoreError,
    project_argument_spec,
    project_ref,
    run_module,
    semaphore_argument_spec,
    semaphore_module_kwargs,
)
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.task import template_names
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.workflow import (
    FINAL_RUN_STATUSES,
    NEWER,
    WAITS_FOR_APPROVAL,
    get_run,
    no_workflow_api,
    require_workflow,
    run_view,
    workflow_version,
)


def read_run(client, base, workflow, run_id):
    details = get_run(client, base, workflow['id'], run_id)
    if details is None:
        raise ValueError('Workflow %r has no run %d.' % (workflow.get('name'), run_id))
    return details


def status_of(details):
    return (details.get('run') or {}).get('status')


def wait_for_end(client, base, workflow, run_id, details, interval, timeout):
    """(details, settled) after polling run `run_id` until it is over, waits for an approval, or `timeout` seconds went by."""
    waited = 0
    while True:
        status = status_of(details)
        if status in FINAL_RUN_STATUSES or status == WAITS_FOR_APPROVAL:
            return details, True
        if waited >= timeout:
            return details, False
        time.sleep(interval)
        waited += interval
        details = read_run(client, base, workflow, run_id)


def finish(module, client, base, project, workflow, names, run_id, details, changed):
    """The result after waiting for run `run_id`, or a failure when it did not end well."""
    params = module.params
    details, settled = wait_for_end(client, base, workflow, run_id, details, params['poll_interval'],
                                    params['wait_timeout'])
    view = run_view(details, project, workflow['name'], names)
    what = 'Run %d of workflow %r' % (run_id, workflow['name'])
    if not settled:
        if params['state'] == 'stopped':
            after = ' Semaphore was asked to stop it and it has not stopped yet.'
        elif params['stop_on_timeout']:
            client.post('%s/workflows/%d/runs/%d/stop' % (base, workflow['id'], run_id), None, expected=(200,))
            after = ' Semaphore was asked to stop it.'
        else:
            after = ' It goes on in Semaphore; wait for it again with run_id, or stop it with state: stopped.'
        module.fail_json(msg='%s is still %s after %d seconds (wait_timeout).%s'
                             % (what, view['status'], params['wait_timeout'], after), changed=changed, run=view)
    if params['state'] == 'started' and view['status'] in ('failed', 'stopped'):
        failed = [n for n in view['nodes'] if n['task_status'] == 'error']
        detail = (' Failed task(s): %s.' % ', '.join('%s (task %s)' % (n['template'], n['task_id']) for n in failed)
                  if failed else '')
        module.fail_json(msg='%s %s.%s' % (what, view['status'], detail), changed=changed, run=view)
    return dict(changed=changed, run=view)


def start(module, client, base, project, workflow, names, version):
    params = module.params
    body = {}
    if params['variables'] is not None:
        body['environment'] = params['variables']
    # 2.19 starts a run with POST .../run and takes no body; 2.20 with POST .../runs.
    path = '%s/workflows/%d/%s' % (base, workflow['id'], 'runs' if version >= NEWER else 'run')
    if module.check_mode:
        return dict(changed=True, run=run_view(dict(run=dict(workflow_template_id=workflow['id'],
                                                             environment=params['variables'] or {})),
                                               project, workflow['name'], names))
    try:
        created = client.post(path, body if version >= NEWER else None)
    except SemaphoreError as e:
        if e.status in (404, 405):
            raise no_workflow_api(client, e)
        raise
    details = read_run(client, base, workflow, created['id'])
    if not params['wait']:
        return dict(changed=True, run=run_view(details, project, workflow['name'], names))
    return finish(module, client, base, project, workflow, names, created['id'], details, True)


def stop(module, client, base, project, workflow, names):
    params = module.params
    details = read_run(client, base, workflow, params['run_id'])
    if status_of(details) in FINAL_RUN_STATUSES:
        return dict(changed=False, run=run_view(details, project, workflow['name'], names))
    if module.check_mode:
        return dict(changed=True, run=run_view(details, project, workflow['name'], names))
    client.post('%s/workflows/%d/runs/%d/stop' % (base, workflow['id'], params['run_id']), None, expected=(200,))
    details = read_run(client, base, workflow, params['run_id'])
    if not params['wait']:
        return dict(changed=True, run=run_view(details, project, workflow['name'], names))
    return finish(module, client, base, project, workflow, names, params['run_id'], details, True)


def run(module, client):
    client.warn_if_untested()
    params = module.params
    if params['poll_interval'] < 1:
        raise ValueError('poll_interval must be 1 or more (seconds). Got %d.' % params['poll_interval'])
    if params['wait_timeout'] < 0:
        raise ValueError('wait_timeout must be 0 or more (seconds). Got %d.' % params['wait_timeout'])
    if params['variables'] is not None and params['run_id'] is not None:
        raise ValueError('variables are only for a run this module starts; leave out run_id to start one.')
    version = workflow_version(client)
    if params['variables'] is not None and version < NEWER:
        raise ValueError('variables need Semaphore 2.20 or later; %d.%d has no workflow survey.' % version)
    project_id, project = project_ref(client, params)
    base = '/project/%d' % project_id
    workflow = require_workflow(client, base, params['workflow'], project)
    names = template_names(client.list(base + '/templates'))
    if params['state'] == 'stopped':
        return stop(module, client, base, project, workflow, names)
    if params['run_id'] is None:
        return start(module, client, base, project, workflow, names, version)
    details = read_run(client, base, workflow, params['run_id'])
    if not params['wait']:
        return dict(changed=False, run=run_view(details, project, workflow['name'], names))
    return finish(module, client, base, project, workflow, names, params['run_id'], details, False)


def main():
    argument_spec = semaphore_argument_spec()
    argument_spec.update(
        project_argument_spec(),
        workflow=dict(type='str', required=True),
        state=dict(type='str', choices=['started', 'stopped'], default='started'),
        run_id=dict(type='int'),
        variables=dict(type='dict'),
        wait=dict(type='bool', default=True),
        wait_timeout=dict(type='int', default=1800),
        poll_interval=dict(type='int', default=5),
        stop_on_timeout=dict(type='bool', default=False),
    )
    module = AnsibleModule(
        argument_spec=argument_spec, supports_check_mode=True,
        **semaphore_module_kwargs(project=PROJECT_REQUIRED, required_if=[('state', 'stopped', ('run_id',))])
    )
    run_module(module, lambda client: run(module, client), placeholder=dict(run={}))


if __name__ == '__main__':
    main()
