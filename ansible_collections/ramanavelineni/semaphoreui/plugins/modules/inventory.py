#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: inventory
short_description: Manage inventories in a Semaphore UI project
version_added: 0.1.0
description:
  - Creates, updates or deletes an Ansible inventory in a project, found by its name.
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
  project:
    description:
      - Name of the project the inventory belongs to.
      - Mutually exclusive with O(project_id); one of the two is required.
    type: str
  project_id:
    description:
      - Id of the project, as an alternative to O(project).
      - With it the list of projects is not read, so a project is found on a server with 200 or more
        projects too. Semaphore cuts that list off at 200, and O(project) fails there.
      - Mutually exclusive with O(project). One of the two is required.
    type: int
    version_added: 0.3.0
  name:
    description:
      - Name of the inventory. Inventories are looked up by this name within the project.
    type: str
    required: true
  state:
    description:
      - V(present) creates the inventory or updates it to match.
      - V(absent) deletes it. It fails, listing them, while templates or other objects still use it.
    type: str
    choices: [present, absent]
    default: present
  type:
    description:
      - V(file) reads the inventory from a file, V(static) takes INI content, V(static-yaml) YAML content.
      - Required to create the inventory.
    type: str
    choices: [file, static, static-yaml]
  inventory:
    description:
      - For V(file), the path of the inventory file. With O(repository) it is relative to that
        repository; without, it is a path on the Semaphore server.
      - For V(static) and V(static-yaml), the inventory content itself.
      - This is not a secret option. Static content appears in the task's result and in the diff, so a
        password in it (C(ansible_password), for example) does too. Keep passwords in the Key Store
        (O(ssh_key), O(become_key)), or set C(no_log) on the task.
      - Required to create the inventory.
    type: str
  repository:
    description:
      - Name of the project repository a V(file) inventory is read from.
      - An empty string removes the repository.
    type: str
  ssh_key:
    description:
      - Name of the key in the project's Key Store that Ansible connects to hosts with.
      - An empty string removes the key.
    type: str
  become_key:
    description:
      - Name of a V(login_password) key with the password for privilege escalation (sudo).
      - Leave it unset when hosts allow passwordless sudo. An empty string removes the key.
    type: str
notes:
  - Semaphore rejects every B(update) of a V(file) inventory whose path is outside its own working
    directory, which includes any absolute path, although it accepts such a path on create. The
    module fails with an explanation when that happens; move the file below Semaphore's working
    directory, or delete the inventory and create it again.
seealso:
  - module: ramanavelineni.semaphoreui.inventory_info
    description: Reads inventories without changing them.
  - module: ramanavelineni.semaphoreui.repository
    description: Manages the repository a file inventory is read from.
  - module: ramanavelineni.semaphoreui.key_store
    description: Manages the keys an inventory uses.
  - module: ramanavelineni.semaphoreui.project
    description: Manages the project.
'''

EXAMPLES = r'''
# The connection options (url and api_token, or username and password) are left out here. Set them once
# with module_defaults, or in the SEMAPHORE_URL and SEMAPHORE_API_TOKEN environment variables; the
# collection's README shows both under "Connecting".

- name: Inventory file from a repository
  ramanavelineni.semaphoreui.inventory:
    project: homelab
    name: homelab
    type: file
    inventory: inventories/homelab/hosts
    repository: ansible
    ssh_key: hosts

- name: Static inventory with a sudo password
  ramanavelineni.semaphoreui.inventory:
    project: homelab
    name: lab
    type: static
    inventory: |
      [lab]
      lab01.example.com
    ssh_key: hosts
    become_key: sudo
'''

RETURN = r'''
inventory:
  description:
    - The inventory after the change, or as it would be in check mode, with the names of the
      repository and keys it refers to.
    - Empty after a deletion.
  returned: always
  type: dict
  contains:
    id:
      description: Inventory id.
      type: int
    name:
      description: Name of the inventory.
      type: str
    type:
      description: Inventory type, as Semaphore reports it (V(file), V(static), V(static-yaml), or a workspace type).
      type: str
    inventory:
      description: Path of the inventory file, or the inventory content for the static types.
      type: str
    repository:
      description: Name of the repository a file inventory is read from. Null when there is none.
      type: str
    repository_id:
      description: Id of that repository. Null when there is none.
      type: int
    ssh_key:
      description: Name of the key Ansible connects to hosts with. Null when there is none.
      type: str
    ssh_key_id:
      description: Id of that key. Null when there is none.
      type: int
    become_key:
      description: Name of the key with the password for privilege escalation. Null when there is none.
      type: str
    become_key_id:
      description: Id of that key. Null when there is none.
      type: int
    project_id:
      description: Id of the project.
      type: int
  sample:
    id: 1
    name: homelab
    type: file
    inventory: inventories/homelab/hosts
    repository: ansible
    repository_id: 1
    ssh_key: hosts
    ssh_key_id: 4
    become_key: null
    become_key_id: null
    project_id: 1
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.semaphore import (
    INVENTORY_REFERENCES,
    MissingReference,
    PROJECT_OPTIONS,
    diff_fields,
    find_by_name,
    inventory_view,
    project_ref,
    refuse_delete_if_used,
    run_module,
    semaphore_argument_spec,
    semaphore_module_kwargs,
)


def ensure(module, client):
    params = module.params
    client.warn_if_untested()

    project_id, project = project_ref(client, params, missing_ok=params['state'] == 'absent')
    if project_id is None:
        # The project is gone, and everything in it went with it.
        return dict(changed=False, inventory={}, diff=dict(before={}, after={}))
    base = '/project/%d' % project_id
    current = find_by_name(client.list(base + '/inventory'), params['name'], 'inventory')

    if params['state'] == 'absent' and not current:
        return dict(changed=False, inventory={}, diff=dict(before={}, after={}))

    lists = dict(keys=client.list(base + '/keys'), repositories=client.list(base + '/repositories'))
    names = dict((endpoint, dict((o['id'], o['name']) for o in items)) for endpoint, items in lists.items())

    if params['state'] == 'absent':
        refuse_delete_if_used(client, '%s/inventory/%d' % (base, current['id']), 'inventory', params['name'])
        if not module.check_mode:
            client.delete('%s/inventory/%d' % (base, current['id']))
        return dict(changed=True, inventory={}, diff=dict(before=inventory_view(current, names), after={}))

    desired = dict(type=params['type'], inventory=params['inventory'])
    for option, (field, what, endpoint) in INVENTORY_REFERENCES.items():
        value = params[option]
        if value is None:
            desired[field] = None
        elif value == '':
            desired[field] = 0
        else:
            found = find_by_name(lists[endpoint], value, what)
            if found is None:
                raise MissingReference('%s %r does not exist in project %r.' % (what.capitalize(), value, project))
            desired[field] = found['id']

    if not current:
        missing = [o for o in ('type', 'inventory') if params[o] is None]
        if missing:
            raise ValueError('Creating inventory %r needs %s.' % (params['name'], ', '.join(missing)))
        body = dict(project_id=project_id, name=params['name'], type=params['type'], inventory=params['inventory'])
        for option, (field, dummy, dummy2) in INVENTORY_REFERENCES.items():
            body[field] = desired[field] or None
        after = inventory_view(body, names)
        after.pop('id')
        if not module.check_mode:
            after = inventory_view(client.post(base + '/inventory', body), names)
        return dict(changed=True, inventory=after, diff=dict(before={}, after=after))

    before = inventory_view(current, names)
    comparable = dict(before)
    for option, (field, dummy, dummy2) in INVENTORY_REFERENCES.items():
        comparable[field] = before[field] or 0
    changed = diff_fields(desired, comparable)
    if not changed:
        return dict(changed=False, inventory=before, diff=dict(before=before, after=before))

    body = dict(current)
    body.update(id=current['id'], project_id=project_id, name=params['name'])
    for key in changed:
        body[key] = desired[key] if key in ('type', 'inventory') else (desired[key] or None)
    after = inventory_view(body, names)

    if body.get('type') == 'file' and (body.get('inventory') or '').startswith('/'):
        raise ValueError(
            'Semaphore rejects every update of a file inventory whose path is outside its working '
            'directory, and %r is at %r. Move the file below Semaphore\'s working directory (or read '
            'it from a repository with a relative path), or delete the inventory and create it again.'
            % (params['name'], body.get('inventory')))

    if not module.check_mode:
        # The update writes every column (name, type, runner_tag, keys,
        # content, template_id, repository_id), so the whole current row goes
        # back with the changes applied.
        client.put('%s/inventory/%d' % (base, current['id']), body)
    return dict(changed=True, inventory=after, diff=dict(before=before, after=after))


def main():
    argument_spec = semaphore_argument_spec()
    argument_spec.update(
        project=dict(type='str'),
        project_id=dict(type='int'),
        name=dict(type='str', required=True),
        state=dict(type='str', default='present', choices=['present', 'absent']),
        type=dict(type='str', choices=['file', 'static', 'static-yaml']),
        inventory=dict(type='str'),
        repository=dict(type='str'),
        ssh_key=dict(type='str', no_log=False),
        become_key=dict(type='str', no_log=False),
    )
    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        **semaphore_module_kwargs(mutually_exclusive=[PROJECT_OPTIONS], required_one_of=[PROJECT_OPTIONS])
    )
    run_module(module, lambda client: ensure(module, client), placeholder=dict(inventory={}))


if __name__ == '__main__':
    main()
