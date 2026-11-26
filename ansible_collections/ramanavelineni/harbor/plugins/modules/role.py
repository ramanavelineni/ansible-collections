#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: role
short_description: Manage custom project roles of Harbor
version_added: 0.10.0
description:
  - Creates, updates or deletes a custom project role (Administration > Roles), found by its name. A project
    member gets one with M(ramanavelineni.harbor.project_member).
  - Custom roles are new in Harbor 2.16; on an older Harbor the module fails.
  - Only the options you set are compared and changed; the others keep their current value.
  - The five built-in roles (Project Admin, Maintainer, Developer, Guest, Limited Guest) cannot be changed or
    deleted, so the module refuses them.
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
  name:
    description:
      - Name of the role. Roles are looked up by this name.
      - Renaming is not supported. A different name is a different role.
      - The names project_member uses for the built-in roles (V(project_admin), V(maintainer), V(developer),
        V(guest), V(limited_guest)) and Harbor's own (V(projectAdmin), V(limitedGuest)) are refused.
    type: str
    required: true
  state:
    description:
      - V(present) creates the role or updates it to match.
      - V(absent) deletes it. Harbor refuses while project members or robot accounts still have the role,
        and the task fails with Harbor's answer.
    type: str
    choices: [present, absent]
    default: present
  description:
    description:
      - Free-text description.
    type: str
  permissions:
    description:
      - 'What a member with this role may do in the project, as resource and action pairs, for example
        C({resource: repository, action: pull}). When set, the complete list; required to create a role.'
      - Compared as a set; the order and duplicates do not matter. An empty list fails, because Harbor refuses
        a role without permissions.
      - Checked against the permissions Harbor offers for roles (C(GET /permissions)) before anything is sent,
        when the login user may read them.
    type: list
    elements: dict
    suboptions:
      resource:
        description: The resource, for example V(repository), V(artifact), V(tag), V(member), V(robot).
        type: str
        required: true
      action:
        description: The action, for example V(pull), V(push), V(read), V(list), V(create), V(update), V(delete).
        type: str
        required: true
notes:
  - Creating, changing and deleting roles needs a Harbor system administrator. Any logged-in user may read them.
seealso:
  - module: ramanavelineni.harbor.role_info
    description: List the roles, built-in and custom.
  - module: ramanavelineni.harbor.project_member
    description: Give a user or group a role in a project.
'''

EXAMPLES = r'''
# The connection options (url, username, password) can be set once instead of on every task, with
# module_defaults for the group/ramanavelineni.harbor.harbor action group, or with the HARBOR_URL,
# HARBOR_USERNAME and HARBOR_PASSWORD environment variables.

- name: A role that may only pull and push
  ramanavelineni.harbor.role:
    url: https://harbor.example.com
    username: admin
    password: "{{ harbor_admin_password }}"
    name: ci-deployer
    description: CI pipelines
    permissions:
      - {resource: repository, action: pull}
      - {resource: repository, action: push}
      - {resource: artifact, action: read}

- name: Give the CI user that role in project apps
  ramanavelineni.harbor.project_member:
    url: https://harbor.example.com
    username: admin
    password: "{{ harbor_admin_password }}"
    project: apps
    user: ci
    role: ci-deployer
'''

RETURN = r'''
role:
  description:
    - The role after the change, or as it would be in check mode. Empty after a deletion.
    - After a change it is read back from Harbor, so it shows what Harbor stored.
  returned: always
  type: dict
  sample:
    id: 6
    name: ci-deployer
    description: CI pipelines
    builtin: false
    member_role: ci-deployer
    permissions:
      - {resource: artifact, action: read}
      - {resource: repository, action: pull}
      - {resource: repository, action: push}
  contains:
    id:
      description: Harbor's id of the role. Custom roles have ids from 6 on.
      type: int
    name:
      description: Name of the role.
      type: str
    description:
      description: Description, empty when there is none.
      type: str
    builtin:
      description: Whether this is one of Harbor's built-in roles. Always V(false) here.
      type: bool
    member_role:
      description: What O(ramanavelineni.harbor.project_member#module:role) takes for this role.
      type: str
    permissions:
      description: The role's permissions, sorted by resource and action.
      type: list
      elements: dict
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.harbor.plugins.module_utils.harbor import (
    BUILT_IN_ROLE_NAMES,
    HarborError,
    MEMBER_ROLES,
    ROLE_KIND,
    harbor_argument_spec,
    id_from_location,
    require_custom_roles,
    role_view as view,
    run_module,
    warn_if_stored_differently,
)


def desired_permissions(permissions):
    """The permissions option as sorted, unique {resource, action} pairs, or None."""
    if permissions is None:
        return None
    pairs = sorted(set((p['resource'], p['action']) for p in permissions))
    if not pairs:
        raise ValueError('permissions cannot be empty: Harbor refuses a role without any.')
    return [dict(resource=resource, action=action) for resource, action in pairs]


def check_offered(client, permissions):
    """Refuse a permission Harbor does not offer for roles; leave it to Harbor when the list can't be read."""
    try:
        answer = client.get('/permissions')
    except HarborError as e:
        if e.status in (401, 403):
            return
        raise
    offered = answer.get('role') if isinstance(answer, dict) else None
    if not isinstance(offered, list):
        return
    known = set((p.get('resource') or '', p.get('action') or '') for p in offered)
    unknown = ['%s:%s' % (p['resource'], p['action']) for p in permissions if (p['resource'], p['action']) not in known]
    if unknown:
        raise ValueError('Harbor offers no role permission %s. Resources it offers: %s.'
                         % (', '.join(unknown), ', '.join(sorted(set(r for r, a in known if r)))))


def body(name, description, permissions):
    return dict(name=name, description=description,
                permissions=[dict(kind=ROLE_KIND, namespace='*', access=permissions)])


def ensure(module, client):
    params = module.params
    name = params['name']
    client.warn_if_untested()
    if name in MEMBER_ROLES or name in BUILT_IN_ROLE_NAMES:
        raise ValueError('%r names a built-in role, which Harbor does not let anyone change or delete; '
                         'project_member assigns it as it is.' % name)
    require_custom_roles(client)
    permissions = desired_permissions(params['permissions'])

    current = next((r for r in client.list('/roles') if r.get('name') == name), None)
    if current is not None and current.get('is_builtin'):
        raise ValueError('%r is a built-in role, which Harbor does not let anyone change or delete.' % name)
    before = view(current) if current else {}

    if params['state'] == 'absent':
        if not current:
            return dict(changed=False, role={}, diff=dict(before={}, after={}))
        if not module.check_mode:
            # 412 while members or robot accounts have the role: Harbor's answer is the failure.
            client.delete('/roles/%d' % current['id'])
        return dict(changed=True, role={}, diff=dict(before=before, after={}))

    if permissions is not None:
        check_offered(client, permissions)

    if not current:
        if permissions is None:
            raise ValueError('Creating role %r needs permissions.' % name)
        sent = body(name, params['description'] or '', permissions)
        after = view(dict(sent, id=None))
        if not module.check_mode:
            created, headers = client.post('/roles', sent)
            role_id = id_from_location(headers) or (created or {}).get('id')
            after = view(client.get('/roles/%d' % role_id))
        return dict(changed=True, role=after, diff=dict(before={}, after=after))

    description = before['description'] if params['description'] is None else params['description']
    wanted = before['permissions'] if permissions is None else permissions
    after = dict(before, description=description, permissions=wanted)
    if after == before:
        return dict(changed=False, role=before, diff=dict(before=before, after=before))
    if not module.check_mode:
        # The update replaces the description and the permissions, so both go back.
        client.put('/roles/%d' % current['id'], body(name, description, wanted))
        predicted = after
        after = view(client.get('/roles/%d' % current['id']))
        warn_if_stored_differently(module, 'role %r' % name, [k for k in after if after[k] != predicted[k]])
    return dict(changed=True, role=after, diff=dict(before=before, after=after))


def main():
    argument_spec = harbor_argument_spec()
    argument_spec.update(
        name=dict(type='str', required=True),
        state=dict(type='str', default='present', choices=['present', 'absent']),
        description=dict(type='str'),
        permissions=dict(type='list', elements='dict', options=dict(
            resource=dict(type='str', required=True),
            action=dict(type='str', required=True),
        )),
    )
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)
    run_module(module, lambda client: ensure(module, client), placeholder=dict(role={}))


if __name__ == '__main__':
    main()
