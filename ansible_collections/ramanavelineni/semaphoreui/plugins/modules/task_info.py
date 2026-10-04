#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: task_info
short_description: Read Semaphore UI tasks and their output
version_added: 0.4.0
description:
  - Returns one task by its id, or the most recent tasks of a project or of one of its templates,
    newest first. A task is one run of a template.
  - With O(output_lines) the output of each returned task is read too.
  - Use it to follow a task that M(ramanavelineni.semaphoreui.task) started with C(wait=false).
author:
  - ramanavelineni (@ramanavelineni)
extends_documentation_fragment:
  - ramanavelineni.semaphoreui.auth
  - ramanavelineni.semaphoreui.attributes
attributes:
  check_mode:
    support: full
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
  task_id:
    description:
      - Only return the task with this id. RV(tasks) is empty when the project has no such task.
      - Mutually exclusive with O(template).
    type: int
  template:
    description:
      - Only return tasks of the template with this name.
      - Mutually exclusive with O(task_id).
    type: str
  limit:
    description:
      - How many tasks to return at most, from 1 to 200. Semaphore returns no more than 200 for one
        request. Not used with O(task_id).
    type: int
    default: 20
  output_lines:
    description:
      - How many of the last lines of each task's output to return in C(output).
      - V(0) returns none and does not read the output. V(-1) returns all of it.
      - The output costs one request for every returned task.
    type: int
    default: 0
notes:
  - A task's output is whatever the playbook or script printed. Semaphore masks the secrets it
    knows there, but a playbook can print anything. Set C(no_log) on the task where the output
    may hold something secret.
  - The last lines of a task's output can reach Semaphore's store a moment after the task's
    final status.
seealso:
  - module: ramanavelineni.semaphoreui.task
    description: Starts and stops tasks.
  - module: ramanavelineni.semaphoreui.template_info
    description: Reads the templates tasks are runs of.
  - module: ramanavelineni.semaphoreui.project
    description: Manages the project.
'''

EXAMPLES = r'''
# The connection options (url and api_token, or username and password) are left out here. Set them once
# with module_defaults, or in the SEMAPHORE_URL and SEMAPHORE_API_TOKEN environment variables; the
# collection's README shows both under "Connecting".

- name: The last five runs of the site template
  ramanavelineni.semaphoreui.task_info:
    project: homelab
    template: site
    limit: 5
  register: result

- name: Fail when the newest one did not succeed
  ansible.builtin.assert:
    that: result.tasks[0].status == 'success'

- name: Wait for a task that was started with wait false
  ramanavelineni.semaphoreui.task_info:
    project: homelab
    task_id: 16
    output_lines: 50
  register: result
  until: result.tasks[0].finished
  retries: 60
  delay: 10
'''

RETURN = r'''
tasks:
  description:
    - Matching tasks, newest first.
  returned: always
  type: list
  elements: dict
  contains:
    id:
      description: Task id.
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
      type: str
    finished:
      description: Whether the task is over, that is its status is V(success), V(error) or V(stopped).
      type: bool
    message:
      description: The note given when the task was started. Empty when there is none.
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
      description: The variables the task was started with. Secret variables are not stored and not returned.
      type: dict
    task_params:
      description: The task's parameters, for example C(limit) or C(dry_run).
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
      description: The last O(output_lines) lines of the task's output, oldest first. Empty with O(output_lines=0).
      type: list
      elements: str
  sample:
    - id: 16
      project: homelab
      template: site
      template_id: 3
      status: success
      finished: true
      message: started by the nightly play
      playbook: ""
      git_branch: ""
      arguments: []
      variables: {}
      task_params: {}
      inventory_id: null
      version: ""
      build_task_id: null
      commit_hash: 0c5f2e1b7d0a4c3e9f8b6a5d4c3b2a1f0e9d8c7b
      commit_message: Add the web role
      user_id: 1
      created: "2026-10-04T15:59:28.605950959Z"
      start: "2026-10-04T15:59:29.613908201Z"
      end: "2026-10-04T15:59:35.6184512Z"
      output: []
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.semaphore import (
    PROJECT_OPTIONS,
    find_by_name,
    project_ref,
    run_module,
    semaphore_argument_spec,
    semaphore_module_kwargs,
)
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.task import (
    LIST_LIMIT,
    get_task,
    read_output,
    task_view,
    template_names,
)


def list_tasks(module, client):
    client.warn_if_untested()
    params = module.params
    if not 1 <= params['limit'] <= LIST_LIMIT:
        raise ValueError('limit must be between 1 and %d. Got %d.' % (LIST_LIMIT, params['limit']))
    project_id, project = project_ref(client, params)
    base = '/project/%d' % project_id
    templates = client.list(base + '/templates')
    if params['task_id'] is not None:
        task = get_task(client, base, params['task_id'])
        tasks = [task] if task else []
    elif params['template'] is not None:
        template = find_by_name(templates, params['template'], 'template')
        if template is None:
            raise ValueError('Template %r does not exist in project %r.' % (params['template'], project))
        tasks = client.list('%s/templates/%d/tasks/last?limit=%d' % (base, template['id'], params['limit']))
    else:
        tasks = client.list('%s/tasks/last?limit=%d' % (base, params['limit']))
    names = template_names(templates)
    # Newest first is how Semaphore answers; the ids say the same, should a version not.
    tasks = sorted(tasks, key=lambda t: t.get('id') or 0, reverse=True)[:params['limit']]
    return dict(changed=False, tasks=[
        task_view(task, project, names, read_output(client, base, task['id'], params['output_lines']))
        for task in tasks])


def main():
    argument_spec = semaphore_argument_spec()
    argument_spec.update(
        project=dict(type='str'),
        project_id=dict(type='int'),
        task_id=dict(type='int'),
        template=dict(type='str'),
        limit=dict(type='int', default=20),
        output_lines=dict(type='int', default=0),
    )
    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        **semaphore_module_kwargs(
            mutually_exclusive=[PROJECT_OPTIONS, ('task_id', 'template')],
            required_one_of=[PROJECT_OPTIONS],
        )
    )
    run_module(module, lambda client: list_tasks(module, client))


if __name__ == '__main__':
    main()
