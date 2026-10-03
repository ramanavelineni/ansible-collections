#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: inventory_info
short_description: List the inventories in a Semaphore UI project
version_added: 0.1.0
description:
  - Lists a project's inventories, optionally only the one with a given name, with the names of
    the repository and keys each one uses.
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
    version_added: 0.3.0
  name:
    description:
      - Only return inventories with this name.
    type: str
'''

EXAMPLES = r'''
- name: List the homelab project's inventories
  ramanavelineni.semaphoreui.inventory_info:
    project: homelab
  register: result
'''

RETURN = r'''
inventories:
  description: Matching inventories, sorted by name, in the form the M(ramanavelineni.semaphoreui.inventory) module
    returns, with the names of the repository (C(repository)) and keys (C(ssh_key), C(become_key)) they refer to.
  returned: always
  type: list
  elements: dict
  sample:
    - id: 1
      name: homelab
      type: file
      inventory: inventories/homelab/hosts
      repository_id: 1
      repository: ansible
      ssh_key_id: 4
      ssh_key: hosts
      become_key_id: null
      become_key: null
      project_id: 1
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.semaphore import (
    PROJECT_OPTIONS,
    inventory_view,
    project_ref,
    run_module,
    semaphore_argument_spec,
    semaphore_module_kwargs,
)


def list_inventories(module, client):
    client.warn_if_untested()
    base = '/project/%d' % project_ref(client, module.params)[0]
    names = dict((endpoint, dict((o['id'], o['name']) for o in client.list('%s/%s' % (base, endpoint))))
                 for endpoint in ('keys', 'repositories'))
    out = []
    for inv in client.list(base + '/inventory'):
        if module.params['name'] is not None and inv.get('name') != module.params['name']:
            continue
        out.append(inventory_view(inv, names))
    return dict(changed=False, inventories=sorted(out, key=lambda i: (i.get('name') or '', i.get('id') or 0)))


def main():
    argument_spec = semaphore_argument_spec()
    argument_spec.update(project=dict(type='str'), project_id=dict(type='int'), name=dict(type='str'))
    module = AnsibleModule(
        argument_spec=argument_spec, supports_check_mode=True,
        **semaphore_module_kwargs(mutually_exclusive=[PROJECT_OPTIONS], required_one_of=[PROJECT_OPTIONS])
    )
    run_module(module, lambda client: list_inventories(module, client))


if __name__ == '__main__':
    main()
