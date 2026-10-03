#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: project
short_description: Manage Semaphore UI projects
version_added: 0.1.0
description:
  - Creates, updates or deletes a Semaphore UI project, found by its name.
  - Only the options you set are compared and changed; the others keep their current value.
author:
  - ramanavelineni (@ramanavelineni)
extends_documentation_fragment:
  - ramanavelineni.semaphoreui.auth
  - ramanavelineni.semaphoreui.attributes
attributes:
  check_mode:
    support: full
  diff_mode:
    support: full
options:
  name:
    description:
      - Name of the project. Projects are looked up by this name.
      - Renaming is not supported. A different name is a different project.
    type: str
    required: true
  state:
    description:
      - V(present) creates the project or updates it to match.
      - V(absent) deletes the project and B(everything in it). It requires O(confirm_delete=true).
    type: str
    choices: [present, absent]
    default: present
  alert:
    description:
      - Whether the project sends alerts about its tasks.
      - Defaults to V(false) for a new project.
    type: bool
  alert_chat:
    description:
      - Chat id (Telegram or Slack) for alerts, used when O(alert=true).
    type: str
  max_parallel_tasks:
    description:
      - How many tasks of this project may run at once. V(0) means no limit.
      - Defaults to V(0) for a new project.
    type: int
  confirm_delete:
    description:
      - Must be V(true) for O(state=absent) to delete the project.
      - Deleting a project deletes all its keys, repositories, inventories, variable groups,
        templates, schedules and task history.
    type: bool
    default: false
notes:
  - Semaphore adds the user that creates a project as its owner, and creates a key named C(None)
    and a view named C(All) in it.
  - Semaphore lists at most 200 projects. When the list is that long the module fails instead of
    risking a duplicate.
'''

EXAMPLES = r'''
- name: Create the homelab project
  ramanavelineni.semaphoreui.project:
    url: https://semaphore.example.com
    username: admin
    password: "{{ semaphore_admin_password }}"
    name: homelab
    max_parallel_tasks: 0

- name: Delete a project and everything in it
  ramanavelineni.semaphoreui.project:
    url: https://semaphore.example.com
    api_token: "{{ semaphore_api_token }}"
    name: scratch
    state: absent
    confirm_delete: true
'''

RETURN = r'''
project:
  description:
    - The project after the change, or as it would be in check mode.
    - Empty after a deletion.
  returned: always
  type: dict
  contains:
    id:
      description: Project id. Absent when a project would be created in check mode.
      type: int
      returned: when the project exists
    name:
      description: Project name.
      type: str
    alert:
      description: Whether alerts are on.
      type: bool
    alert_chat:
      description: Chat id for alerts, empty when not set.
      type: str
    max_parallel_tasks:
      description: Task limit, V(0) for none.
      type: int
    type:
      description: Project type as Semaphore reports it.
      type: str
  sample:
    id: 1
    name: homelab
    alert: false
    alert_chat: ""
    max_parallel_tasks: 0
    type: ""
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.semaphore import (
    diff_fields,
    find_by_name,
    project_view,
    run_module,
    semaphore_argument_spec,
    semaphore_module_kwargs,
)

MANAGED = ('alert', 'alert_chat', 'max_parallel_tasks')


def ensure(module, client):
    params = module.params
    client.warn_if_untested()

    current = find_by_name(client.list('/projects', capped=True), params['name'], 'project')
    before = project_view(current) if current else {}

    if params['state'] == 'absent':
        if not current:
            return dict(changed=False, project={}, diff=dict(before={}, after={}))
        if not params['confirm_delete']:
            raise ValueError(
                'Refusing to delete project %r: that deletes everything in it. Set '
                'confirm_delete: true to delete it.' % params['name'])
        if not module.check_mode:
            client.delete('/project/%d' % current['id'])
        return dict(changed=True, project={}, diff=dict(before=before, after={}))

    desired = dict((k, params[k]) for k in MANAGED)

    if not current:
        after = project_view(dict(name=params['name'], **dict((k, v) for k, v in desired.items() if v is not None)))
        after.pop('id')
        if not module.check_mode:
            body = dict(name=params['name'], alert=after['alert'], max_parallel_tasks=after['max_parallel_tasks'])
            if after['alert_chat']:
                body['alert_chat'] = after['alert_chat']
            after = project_view(client.post('/projects', body))
        return dict(changed=True, project=after, diff=dict(before={}, after=after))

    changed = diff_fields(desired, before)
    if not changed:
        return dict(changed=False, project=before, diff=dict(before=before, after=before))

    after = dict(before)
    after.update((k, desired[k]) for k in changed)
    if not module.check_mode:
        # The update rewrites name, alert, alert_chat and max_parallel_tasks
        # together, and the handler rejects a body whose id differs from the
        # URL's, so the whole object is always sent.
        client.put('/project/%d' % current['id'], dict(
            id=current['id'],
            name=after['name'],
            alert=after['alert'],
            alert_chat=after['alert_chat'],
            max_parallel_tasks=after['max_parallel_tasks'],
        ))
    return dict(changed=True, project=after, diff=dict(before=before, after=after))


def main():
    argument_spec = semaphore_argument_spec()
    argument_spec.update(
        name=dict(type='str', required=True),
        state=dict(type='str', default='present', choices=['present', 'absent']),
        alert=dict(type='bool'),
        alert_chat=dict(type='str'),
        max_parallel_tasks=dict(type='int'),
        confirm_delete=dict(type='bool', default=False),
    )
    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        **semaphore_module_kwargs()
    )
    run_module(module, lambda client: ensure(module, client))


if __name__ == '__main__':
    main()
