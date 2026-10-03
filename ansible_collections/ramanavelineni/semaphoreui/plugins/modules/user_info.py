#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: user_info
short_description: List Semaphore UI users
version_added: 0.1.0
description:
  - Lists Semaphore UI users, optionally only the one with a given login name. Passwords are never
    returned.
  - Without an admin login, Semaphore only reveals each user's id, login name and display name.
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
  login:
    description:
      - Only return the user with this login name.
    type: str
'''

EXAMPLES = r'''
- name: List every user
  ramanavelineni.semaphoreui.user_info:
  register: result

- name: Is there an ops user?
  ramanavelineni.semaphoreui.user_info:
    login: ops
  register: ops
'''

RETURN = r'''
users:
  description: Matching users, sorted by login name, in the form the M(ramanavelineni.semaphoreui.user) module returns.
  returned: always
  type: list
  elements: dict
  sample:
    - id: 3
      username: ops
      name: Ops
      email: ops@example.com
      admin: false
      alert: false
      external: false
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.semaphore import (
    run_module,
    semaphore_argument_spec,
    semaphore_module_kwargs,
    user_view,
)


def list_users(module, client):
    client.warn_if_untested()
    out = []
    for user in client.list('/users'):
        if module.params['login'] is not None and user.get('username') != module.params['login']:
            continue
        out.append(user_view(user))
    return dict(changed=False, users=sorted(out, key=lambda u: (u.get('username') or '', u.get('id') or 0)))


def main():
    argument_spec = semaphore_argument_spec()
    argument_spec.update(login=dict(type='str'))
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True, **semaphore_module_kwargs())
    run_module(module, lambda client: list_users(module, client))


if __name__ == '__main__':
    main()
