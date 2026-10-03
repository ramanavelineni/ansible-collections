#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: variable_group
short_description: Manage variable groups in a Semaphore UI project
version_added: 0.1.0
description:
  - Creates, updates or deletes a variable group (called an environment in Semaphore's API) in a
    project, found by its name. A variable group holds extra variables, environment variables and
    secrets for the tasks that use it.
  - Only the options you set are compared and changed; the others keep their current value.
  - Semaphore never returns a secret's value, so a changed value cannot be detected. By default
    declared secret values are sent on every run and the task reports C(changed); see O(update_secret).
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
      - Name of the project the variable group belongs to.
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
      - Name of the variable group. Groups are looked up by this name within the project.
    type: str
    required: true
  state:
    description:
      - V(present) creates the group or updates it to match.
      - V(absent) deletes it, with its secrets. It fails, listing them, while templates or other
        objects still use it.
    type: str
    choices: [present, absent]
    default: present
  json:
    description:
      - Extra variables passed to Ansible (C(--extra-vars)). Replaces the group's current extra
        variables as a whole.
      - If the stored value is not valid JSON, setting this option replaces it, and the diff shows
        the stored text. Without this option the task fails, because an update would write the
        broken value back.
    type: dict
  env:
    description:
      - Environment variables for the task's process. Values must be scalars (strings, numbers,
        booleans). Replaces the group's current environment variables as a whole.
      - A stored value that is not valid JSON is handled as for O(json).
    type: dict
  secrets:
    description:
      - Secrets of the group, by name. Secrets present in Semaphore but not listed here are left
        alone unless O(purge_secrets=true).
    type: list
    elements: dict
    suboptions:
      name:
        description: Name of the variable.
        type: str
        required: true
      type:
        description:
          - V(env) exposes the secret as an environment variable, V(var) as an extra variable.
          - Semaphore cannot change a secret's type, so a secret of the other type is deleted and
            created again, which needs O(secrets[].value).
        type: str
        choices: [env, var]
        default: env
      value:
        description:
          - The secret's value.
          - Required to create the secret. For an existing secret, leave it out to keep the stored value.
        type: str
  purge_secrets:
    description:
      - Delete the group's secrets that are not listed in O(secrets).
    type: bool
    default: false
  update_secret:
    description:
      - V(always) sends every declared secret value on each run, so the task reports C(changed)
        when any value is declared. The stored values then always match what you declare.
      - V(on_create) sends a value only when its secret is created (or recreated with another type).
    type: str
    choices: [always, on_create]
    default: always
seealso:
  - module: ramanavelineni.semaphoreui.variable_group_info
    description: Reads variable groups without changing them.
  - module: ramanavelineni.semaphoreui.project
    description: Manages the project.
'''

EXAMPLES = r'''
# The connection options (url and api_token, or username and password) are left out here. Set them once
# with module_defaults, or in the SEMAPHORE_URL and SEMAPHORE_API_TOKEN environment variables; the
# collection's README shows both under "Connecting".

- name: Variable group with a token in the environment
  ramanavelineni.semaphoreui.variable_group:
    project: homelab
    name: harbor
    json:
      harbor_url: https://harbor.example.com
    env:
      TZ: UTC
    secrets:
      - name: HARBOR_TOKEN
        type: env
        value: "{{ vault_harbor_token }}"

- name: Empty variable group for templates that need none
  ramanavelineni.semaphoreui.variable_group:
    project: homelab
    name: empty
    json: {}
    env: {}
'''

RETURN = r'''
variable_group:
  description:
    - The group after the change, or as it would be in check mode. Secret values are never returned.
    - Empty after a deletion.
  returned: always
  type: dict
  contains:
    id:
      description: Variable group id.
      type: int
    name:
      description: Name of the variable group.
      type: str
    project_id:
      description: Id of the project.
      type: int
    json:
      description: Extra variables passed to Ansible.
      type: dict
    env:
      description: Environment variables for the task's process.
      type: dict
    secrets:
      description: The group's secrets, sorted by name. Values are never returned.
      type: list
      elements: dict
      contains:
        name:
          description: Name of the variable.
          type: str
        type:
          description: V(env) for an environment variable, V(var) for an extra variable.
          type: str
  sample:
    id: 1
    name: harbor
    project_id: 1
    json:
      harbor_url: https://harbor.example.com
    env:
      TZ: UTC
    secrets:
      - name: HARBOR_TOKEN
        type: env
secrets_sent:
  description: Names of the secrets whose value the module sent.
  returned: always
  type: list
  elements: str
  sample: [HARBOR_TOKEN]
secrets_deleted:
  description: Names of the secrets the module deleted (purged, or recreated with another type).
  returned: always
  type: list
  elements: str
  sample: [OLD_TOKEN]
'''

import json

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.semaphore import (
    PROJECT_OPTIONS,
    find_by_name,
    project_ref,
    refuse_delete_if_used,
    run_module,
    semaphore_argument_spec,
    semaphore_module_kwargs,
    variable_group_view as view,
)

# Fields of the group that this module does not manage but the update
# writes; they are sent back as they are.
PASSTHROUGH = ('password', 'secret_storage_id', 'secret_storage_key_prefix',
               'sync_enabled', 'sync_interval', 'sync_paths')


def validate(params):
    for key, value in (params['env'] or {}).items():
        if isinstance(value, (dict, list)):
            raise ValueError('env.%s must be a scalar; Semaphore only accepts strings, numbers and booleans there.' % key)
    seen = set()
    for secret in params['secrets'] or []:
        if secret['name'] in seen:
            raise ValueError('Secret %r is listed more than once.' % secret['name'])
        seen.add(secret['name'])


def plan_secrets(params, current):
    """Secret operations for the update body, plus the names sent and deleted."""
    existing = dict((s['name'], s) for s in current)
    ops, sent, deleted = [], [], []
    for secret in params['secrets'] or []:
        have = existing.get(secret['name'])
        if have is not None and have['type'] != secret['type']:
            if secret['value'] is None:
                raise ValueError(
                    'Secret %r is of type %s; Semaphore cannot change that in place, so it has to be '
                    'deleted and created as %s, which needs its value.' % (secret['name'], have['type'], secret['type']))
            ops.append(dict(id=have['id'], name=have['name'], type=have['type'], secret='', operation='delete'))
            deleted.append(secret['name'])
            have = None
        if have is None:
            if secret['value'] is None:
                raise ValueError('Creating secret %r needs its value.' % secret['name'])
            ops.append(dict(name=secret['name'], type=secret['type'], secret=secret['value'], operation='create'))
            sent.append(secret['name'])
        elif secret['value'] is not None and params['update_secret'] == 'always':
            ops.append(dict(id=have['id'], name=have['name'], type=have['type'], secret=secret['value'], operation='update'))
            sent.append(secret['name'])
    if params['purge_secrets']:
        declared = set(s['name'] for s in params['secrets'] or [])
        for have in current:
            if have['name'] not in declared:
                ops.append(dict(id=have['id'], name=have['name'], type=have['type'], secret='', operation='delete'))
                deleted.append(have['name'])
    return ops, sent, deleted


def secrets_after(current, params, deleted):
    remaining = [dict(name=s['name'], type=s['type']) for s in current if s['name'] not in deleted]
    names = set(s['name'] for s in remaining)
    for secret in params['secrets'] or []:
        if secret['name'] not in names:
            remaining.append(dict(name=secret['name'], type=secret['type']))
    return remaining


def stored_view(current, secrets, replaced):
    """view() of the stored group that doesn't fail on the fields in `replaced`.

    view() refuses stored json or env that is not valid JSON, because an update
    sends an unmanaged field back as it is. A field the task replaces, and
    everything on a delete, never goes back, so there it must not stand in the
    way. Such a field is shown as the text Semaphore holds.
    """
    group = dict(current)
    raw = {}
    for field in replaced:
        try:
            json.loads(group.get(field) or '{}')
        except ValueError:
            raw[field] = group[field]
            group[field] = ''
    out = view(group, secrets)
    out.update(raw)
    return out


def ensure(module, client):
    params = module.params
    validate(params)
    client.warn_if_untested()

    project_id = project_ref(client, params, missing_ok=params['state'] == 'absent')[0]
    if project_id is None:
        # The project is gone, and everything in it went with it.
        return dict(changed=False, variable_group={}, secrets_sent=[], secrets_deleted=[], diff=dict(before={}, after={}))
    base = '/project/%d' % project_id
    found = find_by_name(client.list(base + '/environment'), params['name'], 'variable group')
    result = dict(changed=False, variable_group={}, secrets_sent=[], secrets_deleted=[])

    if params['state'] == 'absent':
        if not found:
            result.update(diff=dict(before={}, after={}))
            return result
        refuse_delete_if_used(client, '%s/environment/%d' % (base, found['id']), 'variable group', params['name'])
        # The single read, as for an update: the list leaves secrets out.
        current = client.get('%s/environment/%d' % (base, found['id'])) or found
        before = stored_view(current, current.get('secrets') or [], ('json', 'env'))
        if not module.check_mode:
            client.delete('%s/environment/%d' % (base, found['id']))
        result.update(changed=True, diff=dict(before=before, after={}))
        return result

    if not found:
        ops, sent, deleted = plan_secrets(params, [])
        body = dict(project_id=project_id, name=params['name'],
                    json=json.dumps(params['json'] or {}, sort_keys=True),
                    env=json.dumps(params['env'] or {}, sort_keys=True),
                    secrets=ops)
        after = view(body, secrets_after([], params, deleted))
        after.pop('id')
        if not module.check_mode:
            created = client.post(base + '/environment', body)
            after['id'] = created.get('id')
        result.update(changed=True, variable_group=after, secrets_sent=sent,
                      diff=dict(before={}, after=after))
        return result

    # The list leaves secrets out; the single read has their ids and types.
    current = client.get('%s/environment/%d' % (base, found['id'])) or {}
    current_secrets = current.get('secrets') or []
    before = stored_view(current, current_secrets, [f for f in ('json', 'env') if params[f] is not None])

    ops, sent, deleted = plan_secrets(params, current_secrets)
    json_changed = params['json'] is not None and params['json'] != before['json']
    env_changed = params['env'] is not None and params['env'] != before['env']
    if not (ops or json_changed or env_changed):
        result.update(variable_group=before, diff=dict(before=before, after=before))
        return result

    body = dict(id=current['id'], project_id=project_id, name=params['name'],
                json=json.dumps(params['json'], sort_keys=True) if json_changed else current.get('json'),
                env=json.dumps(params['env'], sort_keys=True) if env_changed else current.get('env'),
                secrets=ops)
    for field in PASSTHROUGH:
        if field in current:
            body[field] = current[field]
    after = view(body, secrets_after(current_secrets, params, deleted))
    if not module.check_mode:
        # The update rewrites name, json, env and password together, then
        # applies the secret operations in order (a recreate is a delete
        # followed by a create).
        client.put('%s/environment/%d' % (base, current['id']), body)
    result.update(changed=True, variable_group=after, secrets_sent=sent, secrets_deleted=deleted,
                  diff=dict(before=before, after=after))
    return result


def main():
    argument_spec = semaphore_argument_spec()
    argument_spec.update(
        project=dict(type='str'),
        project_id=dict(type='int'),
        name=dict(type='str', required=True),
        state=dict(type='str', default='present', choices=['present', 'absent']),
        json=dict(type='dict'),
        env=dict(type='dict'),
        secrets=dict(type='list', elements='dict', no_log=False, options=dict(
            name=dict(type='str', required=True),
            type=dict(type='str', default='env', choices=['env', 'var']),
            value=dict(type='str', no_log=True),
        )),
        purge_secrets=dict(type='bool', default=False),
        update_secret=dict(type='str', default='always', choices=['always', 'on_create'], no_log=False),
    )
    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        **semaphore_module_kwargs(mutually_exclusive=[PROJECT_OPTIONS], required_one_of=[PROJECT_OPTIONS])
    )
    run_module(module, lambda client: ensure(module, client), placeholder=dict(variable_group={}, secrets_sent=[], secrets_deleted=[]))


if __name__ == '__main__':
    main()
