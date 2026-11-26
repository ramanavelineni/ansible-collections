#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: role_info
short_description: List Harbor's project roles
version_added: 0.10.0
description:
  - Lists the project roles (Administration > Roles), the five built-in ones and the custom ones, optionally only
    the one with a given name.
  - Custom roles are new in Harbor 2.16; on an older Harbor the module fails.
author:
  - ramanavelineni (@ramanavelineni)
extends_documentation_fragment:
  - ramanavelineni.harbor.auth
  - ramanavelineni.harbor.attributes
attributes:
  check_mode:
    support: full
  diff_mode:
    support: none
options:
  name:
    description:
      - Only return the role with this name, Harbor's name of it (V(projectAdmin) for a built-in role).
    type: str
  custom_only:
    description:
      - Leave out the built-in roles.
    type: bool
    default: false
notes:
  - Any logged-in user may read the roles.
seealso:
  - module: ramanavelineni.harbor.role
    description: Manage custom project roles.
'''

EXAMPLES = r'''
# The connection options (url, username, password) can be set once instead of on every task, with
# module_defaults for the group/ramanavelineni.harbor.harbor action group, or with the HARBOR_URL,
# HARBOR_USERNAME and HARBOR_PASSWORD environment variables.

- name: List the custom roles
  ramanavelineni.harbor.role_info:
    url: https://harbor.example.com
    username: admin
    password: "{{ harbor_admin_password }}"
    custom_only: true
  register: result
'''

RETURN = r'''
roles:
  description: Matching roles, the built-in ones first, each group sorted by name.
  returned: always
  type: list
  elements: dict
  sample:
    - id: 1
      name: projectAdmin
      description: ""
      builtin: true
      member_role: project_admin
      permissions: [{resource: "", action: read}, {resource: member, action: create}]
    - id: 6
      name: ci-deployer
      description: CI pipelines
      builtin: false
      member_role: ci-deployer
      permissions: [{resource: repository, action: pull}, {resource: repository, action: push}]
  contains:
    id:
      description: Harbor's id of the role. The built-in roles have ids 1 to 5, custom roles 6 and up.
      type: int
    name:
      description: Harbor's name of the role.
      type: str
    description:
      description: Description, empty when there is none.
      type: str
    builtin:
      description: Whether this is one of Harbor's built-in roles, which cannot be changed.
      type: bool
    member_role:
      description: What O(ramanavelineni.harbor.project_member#module:role) takes for this role.
      type: str
    permissions:
      description:
        - The role's permissions as resource and action pairs, sorted. An empty resource is the project itself.
      type: list
      elements: dict
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.harbor.plugins.module_utils.harbor import (
    harbor_argument_spec,
    require_custom_roles,
    role_view,
    run_module,
)


def list_roles(module, client):
    client.warn_if_untested()
    require_custom_roles(client)
    out = [role_view(r) for r in client.list('/roles')
           if (module.params['name'] is None or r.get('name') == module.params['name'])
           and not (module.params['custom_only'] and r.get('is_builtin'))]
    return dict(changed=False, roles=sorted(out, key=lambda r: (not r['builtin'], r['name'] or '')))


def main():
    argument_spec = harbor_argument_spec()
    argument_spec.update(name=dict(type='str'), custom_only=dict(type='bool', default=False))
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)
    run_module(module, lambda client: list_roles(module, client))


if __name__ == '__main__':
    main()
