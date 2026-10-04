#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: project_restore
short_description: Create a Semaphore UI project from a backup
version_added: 0.4.0
description:
  - Creates a project from a backup, as B(Restore Project) in the UI does. The backup comes from
    M(ramanavelineni.semaphoreui.project_backup) or from the UI.
  - Restoring always creates a new project. B(When a project of that name exists already, the module does
    nothing) and reports no change. It does not compare that project with the backup.
  - B(A backup holds no secrets), so the keys of the restored project are empty, and the secret variables of
    its variable groups are gone. Set them afterwards, for example with
    M(ramanavelineni.semaphoreui.key_store) and M(ramanavelineni.semaphoreui.variable_group).
  - The user the module logs in as becomes the owner of the new project. Other team members are not part of
    a backup.
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
  src:
    description:
      - File that holds the backup as JSON, on the host the module runs on.
      - Mutually exclusive with O(backup); one of the two is required.
    type: path
  backup:
    description:
      - The backup itself, for example RV(ramanavelineni.semaphoreui.project_backup#module:backup).
      - Mutually exclusive with O(src); one of the two is required.
    type: dict
  name:
    description:
      - Name of the project to create. Defaults to the name in the backup.
      - Use it to restore a backup next to the project it was taken from.
    type: str
notes:
  - Restoring needs an administrator, unless the server lets every user create projects.
  - Semaphore checks a backup before it creates anything, but a failure after that leaves the new project
    behind, half filled. The module says so when that happens; delete the project with
    M(ramanavelineni.semaphoreui.project) before running the task again.
  - Schedules are restored as they were, active ones included.
  - Semaphore lists at most 200 projects. When the list is that long the module fails instead of risking a
    second project of the same name.
seealso:
  - module: ramanavelineni.semaphoreui.project_backup
    description: Reads a project's backup and writes it to a file.
  - module: ramanavelineni.semaphoreui.project
    description: Manages the project.
  - module: ramanavelineni.semaphoreui.key_store
    description: Sets the secrets of the restored keys.
'''

EXAMPLES = r'''
# The connection options (url and api_token, or username and password) are left out here. Set them once
# with module_defaults, or in the SEMAPHORE_URL and SEMAPHORE_API_TOKEN environment variables; the
# collection's README shows both under "Connecting".

- name: Restore the homelab project if it is not there
  ramanavelineni.semaphoreui.project_restore:
    src: /var/backups/semaphore/homelab.json

- name: Copy a project under another name
  ramanavelineni.semaphoreui.project_restore:
    backup: "{{ homelab_backup.backup }}"
    name: homelab-copy
'''

RETURN = r'''
project:
  description:
    - The project of that name, in the form M(ramanavelineni.semaphoreui.project) returns it. It is the new
      project when one was created, and the existing one otherwise.
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
    id: 2
    name: homelab
    alert: false
    alert_chat: ""
    max_parallel_tasks: 0
    type: ""
'''

import copy
import json

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.semaphore import (
    SemaphoreError,
    find_by_name,
    project_view,
    run_module,
    semaphore_argument_spec,
    semaphore_module_kwargs,
)


def load(params):
    """The backup a task names, with the project name the task asks for."""
    if params['src'] is not None:
        try:
            with open(params['src'], encoding='utf-8') as f:
                backup = json.load(f)
        except OSError as e:
            raise ValueError('Cannot read src %r on the host this module runs on: %s' % (params['src'], e))
        except ValueError as e:
            raise ValueError('src %r does not hold JSON: %s' % (params['src'], e))
        where = 'src %r' % params['src']
    else:
        backup = copy.deepcopy(params['backup'])
        where = 'backup'
    meta = backup.get('meta') if isinstance(backup, dict) else None
    if not isinstance(meta, dict):
        raise ValueError('%s is not a Semaphore project backup: it has no "meta" section.' % where)
    if params['name'] is not None:
        meta['name'] = params['name']
    # Semaphore would take a backup without a name, and create a project with an empty one.
    if not isinstance(meta.get('name'), str) or not meta['name'].strip():
        raise ValueError('%s names no project (meta.name), and the task gives no name.' % where)
    return backup


def what_is_left(client, name, error):
    """What a failed restore left on the server, for the failure message."""
    if 'already exists' in (error.response or ''):
        # Semaphore's own check of the name: the project appeared after this task looked for it.
        return 'Nothing was created. Run the task again; it then finds the project and leaves it alone.'
    try:
        left = find_by_name(client.list('/projects'), name, 'project')
    except (SemaphoreError, ValueError):
        return 'Whether a project %r was left behind could not be checked.' % name
    if left:
        return ('Semaphore created project %r (id %s) before it failed, and left it half filled. Delete it before '
                'running this task again.' % (name, left.get('id')))
    return ('Nothing was created. Semaphore refuses a backup in which something refers to a name that is not in it, '
            'or that is not in the form its version writes.')


def restore(module, client):
    client.warn_if_untested()
    backup = load(module.params)
    name = backup['meta']['name']

    existing = find_by_name(client.list('/projects', capped=True), name, 'project')
    if existing:
        view = project_view(existing)
        return dict(changed=False, project=view, diff=dict(before=view, after=view))

    if module.check_mode:
        after = project_view(backup['meta'])
        after.pop('id')
        return dict(changed=True, project=after, diff=dict(before={}, after=after))

    try:
        created = client.post('/projects/restore', backup, expected=(200,))
    except SemaphoreError as error:
        module.fail_json(msg='%s %s' % (error.message(), what_is_left(client, name, error)),
                         request_details=error.details())
    after = project_view(created or {})
    return dict(changed=True, project=after, diff=dict(before={}, after=after))


def main():
    argument_spec = semaphore_argument_spec()
    argument_spec.update(
        src=dict(type='path'),
        backup=dict(type='dict'),
        name=dict(type='str'),
    )
    module = AnsibleModule(
        argument_spec=argument_spec, supports_check_mode=True,
        **semaphore_module_kwargs(mutually_exclusive=[('src', 'backup')], required_one_of=[('src', 'backup')])
    )
    run_module(module, lambda client: restore(module, client))


if __name__ == '__main__':
    main()
