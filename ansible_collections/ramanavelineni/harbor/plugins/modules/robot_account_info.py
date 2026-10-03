#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: robot_account_info
short_description: List Harbor robot accounts
version_added: 0.1.0
description:
  - Lists the system robot accounts, or the robot accounts of one project, optionally only the one
    with a given name. Harbor never returns secrets, so none are listed.
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
      - List this project's robot accounts instead of the system robot accounts.
    type: str
  name:
    description:
      - Only return the robot account with this name (without the robot name prefix and, for a
        project robot account, without the C(<project>+) part).
    type: str
seealso:
  - module: ramanavelineni.harbor.robot_account
    description: Manage robot accounts.
'''

EXAMPLES = r'''
# The connection options (url, username, password) are left out of these examples. Set them once with
# module_defaults for the group/ramanavelineni.harbor.harbor action group, or with the HARBOR_URL,
# HARBOR_USERNAME and HARBOR_PASSWORD environment variables.

- name: System robot accounts
  ramanavelineni.harbor.robot_account_info:
  register: robots

- name: Robot accounts of the apps project
  ramanavelineni.harbor.robot_account_info:
    project: apps
  register: app_robots
'''

RETURN = r'''
robot_accounts:
  description: Matching robot accounts, sorted by name.
  returned: always
  type: list
  elements: dict
  sample:
    - id: 4
      name: puller
      full_name: robot$puller
      level: system
      project: null
      description: ""
      duration: -1
      expires_at: -1
      disable: false
      permissions:
        - kind: project
          namespace: "*"
          access:
            - {resource: repository, action: pull}
  contains:
    id:
      description: Harbor's id of the robot account.
      type: int
    name:
      description: Name without the robot name prefix and, for a project robot account, without the project part.
      type: str
    full_name:
      description: Name as Harbor stores it and as it is used to log in, for example C(robot$puller).
      type: str
    level:
      description: V(system) or V(project).
      type: str
    project:
      description: Name of the project a V(project) robot account belongs to, V(null) for a V(system) one.
      type: str
    description:
      description: Description, empty when there is none.
      type: str
    duration:
      description: Days until the robot account expires, counted from its creation, or V(-1) for never.
      type: int
    expires_at:
      description: When the robot account expires, in seconds since the epoch, or V(-1) for never. V(null) in check mode for a new one.
      type: int
    disable:
      description: Whether the robot account is disabled.
      type: bool
    permissions:
      description: What the robot account may do, in a fixed order.
      type: list
      elements: dict
      contains:
        kind:
          description: V(project) or V(system).
          type: str
        namespace:
          description: Project name, C(*) for every project, or C(/) for V(system).
          type: str
        access:
          description: The allowed actions, each with a C(resource) and an C(action).
          type: list
          elements: dict
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.harbor.plugins.module_utils.harbor import (
    harbor_argument_spec,
    require_project,
    robot_account_view,
    robot_prefix,
    run_module,
)


def list_robots(module, client):
    client.warn_if_untested()
    project = module.params['project']
    if project is None:
        robots = [r for r in client.list('/robots', {'q': 'Level=system'}) if r.get('level') == 'system']
    else:
        found = require_project(client, project)
        robots = client.list('/robots', {'q': 'Level=project,ProjectID=%d' % found['project_id']})
    prefix = robot_prefix(client)
    out = []
    for robot in robots:
        view = robot_account_view(robot, project, prefix=prefix)
        if module.params['name'] is None or view['name'] == module.params['name']:
            out.append(view)
    return dict(changed=False, robot_accounts=sorted(out, key=lambda r: (r['name'] or '', r['id'] or 0)))


def main():
    argument_spec = harbor_argument_spec()
    argument_spec.update(project=dict(type='str'), name=dict(type='str'))
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)
    run_module(module, lambda client: list_robots(module, client))


if __name__ == '__main__':
    main()
