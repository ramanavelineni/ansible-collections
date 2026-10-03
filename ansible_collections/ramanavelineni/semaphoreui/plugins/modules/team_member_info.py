#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: team_member_info
short_description: List the team of a Semaphore UI project
version_added: 0.1.0
description:
  - Lists the users who belong to a project and their roles, optionally only one user.
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
  user:
    description:
      - Only return this user's membership (by username).
    type: str
seealso:
  - module: ramanavelineni.semaphoreui.team_member
    description: Creates, changes and deletes team members.
  - module: ramanavelineni.semaphoreui.project
    description: Manages the project.
'''

EXAMPLES = r'''
# The connection options (url and api_token, or username and password) are left out here. Set them once
# with module_defaults, or in the SEMAPHORE_URL and SEMAPHORE_API_TOKEN environment variables; the
# collection's README shows both under "Connecting".

- name: Who is in the homelab project
  ramanavelineni.semaphoreui.team_member_info:
    project: homelab
  register: result
'''

RETURN = r'''
members:
  description: Matching members, sorted by username.
  returned: always
  type: list
  elements: dict
  contains:
    user_id:
      description: The user's id.
      type: int
    username:
      description: The user's login name.
      type: str
    name:
      description: The user's display name.
      type: str
    role:
      description: The user's role in the project (V(owner), V(manager), V(task_runner) or V(guest)).
      type: str
    project_id:
      description: Id of the project.
      type: int
  sample:
    - user_id: 3
      username: rc
      name: RC
      role: owner
      project_id: 1
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.semaphore import (
    PROJECT_OPTIONS,
    project_ref,
    run_module,
    semaphore_argument_spec,
    semaphore_module_kwargs,
)


def list_members(module, client):
    client.warn_if_untested()
    project_id = project_ref(client, module.params)[0]
    out = []
    for member in client.list('/project/%d/users' % project_id):
        if module.params['user'] is not None and member.get('username') != module.params['user']:
            continue
        out.append(dict(user_id=member.get('id'), username=member.get('username'), name=member.get('name') or '',
                        role=member.get('role') or '', project_id=project_id))
    return dict(changed=False, members=sorted(out, key=lambda m: (m['username'] or '', m['user_id'] or 0)))


def main():
    argument_spec = semaphore_argument_spec()
    argument_spec.update(project=dict(type='str'), project_id=dict(type='int'), user=dict(type='str'))
    module = AnsibleModule(
        argument_spec=argument_spec, supports_check_mode=True,
        **semaphore_module_kwargs(mutually_exclusive=[PROJECT_OPTIONS], required_one_of=[PROJECT_OPTIONS])
    )
    run_module(module, lambda client: list_members(module, client))


if __name__ == '__main__':
    main()
