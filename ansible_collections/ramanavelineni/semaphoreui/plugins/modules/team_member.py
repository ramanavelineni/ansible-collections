#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: team_member
short_description: Manage who belongs to a Semaphore UI project, and with which role
version_added: 0.1.0
description:
  - Adds a user to a project's team, changes their role, or removes them, found by username.
  - The user must already exist; this module does not create users.
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
      - Name of the project.
    type: str
    required: true
  user:
    description:
      - Username (login name) of the member.
      - Named C(user), not C(username), because O(username) is the account the module logs in with.
    type: str
    required: true
  role:
    description:
      - The user's role in the project. Required with O(state=present).
      - V(owner) can do everything, V(manager) everything except managing the team and deleting the
        project, V(task_runner) can run tasks, V(guest) can only look.
    type: str
    choices: [owner, manager, task_runner, guest]
  state:
    description:
      - V(present) adds the user to the team or changes their role.
      - V(absent) removes the user from the team.
    type: str
    choices: [present, absent]
    default: present
notes:
  - The module refuses to remove or downgrade a project's last owner, which would leave the project
    without anyone who can manage its team.
  - The module refuses to change the membership of the user it logs in as, so a run can't lock
    itself out of a project.
'''

EXAMPLES = r'''
- name: Give rc the owner role in homelab
  ramanavelineni.semaphoreui.team_member:
    project: homelab
    user: rc
    role: owner

- name: Remove a user from the team
  ramanavelineni.semaphoreui.team_member:
    project: homelab
    user: alice
    state: absent
'''

RETURN = r'''
member:
  description:
    - The membership after the change, or as it would be in check mode.
    - Empty when the user is not (or no longer) in the team.
  returned: always
  type: dict
  sample:
    user_id: 3
    username: rc
    name: RC
    role: owner
    project_id: 1
'''

from urllib.parse import quote

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.semaphore import (
    MissingReference,
    find_by_name,
    resolve_project,
    run_module,
    semaphore_argument_spec,
    semaphore_module_kwargs,
)

OWNER = 'owner'


def member_view(member, project_id):
    return dict(user_id=member.get('id'), username=member.get('username'), name=member.get('name') or '',
                role=member.get('role') or '', project_id=project_id)


def find_user(client, username):
    """The user with exactly this username, or None.

    GET /users?s= matches a username prefix, so the exact name is picked out.
    """
    return find_by_name(client.list('/users?s=%s' % quote(username, safe='')), username, 'user', field='username')


def ensure(module, client):
    params = module.params
    client.warn_if_untested()

    project_id = resolve_project(client, params['project'], missing_ok=params['state'] == 'absent')
    if project_id is None:
        # The project is gone, and everything in it went with it.
        return dict(changed=False, member={}, diff=dict(before={}, after={}))
    base = '/project/%d/users' % project_id
    members = client.list(base)
    user = find_user(client, params['user'])
    if user is None:
        if params['state'] == 'absent':
            return dict(changed=False, member={}, diff=dict(before={}, after={}))
        raise MissingReference('User %r does not exist; create the user first.' % params['user'])

    current = [m for m in members if m.get('id') == user['id']]
    current = current[0] if current else None
    before = member_view(current, project_id) if current else {}
    owners = [m for m in members if m.get('role') == OWNER]

    if params['state'] == 'absent':
        if not current:
            return dict(changed=False, member={}, diff=dict(before={}, after={}))
        after = {}
    else:
        after = member_view(dict(current or user, role=params['role']), project_id)
        if before == after:
            return dict(changed=False, member=before, diff=dict(before=before, after=after))

    me = client.get('/user') or {}
    if me.get('id') == user['id']:
        raise ValueError(
            'User %r is the user this module logs in as; changing its own membership of project %r could lock '
            'it out. Change it as another user, or in the UI.' % (params['user'], params['project']))
    if current and current.get('role') == OWNER and after.get('role') != OWNER and len(owners) == 1:
        raise ValueError(
            'User %r is the last owner of project %r; removing or downgrading them would leave nobody who can '
            'manage the team. Make someone else an owner first.' % (params['user'], params['project']))

    if not module.check_mode:
        if params['state'] == 'absent':
            client.delete('%s/%d' % (base, user['id']))
        elif current:
            client.put('%s/%d' % (base, user['id']), dict(role=params['role']))
        else:
            # Semaphore answers an added member with 204 and no body.
            client.post(base, dict(user_id=user['id'], role=params['role']), expected=(204,))
    return dict(changed=True, member=after, diff=dict(before=before, after=after))


def main():
    argument_spec = semaphore_argument_spec()
    argument_spec.update(
        project=dict(type='str', required=True),
        user=dict(type='str', required=True),
        role=dict(type='str', choices=['owner', 'manager', 'task_runner', 'guest']),
        state=dict(type='str', default='present', choices=['present', 'absent']),
    )
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True,
                           **semaphore_module_kwargs(required_if=[('state', 'present', ('role',))]))
    run_module(module, lambda client: ensure(module, client), placeholder=dict(member={}))


if __name__ == '__main__':
    main()
