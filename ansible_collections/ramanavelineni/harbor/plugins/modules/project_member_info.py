#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: project_member_info
short_description: List the members of a Harbor project
version_added: 0.6.0
description:
  - Lists a project's members, users and groups, with their roles; optionally only those with a given name.
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
  project:
    description:
      - Name of the project.
    type: str
    required: true
  name:
    description:
      - Only return the members with this name, users and groups alike.
    type: str
notes:
  - A group's type comes from Harbor's user groups, which only a system administrator may read. For anyone
    else C(group_type) is V(null).
seealso:
  - module: ramanavelineni.harbor.project_member
    description: Manage a project's members.
'''

EXAMPLES = r'''
# The connection options (url, username, password) can be set once instead of on every task, with
# module_defaults for the group/ramanavelineni.harbor.harbor action group, or with the HARBOR_URL,
# HARBOR_USERNAME and HARBOR_PASSWORD environment variables.

- name: List the members of the apps project
  ramanavelineni.harbor.project_member_info:
    url: https://harbor.example.com
    username: admin
    password: "{{ harbor_admin_password }}"
    project: apps
  register: result
'''

RETURN = r'''
members:
  description: Matching members, users first, each kind sorted by name.
  returned: always
  type: list
  elements: dict
  sample:
    - id: 1
      project: apps
      project_id: 2
      user: admin
      group: null
      group_type: null
      role: project_admin
      role_id: 1
    - id: 7
      project: apps
      project_id: 2
      user: null
      group: harbor-readonly
      group_type: oidc
      role: guest
      role_id: 3
  contains:
    id:
      description: Harbor's id of the membership.
      type: int
    project:
      description: Name of the project.
      type: str
    project_id:
      description: Harbor's id of the project.
      type: int
    user:
      description: Name of the user, V(null) for a group.
      type: str
    group:
      description: Name of the group, V(null) for a user.
      type: str
    group_type:
      description: V(oidc), V(ldap) or V(http) for a group; V(null) for a user, or when the type can't be read.
      type: str
    role:
      description: The member's role, V(null) for a role id this collection doesn't know.
      type: str
    role_id:
      description: Harbor's id of the role.
      type: int
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.harbor.plugins.module_utils.harbor import (
    group_type_name,
    harbor_argument_spec,
    member_view,
    require_project,
    run_module,
    user_groups,
)


def list_members(module, client):
    client.warn_if_untested()
    name = module.params['project']
    project = require_project(client, name)
    members = [m for m in client.list('/projects/%d/members' % project['project_id'])
               if module.params['name'] is None or m.get('entity_name') == module.params['name']]
    types = {}
    if any(m.get('entity_type') == 'g' for m in members):
        types = dict((g.get('id'), group_type_name(g.get('group_type'))) for g in user_groups(client) or [])
    out = [member_view(m, name, types.get(m.get('entity_id'))) for m in members]

    def order(member):
        # Users first, then groups, each by name.
        return member['user'] is None, member['user'] or member['group'] or '', member['id'] or 0

    return dict(changed=False, members=sorted(out, key=order))


def main():
    argument_spec = harbor_argument_spec()
    argument_spec.update(project=dict(type='str', required=True), name=dict(type='str'))
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)
    run_module(module, lambda client: list_members(module, client))


if __name__ == '__main__':
    main()
