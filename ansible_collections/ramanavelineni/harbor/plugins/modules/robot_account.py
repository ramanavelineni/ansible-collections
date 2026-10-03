#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: robot_account
short_description: Manage Harbor robot accounts
version_added: 0.1.0
description:
  - Creates, updates or deletes a Harbor robot account, found by its name. A B(system) robot
    account can hold permissions on several projects (or on all of them) and on system resources;
    a B(project) robot account belongs to one project.
  - Only the options you set are compared and changed; the others keep their current value.
    O(permissions), when set, is the complete list.
  - Harbor never returns a robot's secret, so a changed secret cannot be detected. A declared
    O(secret) is set on every run by default; see O(update_secret). Without a declared secret
    Harbor generates one when the robot is created, and the module returns it that one time.
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
      - Name of the robot account, without Harbor's robot name prefix (C(robot$) by default) and,
        for a project robot, without the C(<project>+) part Harbor adds.
      - Lower-case letters, digits and C(.), C(_) or C(-) between them.
    type: str
    required: true
  level:
    description:
      - V(system) for a robot account that spans projects (Administration, Robot Accounts),
        V(project) for one that belongs to O(project) (the project's Robot Accounts tab).
      - A robot account's level cannot be changed; delete it and create it again.
    type: str
    choices: [system, project]
    default: system
  project:
    description:
      - Name of the project a V(project) robot account belongs to. Required with O(level=project).
    type: str
  state:
    description:
      - V(present) creates the robot account or updates it to match.
      - V(absent) deletes it.
    type: str
    choices: [present, absent]
    default: present
  description:
    description:
      - Free-text description.
    type: str
  duration:
    description:
      - Days until the robot account expires, counted from its creation, or V(-1) for never.
      - Defaults to V(-1) for a new robot account.
    type: int
  disable:
    description:
      - Whether the robot account is disabled.
    type: bool
  permissions:
    description:
      - What the robot account may do. When set, the complete list; required to create a robot account.
      - A V(project) robot account takes one entry, for its own project.
      - Compared as data, in any order.
    type: list
    elements: dict
    suboptions:
      kind:
        description:
          - V(project) for project resources, V(system) for system resources (system robot accounts only).
        type: str
        choices: [project, system]
        default: project
      namespace:
        description:
          - For V(project), the project name, or C(*) for every project, including projects created later.
            Defaults to O(project) for a project robot account.
          - For V(system), always C(/) (the default).
        type: str
      access:
        description:
          - 'The allowed actions, for example C({resource: repository, action: pull}).'
        type: list
        elements: dict
        required: true
        suboptions:
          resource:
            description: The resource, for example V(repository), V(artifact), V(tag), V(project).
            type: str
            required: true
          action:
            description: The action, for example V(pull), V(push), V(read), V(list), V(create), V(delete).
            type: str
            required: true
  secret:
    description:
      - Secret (password) of the robot account. 8 to 128 characters with at least one upper-case
        letter, one lower-case letter and one digit.
      - Harbor creates a robot account with a secret of its own and takes the declared one in a second
        request. If that request fails, the module deletes the new robot account again and fails, so
        the next run starts over.
      - Without it, Harbor generates a secret when the robot account is created and the module
        returns it in RV(secret); an existing robot account's secret is then left alone.
    type: str
  update_secret:
    description:
      - V(always) sets the declared O(secret) on every run, so the task always reports C(changed)
        when a secret is declared. The stored secret then always matches what you declare.
      - V(on_create) sets it only when the robot account is created.
    type: str
    choices: [always, on_create]
    default: always
notes:
  - Harbor answers every read with the robot's full name, prefix included (C(robot$name), or
    C(robot$project+name) for a project robot account). The module matches on O(name) and
    O(project), whatever the prefix is.
  - The C(harbor_config) role's C(projects=all) is written here as a system robot account with a
    project permission on namespace C(*), which also covers projects created later.
seealso:
  - module: ramanavelineni.harbor.robot_account_info
    description: List robot accounts.
  - module: ramanavelineni.harbor.project
    description: Create the project that O(project) or a permission names.
  - module: ramanavelineni.harbor.configuration
    description: Change the robot name prefix (C(robot_name_prefix)).
'''

EXAMPLES = r'''
# The connection options (url, username, password) are left out of these examples. Set them once with
# module_defaults for the group/ramanavelineni.harbor.harbor action group, or with the HARBOR_URL,
# HARBOR_USERNAME and HARBOR_PASSWORD environment variables.

- name: Pull-only robot for every project, with a secret from vault
  ramanavelineni.harbor.robot_account:
    name: puller
    permissions:
      - namespace: "*"
        access:
          - {resource: repository, action: pull}
    secret: "{{ vault_harbor_puller_secret }}"

- name: Project robot that can push to apps, secret generated by Harbor
  ramanavelineni.harbor.robot_account:
    name: ci
    level: project
    project: apps
    duration: 90
    permissions:
      - access:
          - {resource: repository, action: pull}
          - {resource: repository, action: push}
  register: ci_robot
  no_log: true  # the result holds the generated secret when the robot is created
'''

RETURN = r'''
robot_account:
  description:
    - The robot account after the change, or as it would be in check mode. Never holds a secret.
    - Empty after a deletion.
  returned: always
  type: dict
  sample:
    id: 4
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
secret:
  description:
    - The secret Harbor generated for a new robot account created without O(secret).
    - Set C(no_log) on the task. Modules cannot hide values they return.
  returned: when a robot account was created without O(secret) (not in check mode)
  type: str
  sample: "(the generated secret)"
secret_updated:
  description:
    - Whether the module set the robot account's secret, or would set it in check mode.
  returned: always
  type: bool
  sample: false
'''

import re

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.harbor.plugins.module_utils.harbor import (
    HarborError,
    canonical_permissions,
    harbor_argument_spec,
    require_project,
    robot_account_view,
    run_module,
)

NAME_RE = re.compile(r'^[a-z0-9]+(?:[._-][a-z0-9]+)*$')


def secret_is_valid(secret):
    """Harbor's rule: 8-128 characters with an upper-case letter, a lower-case letter and a digit."""
    return (8 <= len(secret) <= 128 and bool(re.search(r'[A-Z]', secret))
            and bool(re.search(r'[a-z]', secret)) and bool(re.search(r'[0-9]', secret)))


def desired_permissions(params):
    if params['permissions'] is None:
        return None
    out = []
    for perm in params['permissions']:
        kind = perm['kind']
        namespace = perm['namespace']
        if kind == 'system':
            if params['level'] == 'project':
                raise ValueError('A project robot account cannot have system permissions.')
            if namespace not in (None, '/'):
                raise ValueError('System permissions take namespace "/", not %r.' % namespace)
            namespace = '/'
        elif namespace is None:
            if params['level'] != 'project':
                raise ValueError('Each project permission of a system robot account needs namespace '
                                 '(a project name, or "*" for every project).')
            namespace = params['project']
        out.append(dict(kind=kind, namespace=namespace, access=perm['access']))
    if params['level'] == 'project':
        namespaces = set(p['namespace'] for p in out)
        if namespaces != set([params['project']]):
            raise ValueError('A project robot account only takes permissions on its own project %r.'
                             % params['project'])
    if not out:
        raise ValueError('permissions cannot be empty: Harbor rejects a robot account without any.')
    return canonical_permissions(out)


def find_robot(client, params, project_id):
    """The existing robot account for name/level/project, or None."""
    name = params['name']
    if params['level'] == 'system':
        # q=name matches the stored name, which carries neither the name
        # prefix nor a project, exactly.
        matches = [r for r in client.list('/robots', {'q': 'Level=system,name=%s' % name})
                   if r.get('level') == 'system']
    else:
        # A project robot is stored as <project>+<name>; the list is already
        # limited to the project, so the ending identifies it whatever the
        # prefix in front is.
        suffix = '%s+%s' % (params['project'], name)
        matches = [r for r in client.list('/robots', {'q': 'Level=project,ProjectID=%d' % project_id})
                   if (r.get('name') or '').endswith(suffix)]
    if len(matches) > 1:
        raise ValueError('More than one %s robot account is named %r.' % (params['level'], name))
    return matches[0] if matches else None


def ensure(module, client):
    params = module.params
    client.warn_if_untested()
    if not NAME_RE.match(params['name']):
        raise ValueError('Robot account name %r must be lower-case letters and digits, with ".", "_" or "-" '
                         'between them.' % params['name'])
    # The argument spec refuses a missing project; an empty one gets here.
    if params['level'] == 'project' and not params['project']:
        raise ValueError('level: project needs project.')
    if params['level'] == 'system' and params['project']:
        raise ValueError('project is only valid with level: project.')
    if params['secret'] is not None and not secret_is_valid(params['secret']):
        raise ValueError('secret must be 8 to 128 characters with at least one upper-case letter, one '
                         'lower-case letter and one digit (Harbor refuses anything else).')
    if params['duration'] is not None and not (params['duration'] == -1 or params['duration'] > 0):
        raise ValueError('duration must be -1 (never expires) or a positive number of days.')

    project_id = require_project(client, params['project'])['project_id'] if params['level'] == 'project' else None
    current = find_robot(client, params, project_id)
    result = dict(changed=False, robot_account={}, secret_updated=False)

    if params['state'] == 'absent':
        if current:
            before = robot_account_view(current, params['project'], params['name'])
            if not module.check_mode:
                client.delete('/robots/%d' % current['id'])
            result.update(changed=True, diff=dict(before=before, after={}))
        else:
            result['diff'] = dict(before={}, after={})
        return result

    permissions = desired_permissions(params)

    if not current:
        if permissions is None:
            raise ValueError('Creating robot account %r needs permissions.' % params['name'])
        body = dict(name=params['name'], level=params['level'], description=params['description'] or '',
                    duration=-1 if params['duration'] is None else params['duration'],
                    disable=bool(params['disable']), permissions=permissions)
        after = dict(id=None, name=params['name'], full_name=None, level=params['level'], project=params['project'],
                     description=body['description'], duration=body['duration'], expires_at=None,
                     disable=body['disable'], permissions=permissions)
        if not module.check_mode:
            created, dummy = client.post('/robots', body)
            robot_id = created['id']
            if params['secret'] is not None:
                try:
                    client.request('PATCH', '/robots/%d' % robot_id, body=dict(secret=params['secret']),
                                   expected=(200,), retry=True)
                except HarborError as e:
                    # Harbor created the robot with a secret of its own, which
                    # nobody knows. Left like that, update_secret: on_create
                    # would never set the declared one.
                    try:
                        client.delete('/robots/%d' % robot_id)
                        outcome = 'The robot account was removed again, so the next run starts over.'
                    except HarborError:
                        outcome = ('Removing it again failed too: it now exists without the declared secret. '
                                   'Delete it in Harbor, or run again with update_secret: always.')
                    raise ValueError('Robot account %r was created, but setting its declared secret failed: %s. %s'
                                     % (params['name'], e.message(), outcome))
                result['secret_updated'] = True
            else:
                result['secret'] = created.get('secret')
            after = robot_account_view(client.get('/robots/%d' % robot_id), params['project'], params['name'])
        else:
            # What the real run reports: a declared secret is set right after
            # the create. Without one Harbor generates it, which can't be shown.
            result['secret_updated'] = params['secret'] is not None
        result.update(changed=True, robot_account=after, diff=dict(before={}, after=after))
        return result

    before = robot_account_view(current, params['project'], params['name'])
    after = dict(before)
    for key in ('description', 'duration', 'disable'):
        if params[key] is not None:
            after[key] = params[key]
    if permissions is not None:
        after['permissions'] = permissions
    fields_changed = any(after[k] != before[k] for k in ('description', 'duration', 'disable', 'permissions'))
    send_secret = params['secret'] is not None and params['update_secret'] == 'always'

    if fields_changed and not module.check_mode:
        # The update needs the full name and level exactly as Harbor reports
        # them, overwrites description and disable with what it is sent, and
        # replaces the permissions, so every field goes back.
        client.put('/robots/%d' % current['id'], dict(
            name=current['name'], level=current['level'], description=after['description'],
            duration=after['duration'], disable=after['disable'], permissions=after['permissions']))
        after = robot_account_view(client.get('/robots/%d' % current['id']), params['project'], params['name'])
    if send_secret and not module.check_mode:
        client.request('PATCH', '/robots/%d' % current['id'], body=dict(secret=params['secret']),
                       expected=(200,), retry=True)
    result.update(changed=fields_changed or send_secret, secret_updated=send_secret, robot_account=after,
                  diff=dict(before=before, after=after))
    return result


def main():
    argument_spec = harbor_argument_spec()
    argument_spec.update(
        name=dict(type='str', required=True),
        level=dict(type='str', default='system', choices=['system', 'project']),
        project=dict(type='str'),
        state=dict(type='str', default='present', choices=['present', 'absent']),
        description=dict(type='str'),
        duration=dict(type='int'),
        disable=dict(type='bool'),
        permissions=dict(type='list', elements='dict', options=dict(
            kind=dict(type='str', default='project', choices=['project', 'system']),
            namespace=dict(type='str'),
            access=dict(type='list', elements='dict', required=True, options=dict(
                resource=dict(type='str', required=True),
                action=dict(type='str', required=True),
            )),
        )),
        secret=dict(type='str', no_log=True),
        update_secret=dict(type='str', default='always', choices=['always', 'on_create'], no_log=False),
    )
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True,
                           required_if=[('level', 'project', ('project',))])
    run_module(module, lambda client: ensure(module, client))


if __name__ == '__main__':
    main()
