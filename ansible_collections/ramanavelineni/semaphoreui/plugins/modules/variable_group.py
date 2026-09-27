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
    type: str
    required: true
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
    type: dict
  env:
    description:
      - Environment variables for the task's process. Values must be scalars (strings, numbers,
        booleans). Replaces the group's current environment variables as a whole.
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
'''

EXAMPLES = r'''
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
secrets_deleted:
  description: Names of the secrets the module deleted (purged, or recreated with another type).
  returned: always
  type: list
  elements: str
'''

import json

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.semaphore import (
    find_by_name,
    refuse_delete_if_used,
    resolve_project,
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


def ensure(module, client):
    params = module.params
    validate(params)
    client.warn_if_untested()

    project_id = resolve_project(client, params['project'])
    base = '/project/%d' % project_id
    found = find_by_name(client.list(base + '/environment'), params['name'], 'variable group')
    result = dict(changed=False, variable_group={}, secrets_sent=[], secrets_deleted=[])

    if params['state'] == 'absent':
        if not found:
            result.update(diff=dict(before={}, after={}))
            return result
        refuse_delete_if_used(client, '%s/environment/%d' % (base, found['id']), 'variable group', params['name'])
        if not module.check_mode:
            client.delete('%s/environment/%d' % (base, found['id']))
        result.update(changed=True, diff=dict(before=dict(id=found['id'], name=found['name']), after={}))
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
    before = view(current, current_secrets)

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
        project=dict(type='str', required=True),
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
        **semaphore_module_kwargs()
    )
    run_module(module, lambda client: ensure(module, client))


if __name__ == '__main__':
    main()
