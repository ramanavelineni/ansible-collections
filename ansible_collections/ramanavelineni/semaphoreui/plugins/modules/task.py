#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: task
short_description: Run a Semaphore UI template, or stop a task
version_added: 0.4.0
description:
  - Starts a task, that is one run of a template, and by default waits until it is over. The module
    fails when the task ends with an error or was stopped, and returns the task with its output.
  - With O(wait=false) the task is only started. RV(task) then carries its id, which
    M(ramanavelineni.semaphoreui.task_info) reads the status and the output with later.
  - With O(state=stopped) it stops a task that is waiting or running.
  - B(This module is not idempotent:) every run with O(state=started) starts a new task. Guard it
    with C(when), or use C(changed_when), where a play must not run the template twice.
  - A task may set a few things for itself (O(git_branch), O(arguments), O(inventory) and some of
    O(task_params)), each only if the template allows it. Semaphore ignores such a value without
    a word when the template does not allow it, so the module checks first and fails instead.
author:
  - ramanavelineni (@ramanavelineni)
extends_documentation_fragment:
  - ramanavelineni.semaphoreui.auth
  - ramanavelineni.semaphoreui.attributes
attributes:
  check_mode:
    support: partial
    details:
      - In check mode nothing is started or stopped. The task is reported as changed, and RV(task)
        shows what would be started, without an id or a status.
      - Stopping a task that is already over is reported as unchanged, in check mode too.
  diff_mode:
    support: none
options:
  project:
    description:
      - Name of the project.
      - Mutually exclusive with O(project_id); one of the two is required.
    type: str
  project_id:
    description:
      - Id of the project, as an alternative to O(project).
      - With it the list of projects is not read, so a project is found on a server with 200 or more
        projects too. Semaphore cuts that list off at 200, and O(project) fails there.
      - Mutually exclusive with O(project). One of the two is required.
    type: int
  state:
    description:
      - V(started) starts a new task of O(template).
      - V(stopped) stops the task O(task_id). A task that is already over is left as it is.
    type: str
    choices: [started, stopped]
    default: started
  template:
    description:
      - Name of the template to run. Required with O(state=started).
    type: str
  task_id:
    description:
      - Id of the task to stop. Required with O(state=stopped), and only used there.
    type: int
  message:
    description:
      - A note shown with the task in Semaphore's task list.
    type: str
  variables:
    description:
      - Variables for this run, added to the ones of the template's variable groups and winning
        over them. The values of the template's survey variables go here, under their names.
      - Semaphore passes them the way the template's app takes variables (extra variables for
        Ansible, C(-var) for Terraform and OpenTofu, C(name=value) arguments for a shell app),
        or as environment variables for survey variables with that target.
      - They are stored with the task and returned in RV(task.variables). For a value that must
        not be stored, use O(secret_variables).
    type: dict
  secret_variables:
    description:
      - Values of the template's survey variables of type V(secret). Semaphore uses them for this
        run and does not store them with the task; they are never returned.
    type: dict
  playbook:
    description:
      - Run this file instead of the template's playbook (or script). A path inside the
        repository.
    type: str
  git_branch:
    description:
      - Branch to check out instead of the template's or the repository's.
      - The template must allow it (C(allow_override_branch_in_task)).
    type: str
  arguments:
    description:
      - Command line arguments for this run, added to the template's.
      - The template must allow it (C(allow_override_args_in_task)).
    type: list
    elements: str
  inventory:
    description:
      - Name of the inventory to run against instead of the template's.
      - Only for templates of app V(ansible), and the template must allow it
        (C(allow_override_inventory) in its C(task_params)).
    type: str
  task_params:
    description:
      - What the task dialog in Semaphore offers for the template's app.
      - For V(ansible) the keys are C(debug), C(debug_level) (1 to 6), C(dry_run) (C(--check)),
        C(diff), C(limit), C(tags), C(skip_tags) (each a list) and C(skip_galaxy_install).
      - For V(terraform), V(tofu) and V(terragrunt) the keys are C(plan), C(destroy),
        C(auto_approve), C(upgrade) and C(reconfigure).
      - C(debug), C(limit), C(tags), C(skip_tags) and C(auto_approve) take effect only if the
        template allows them (C(allow_debug), C(allow_override_limit), C(allow_override_tags),
        C(allow_override_skip_tags), C(allow_auto_approve) in its C(task_params)). The module
        fails when it does not.
      - For an app the module does not know, the keys are sent as given.
    type: dict
  build_task_id:
    description:
      - Id of the build task whose version to deploy. Only for templates of type V(deploy).
    type: int
  wait:
    description:
      - Whether to wait until the task is over.
      - With V(false), O(state=started) returns as soon as the task is queued and
        O(state=stopped) as soon as Semaphore took the request.
    type: bool
    default: true
  wait_timeout:
    description:
      - How many seconds to wait for the task to end. When they are over, the module fails and
        says so; the task goes on in Semaphore unless O(stop_on_timeout=true).
      - The time is counted in the pauses between two reads of the task, so it is a lower bound.
    type: int
    default: 1800
  poll_interval:
    description:
      - Seconds between two reads of the task while waiting.
    type: int
    default: 5
  stop_on_timeout:
    description:
      - Ask Semaphore to stop a task this module started when O(wait_timeout) is over. The module
        fails all the same.
    type: bool
    default: false
  force:
    description:
      - With O(state=stopped), or when O(stop_on_timeout=true) applies, stop the task at once
        instead of letting it end its current step.
    type: bool
    default: false
  output_lines:
    description:
      - How many of the last lines of the task's output to return in RV(task.output).
      - V(0) returns none and does not read the output. V(-1) returns all of it.
      - Only read when the module waited for the task to end.
    type: int
    default: 200
notes:
  - A task's output is whatever the playbook or script printed. Semaphore masks the secrets it
    knows there, but a playbook can print anything. Set C(no_log) on the task, or
    O(output_lines=0), where the output may hold something secret.
  - O(variables) are stored with the task and returned. Do not put secrets there.
  - A task that waits for a confirmation in Semaphore (a Terraform plan without
    C(auto_approve)) cannot be confirmed by this module. It fails and leaves the task waiting.
  - Semaphore sets a task that is already over to V(stopped) when it is asked to stop it. The
    module reads the task first and does not send the request then.
seealso:
  - module: ramanavelineni.semaphoreui.task_info
    description: Reads tasks and their output without changing anything.
  - module: ramanavelineni.semaphoreui.template
    description: Manages the template a task runs, and what a task may set for itself.
  - module: ramanavelineni.semaphoreui.schedule
    description: Runs a template at set times.
  - module: ramanavelineni.semaphoreui.project
    description: Manages the project.
'''

EXAMPLES = r'''
# The connection options (url and api_token, or username and password) are left out here. Set them once
# with module_defaults, or in the SEMAPHORE_URL and SEMAPHORE_API_TOKEN environment variables; the
# collection's README shows both under "Connecting".

- name: Run the site playbook and wait for it
  ramanavelineni.semaphoreui.task:
    project: homelab
    template: site
    message: started by the nightly play
  register: run

- name: Show the end of its output
  ansible.builtin.debug:
    msg: "{{ run.task.output[-5:] }}"

- name: Run it for two hosts, in check mode, with a survey value
  ramanavelineni.semaphoreui.task:
    project: homelab
    template: site
    variables:
      release: "1.4.2"
    task_params:
      limit: [web01, web02]
      dry_run: true
      diff: true

- name: Start a long run and come back later
  ramanavelineni.semaphoreui.task:
    project: homelab
    template: backup
    wait: false
  register: started

- name: Read how it went
  ramanavelineni.semaphoreui.task_info:
    project: homelab
    task_id: "{{ started.task.id }}"
    output_lines: 50
  register: later

- name: Give a run ten minutes, then stop it
  ramanavelineni.semaphoreui.task:
    project: homelab
    template: site
    wait_timeout: 600
    stop_on_timeout: true

- name: Stop a task
  ramanavelineni.semaphoreui.task:
    project: homelab
    state: stopped
    task_id: "{{ started.task.id }}"
'''

RETURN = r'''
task:
  description:
    - The task as Semaphore reports it at the end of the module's run.
    - In check mode, the task that would be started, without what only Semaphore can tell.
  returned: always
  type: dict
  contains:
    id:
      description: Task id. Null in check mode for a task that would be started.
      type: int
    project:
      description: Name of the project.
      type: str
    template:
      description: Name of the template the task runs.
      type: str
    template_id:
      description: Id of that template.
      type: int
    status:
      description:
        - V(waiting), V(starting), V(running), V(stopping), V(waiting_confirmation), V(confirmed) or
          V(rejected) while the task is not over; V(success), V(error) or V(stopped) when it is.
        - Empty in check mode for a task that would be started.
      type: str
    finished:
      description: Whether the task is over, that is RV(task.status) is V(success), V(error) or V(stopped).
      type: bool
    message:
      description: The note given with O(message). Empty when there is none.
      type: str
    playbook:
      description: The file the task runs instead of the template's. Empty when it runs the template's.
      type: str
    git_branch:
      description: The branch the task asked for. Empty when it uses the template's.
      type: str
    arguments:
      description: The task's own command line arguments.
      type: list
      elements: str
    variables:
      description: The variables given with O(variables). Secret variables are not stored and not returned.
      type: dict
    task_params:
      description: The task's parameters, as given with O(task_params).
      type: dict
    inventory_id:
      description: Id of the inventory the task runs against instead of the template's. Null when it uses the template's.
      type: int
    version:
      description: The version a task of a build template builds. Empty for other tasks.
      type: str
    build_task_id:
      description: Id of the build task a deploy task deploys. Null for other tasks.
      type: int
    commit_hash:
      description: The commit the repository was at when the task ran. Empty until the task has checked it out.
      type: str
    commit_message:
      description: Message of that commit.
      type: str
    user_id:
      description: Id of the user who started the task. Null for a task a schedule or an integration started.
      type: int
    created:
      description: When the task was queued.
      type: str
    start:
      description: When the task started to run. Empty while it waits.
      type: str
    end:
      description: When the task ended. Empty while it is not over.
      type: str
    output:
      description:
        - The last O(output_lines) lines of the task's output, oldest first.
        - Empty when the module did not wait, in check mode, and with O(output_lines=0).
      type: list
      elements: str
  sample:
    id: 16
    project: homelab
    template: site
    template_id: 3
    status: success
    finished: true
    message: started by the nightly play
    playbook: ""
    git_branch: ""
    arguments: []
    variables:
      release: "1.4.2"
    task_params:
      limit: [web01, web02]
    inventory_id: null
    version: ""
    build_task_id: null
    commit_hash: 0c5f2e1b7d0a4c3e9f8b6a5d4c3b2a1f0e9d8c7b
    commit_message: Add the web role
    user_id: 1
    created: "2026-10-04T15:59:28.605950959Z"
    start: "2026-10-04T15:59:29.613908201Z"
    end: "2026-10-04T15:59:35.6184512Z"
    output:
      - Task site added to queue
      - Started task #16 of template 'site'
'''

import json

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.semaphore import (
    PROJECT_OPTIONS,
    MissingReference,
    find_by_name,
    project_ref,
    run_module,
    semaphore_argument_spec,
    semaphore_module_kwargs,
)
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.task import (
    FINAL_STATUSES,
    NEEDS_CONFIRMATION,
    get_task,
    settled_output,
    task_view,
    template_names,
    wait_for_end,
)

ANSIBLE_PARAMS = ('debug', 'debug_level', 'dry_run', 'diff', 'limit', 'tags', 'skip_tags', 'skip_galaxy_install')
TERRAFORM_PARAMS = ('plan', 'destroy', 'auto_approve', 'upgrade', 'reconfigure')
# The keys Semaphore reads for the apps it ships with. An app an administrator
# registered is not here: the module can't know what it takes.
TASK_PARAMS = dict(ansible=ANSIBLE_PARAMS, terraform=TERRAFORM_PARAMS, tofu=TERRAFORM_PARAMS,
                   terragrunt=TERRAFORM_PARAMS, bash=(), powershell=(), python=())
# A parameter of the task -> the switch in the template's task_params without
# which Semaphore drops it.
NEEDS_SWITCH = dict(debug='allow_debug', limit='allow_override_limit', tags='allow_override_tags',
                    skip_tags='allow_override_skip_tags', auto_approve='allow_auto_approve')
LIST_PARAMS = ('limit', 'tags', 'skip_tags')

EMPTY = dict(task={})


def not_allowed(template, what, switch, where='the template'):
    return ValueError('Template %r does not let a task set %s: Semaphore would ignore it. Set %s on %s first.'
                      % (template.get('name'), what, switch, where))


def task_params_body(template, given):
    """The task's `params`, checked against the template's app and against what the template allows."""
    app = template.get('app') or 'ansible'
    params = dict(given)
    if app in TASK_PARAMS:
        unknown = sorted(set(params) - set(TASK_PARAMS[app]))
        if unknown:
            raise ValueError('task_params %s are not valid for a template of app %s (valid: %s).'
                             % (', '.join(unknown), app, ', '.join(TASK_PARAMS[app]) or 'none'))
    allowed = template.get('task_params') or {}
    for name in LIST_PARAMS:
        if isinstance(params.get(name), str):
            params[name] = [params[name]]
    for name, switch in sorted(NEEDS_SWITCH.items()):
        if params.get(name) and not allowed.get(switch):
            # A template that approves by itself needs no permission for it.
            if name == 'auto_approve' and allowed.get('auto_approve'):
                continue
            raise not_allowed(template, 'task_params.%s' % name, '%s: true' % switch, "the template's task_params")
    return params


def start_body(client, base, template, params):
    """The body of the request that starts a task of `template`."""
    body = dict(template_id=template['id'])
    if params['message'] is not None:
        body['message'] = params['message']
    if params['variables'] is not None:
        # Semaphore takes both as JSON in a string.
        body['environment'] = json.dumps(params['variables'], sort_keys=True)
    if params['secret_variables'] is not None:
        body['secret'] = json.dumps(params['secret_variables'], sort_keys=True)
    if params['playbook'] is not None:
        body['playbook'] = params['playbook']
    if params['git_branch'] is not None:
        if not template.get('allow_override_branch_in_task'):
            raise not_allowed(template, 'git_branch', 'allow_override_branch_in_task: true')
        body['git_branch'] = params['git_branch']
    if params['arguments'] is not None:
        if not template.get('allow_override_args_in_task'):
            raise not_allowed(template, 'arguments', 'allow_override_args_in_task: true')
        body['arguments'] = json.dumps(params['arguments'])
    if params['inventory'] is not None:
        if (template.get('app') or 'ansible') != 'ansible':
            raise ValueError('inventory is only for a template of app ansible; %r is of app %s.'
                             % (template.get('name'), template.get('app')))
        if not (template.get('task_params') or {}).get('allow_override_inventory'):
            raise not_allowed(template, 'inventory', 'allow_override_inventory: true', "the template's task_params")
        found = find_by_name(client.list(base + '/inventory'), params['inventory'], 'inventory')
        if found is None:
            raise MissingReference('Inventory %r does not exist in this project.' % params['inventory'])
        body['inventory_id'] = found['id']
    if params['task_params'] is not None:
        body['params'] = task_params_body(template, params['task_params'])
    if params['build_task_id'] is not None:
        if template.get('type') != 'deploy':
            raise ValueError('build_task_id is only for a template of type deploy; %r is not one.' % template.get('name'))
        body['build_task_id'] = params['build_task_id']
    return body


def describe(task, template):
    return 'Task %s of template %r' % (task.get('id'), template)


def ended(module, client, base, project, names, task, changed):
    """The result for a task the module waited for, or a failure when it did not end well."""
    params = module.params
    template = names.get(task.get('template_id'))
    task, over = wait_for_end(client, base, task, params['poll_interval'], params['wait_timeout'])
    status = task.get('status')
    if not over:
        if status == NEEDS_CONFIRMATION:
            module.fail_json(
                msg='%s waits for a confirmation in Semaphore, which this module cannot give. Confirm or reject '
                    'it there. A Terraform or OpenTofu template that approves by itself (auto_approve) does not ask.'
                    % describe(task, template),
                changed=changed, task=task_view(task, project, names))
        if params['state'] == 'stopped':
            after = ' Semaphore was asked to stop it and it has not stopped yet; force: true stops it at once.'
        elif params['stop_on_timeout']:
            client.post('%s/tasks/%d/stop' % (base, task['id']), dict(force=params['force']), expected=(204,))
            after = ' Semaphore was asked to stop it.'
        else:
            after = ' It goes on in Semaphore; read it with task_info, or stop it with state: stopped.'
        module.fail_json(
            msg='%s is still %s after %d seconds (wait_timeout).%s'
                % (describe(task, template), status, params['wait_timeout'], after),
            changed=changed, task=task_view(task, project, names))
    view = task_view(task, project, names, settled_output(client, base, task['id'], params['output_lines']))
    if params['state'] == 'started' and status != 'success':
        last = (' Last line of its output: %s' % view['output'][-1]) if view['output'] else ''
        module.fail_json(
            msg='%s %s.%s' % (describe(task, template),
                              'failed (status error)' if status == 'error' else 'was stopped', last),
            changed=changed, task=view)
    return dict(changed=changed, task=view)


def start(module, client, base, project):
    params = module.params
    if params['task_id'] is not None:
        raise ValueError('task_id is only for state: stopped. A new task gets its id from Semaphore.')
    templates = client.list(base + '/templates')
    names = template_names(templates)
    template = find_by_name(templates, params['template'], 'template')
    if template is None:
        raise MissingReference('Template %r does not exist in project %r.' % (params['template'], project))
    body = start_body(client, base, template, params)
    if module.check_mode:
        # What would be sent, in the shape of a task; "secret" is not part of a task.
        return dict(changed=True, task=task_view(body, project, names))
    task = client.post(base + '/tasks', body)
    if not params['wait']:
        return dict(changed=True, task=task_view(task, project, names))
    return ended(module, client, base, project, names, task, True)


def stop(module, client, base, project):
    params = module.params
    names = template_names(client.list(base + '/templates'))
    task = get_task(client, base, params['task_id'])
    if task is None:
        raise ValueError('Task %d does not exist in project %r.' % (params['task_id'], project))
    # Asked to stop a task that is over, Semaphore sets it to "stopped", whatever it ended with.
    if task.get('status') in FINAL_STATUSES:
        return dict(changed=False, task=task_view(task, project, names))
    if module.check_mode:
        return dict(changed=True, task=task_view(task, project, names))
    client.post('%s/tasks/%d/stop' % (base, task['id']), dict(force=params['force']), expected=(204,))
    if not params['wait']:
        task = get_task(client, base, task['id']) or task
        return dict(changed=True, task=task_view(task, project, names))
    return ended(module, client, base, project, names, task, True)


def run(module, client):
    client.warn_if_untested()
    params = module.params
    if params['poll_interval'] < 1:
        raise ValueError('poll_interval must be 1 or more (seconds). Got %d.' % params['poll_interval'])
    if params['wait_timeout'] < 0:
        raise ValueError('wait_timeout must be 0 or more (seconds). Got %d.' % params['wait_timeout'])
    project_id, project = project_ref(client, params)
    base = '/project/%d' % project_id
    if params['state'] == 'stopped':
        return stop(module, client, base, project)
    return start(module, client, base, project)


def main():
    argument_spec = semaphore_argument_spec()
    argument_spec.update(
        project=dict(type='str'),
        project_id=dict(type='int'),
        state=dict(type='str', choices=['started', 'stopped'], default='started'),
        template=dict(type='str'),
        task_id=dict(type='int'),
        message=dict(type='str'),
        variables=dict(type='dict'),
        secret_variables=dict(type='dict', no_log=True),
        playbook=dict(type='str'),
        git_branch=dict(type='str'),
        arguments=dict(type='list', elements='str'),
        inventory=dict(type='str'),
        task_params=dict(type='dict'),
        build_task_id=dict(type='int'),
        wait=dict(type='bool', default=True),
        wait_timeout=dict(type='int', default=1800),
        poll_interval=dict(type='int', default=5),
        stop_on_timeout=dict(type='bool', default=False),
        force=dict(type='bool', default=False),
        output_lines=dict(type='int', default=200),
    )
    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        **semaphore_module_kwargs(
            mutually_exclusive=[PROJECT_OPTIONS],
            required_one_of=[PROJECT_OPTIONS],
            required_if=[('state', 'started', ('template',)), ('state', 'stopped', ('task_id',))],
        )
    )
    run_module(module, lambda client: run(module, client), placeholder=EMPTY)


if __name__ == '__main__':
    main()
