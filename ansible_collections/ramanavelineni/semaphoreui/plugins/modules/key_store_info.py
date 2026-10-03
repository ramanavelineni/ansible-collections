#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: key_store_info
short_description: List the keys in a Semaphore UI project's Key Store
version_added: 0.1.0
description:
  - Lists a project's keys, optionally only the one with a given name, with the repositories
    that use each key. Semaphore never returns secrets, so none are listed.
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
      - Only return keys with this name.
    type: str
'''

EXAMPLES = r'''
- name: List the homelab project's keys
  ramanavelineni.semaphoreui.key_store_info:
    project: homelab
  register: result
'''

RETURN = r'''
key_store:
  description:
    - Matching keys, sorted by name.
    - Named C(key_store) rather than C(keys), which would clash with Jinja's C(dict.keys).
  returned: always
  type: list
  elements: dict
  contains:
    id:
      description: Key id.
      type: int
    name:
      description: Key name.
      type: str
    type:
      description: Key type (V(ssh), V(login_password) or V(none)).
      type: str
    project_id:
      description: Id of the project.
      type: int
    repositories:
      description: Names of the repositories that use the key.
      type: list
      elements: str
  sample:
    - id: 4
      name: github-deploy
      type: ssh
      project_id: 1
      repositories: [ansible]
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.semaphore import (
    PROJECT_OPTIONS,
    project_ref,
    run_module,
    semaphore_argument_spec,
    semaphore_module_kwargs,
)


def list_keys(module, client):
    client.warn_if_untested()
    project_id = project_ref(client, module.params)[0]
    base = '/project/%d' % project_id
    repos = client.list(base + '/repositories')
    keys = []
    for key in client.list(base + '/keys'):
        if module.params['name'] is not None and key.get('name') != module.params['name']:
            continue
        keys.append(dict(
            id=key.get('id'), name=key.get('name'), type=key.get('type'), project_id=project_id,
            repositories=sorted(r['name'] for r in repos if r.get('ssh_key_id') == key.get('id'))))
    return dict(changed=False, key_store=sorted(keys, key=lambda k: (k['name'] or '', k['id'] or 0)))


def main():
    argument_spec = semaphore_argument_spec()
    argument_spec.update(
        project=dict(type='str'),
        project_id=dict(type='int'),
        name=dict(type='str'),
    )
    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        **semaphore_module_kwargs(mutually_exclusive=[PROJECT_OPTIONS], required_one_of=[PROJECT_OPTIONS])
    )
    run_module(module, lambda client: list_keys(module, client))


if __name__ == '__main__':
    main()
