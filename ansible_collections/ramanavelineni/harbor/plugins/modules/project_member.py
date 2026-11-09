#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: project_member
short_description: Manage the members of a Harbor project
version_added: 0.6.0
description:
  - Adds a user or a group to a Harbor project with a role, changes the role, or removes the member.
  - A user is found by name among the project's members. A group is found by name and O(group_type) among
    Harbor's user groups, and then by its id among the project's members, so an OIDC group and an LDAP group
    with the same name are not mixed up.
author:
  - ramanavelineni (@ramanavelineni)
extends_documentation_fragment:
  - ramanavelineni.harbor.auth
  - ramanavelineni.harbor.attributes
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
      - Name of the Harbor user to add.
      - A user that Harbor doesn't know yet is looked up through its login backend (LDAP, OIDC) when it has
        one, as Harbor does in the UI. With database logins the user must exist.
      - Exactly one of O(user) and O(group) is required.
    type: str
  group:
    description:
      - Name of the group to add. Requires O(group_type).
      - Exactly one of O(user) and O(group) is required.
    type: str
  group_type:
    description:
      - The kind of group O(group) names.
      - A group Harbor doesn't have yet is created when the member is added, but Harbor does that only while
        its C(auth_mode) matches the type (V(oidc) needs C(oidc_auth), V(ldap) C(ldap_auth), V(http)
        C(http_auth)). Otherwise the task fails with that reason before anything is sent; in check mode it
        is a warning instead.
      - An LDAP group is added by name only; its DN is not supported.
    type: str
    choices: [oidc, ldap, http]
  role:
    description:
      - The member's role in the project. Required to add a member.
      - Left out for an existing member, the role is not changed.
    type: str
    choices: [project_admin, maintainer, developer, guest, limited_guest]
  state:
    description:
      - V(present) adds the member or changes its role to match.
      - V(absent) removes it. When the project no longer exists, it reports no change.
    type: str
    choices: [present, absent]
    default: present
notes:
  - Only a system administrator may read Harbor's user groups and its configuration. For anyone else a group
    is found by its name alone, and a missing group is left to Harbor to accept or refuse.
  - The user who creates a project is its first member, as project admin.
seealso:
  - module: ramanavelineni.harbor.project_member_info
    description: List a project's members.
  - module: ramanavelineni.harbor.project
    description: Create the project.
'''

EXAMPLES = r'''
# The connection options (url, username, password) can be set once instead of on every task, with
# module_defaults for the group/ramanavelineni.harbor.harbor action group, or with the HARBOR_URL,
# HARBOR_USERNAME and HARBOR_PASSWORD environment variables.

- name: Let everyone in the harbor-readonly OIDC group pull from the apps project
  ramanavelineni.harbor.project_member:
    url: https://harbor.example.com
    username: admin
    password: "{{ harbor_admin_password }}"
    project: apps
    group: harbor-readonly
    group_type: oidc
    role: guest

- name: Make alice a maintainer of the apps project
  ramanavelineni.harbor.project_member:
    url: https://harbor.example.com
    username: admin
    password: "{{ harbor_admin_password }}"
    project: apps
    user: alice
    role: maintainer

- name: Remove bob from the apps project
  ramanavelineni.harbor.project_member:
    url: https://harbor.example.com
    username: admin
    password: "{{ harbor_admin_password }}"
    project: apps
    user: bob
    state: absent
'''

RETURN = r'''
member:
  description:
    - The member after the change, or as it would be in check mode. Empty after a removal.
    - After a change it is read back from Harbor. If the stored role differs from what the task sent, the
      module warns, because the next run will then report a change again.
  returned: always
  type: dict
  sample:
    id: 7
    project: apps
    project_id: 2
    user: null
    group: harbor-readonly
    group_type: oidc
    role: guest
    role_id: 3
  contains:
    id:
      description: Harbor's id of the membership, V(null) for a member that check mode would add.
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
      description: V(oidc), V(ldap) or V(http) for a group, V(null) for a user.
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
    GROUP_AUTH_MODES,
    GROUP_TYPES,
    MEMBER_ROLES,
    auth_mode,
    harbor_argument_spec,
    id_from_location,
    member_view,
    require_project,
    run_module,
    user_groups,
    warn_if_stored_differently,
)

# In these auth modes Harbor lists only the user groups of its own type
# (ListUserGroups in src/server/v2.0/handler/usergroup.go), so a group of
# another type may exist without being listed.
LISTING_ONE_TYPE = ('ldap_auth', 'http_auth')


def find_group(client, name, group_type):
    """(the user group, whether the answer can be trusted).

    The group is None when Harbor has none of that name and type. The answer
    can't be trusted when this user may not list user groups, or when Harbor
    lists only groups of another type.
    """
    groups = user_groups(client, dict(group_name=name))
    if groups is None:
        return None, False
    # ?group_name= also finds groups whose name merely contains this one.
    wanted = GROUP_TYPES[group_type]
    matches = [g for g in groups if g.get('group_name') == name and g.get('group_type') == wanted]
    if matches:
        return matches[0], True
    return None, True


def ensure(module, client):
    params = module.params
    client.warn_if_untested()
    project = require_project(client, params['project'], missing_ok=params['state'] == 'absent')
    if project is None:
        # The project is gone, and its members went with it.
        return dict(changed=False, member={}, diff=dict(before={}, after={}))
    project_id = project['project_id']
    base = '/projects/%d/members' % project_id
    members = client.list(base)
    group_type = params['group_type']

    group = None
    blocked = None
    if params['user'] is not None:
        name, entity_type = params['user'], 'u'
        found = [m for m in members if m.get('entity_type') == 'u' and m.get('entity_name') == name]
    else:
        name, entity_type = params['group'], 'g'
        group, trusted = find_group(client, name, group_type)
        if trusted and group is None:
            mode = auth_mode(client)
            if mode in LISTING_ONE_TYPE and mode != GROUP_AUTH_MODES[group_type]:
                trusted = False
            elif mode is not None and mode != GROUP_AUTH_MODES[group_type]:
                blocked = mode
        if trusted:
            found = [m for m in members if m.get('entity_type') == 'g' and group is not None
                     and m.get('entity_id') == group.get('id')]
        else:
            found = [m for m in members if m.get('entity_type') == 'g' and m.get('entity_name') == name]
            if len(found) > 1:
                raise ValueError(
                    'Project %r has %d group members named %r, and the user this module logs in as may not read '
                    "Harbor's user groups to tell which one is the %s group. Run it as a system administrator."
                    % (params['project'], len(found), name, group_type))
    current = found[0] if found else None
    before = member_view(current, params['project'], group_type) if current else {}

    if params['state'] == 'absent':
        if not current:
            return dict(changed=False, member={}, diff=dict(before={}, after={}))
        if not module.check_mode:
            client.delete('%s/%d' % (base, current['id']))
        return dict(changed=True, member={}, diff=dict(before=before, after={}))

    wanted_role = MEMBER_ROLES[params['role']] if params['role'] is not None else None
    if current:
        if wanted_role is None or current.get('role_id') == wanted_role:
            return dict(changed=False, member=before, diff=dict(before=before, after=before))
        after = dict(before, role=params['role'], role_id=wanted_role)
        if not module.check_mode:
            client.put('%s/%d' % (base, current['id']), dict(role_id=wanted_role))
            # Read it back: what Harbor stored is what the next run compares with.
            predicted = after
            after = member_view(client.get('%s/%d' % (base, current['id'])), params['project'], group_type)
            warn_if_stored_differently(module, 'member %r' % name, [k for k in after if after[k] != predicted[k]])
        return dict(changed=True, member=after, diff=dict(before=before, after=after))

    what = 'user %r' % name if entity_type == 'u' else '%s group %r' % (group_type, name)
    if wanted_role is None:
        raise ValueError('Adding %s to project %r needs role.' % (what, params['project']))
    if blocked:
        message = ("Harbor has no %s, and creates a missing one only while its auth_mode is %s; it is %s. Create "
                   'the group first (Administration > Groups), or run this where that group can be created.'
                   % (what, GROUP_AUTH_MODES[group_type], blocked))
        if not module.check_mode:
            raise ValueError(message)
        module.warn(message)
    if entity_type == 'u':
        body = dict(role_id=wanted_role, member_user=dict(username=name))
    elif group is not None:
        body = dict(role_id=wanted_role, member_group=dict(id=group['id']))
    else:
        body = dict(role_id=wanted_role, member_group=dict(group_name=name, group_type=GROUP_TYPES[group_type]))
    after = member_view(dict(id=None, project_id=project_id, entity_name=name, entity_type=entity_type,
                             role_id=wanted_role), params['project'], group_type)
    if not module.check_mode:
        dummy, headers = client.post(base, body)
        member_id = id_from_location(headers)
        if member_id:
            created = client.get('%s/%d' % (base, member_id))
        else:
            created = next((m for m in client.list(base)
                            if m.get('entity_type') == entity_type and m.get('entity_name') == name), {})
        after = member_view(created, params['project'], group_type)
    return dict(changed=True, member=after, diff=dict(before={}, after=after))


def main():
    argument_spec = harbor_argument_spec()
    argument_spec.update(
        project=dict(type='str', required=True),
        user=dict(type='str'),
        group=dict(type='str'),
        group_type=dict(type='str', choices=['oidc', 'ldap', 'http']),
        role=dict(type='str', choices=['project_admin', 'maintainer', 'developer', 'guest', 'limited_guest']),
        state=dict(type='str', default='present', choices=['present', 'absent']),
    )
    module = AnsibleModule(
        argument_spec=argument_spec,
        mutually_exclusive=[('user', 'group'), ('user', 'group_type')],
        required_one_of=[('user', 'group')],
        required_by=dict(group='group_type'),
        supports_check_mode=True,
    )
    run_module(module, lambda client: ensure(module, client), placeholder=dict(member={}))


if __name__ == '__main__':
    main()
