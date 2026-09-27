#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: replication
short_description: Manage Harbor replication rules
version_added: 0.1.0
description:
  - Creates, updates or deletes a replication rule (Administration > Replications), found by its name.
  - A rule either pulls from a registry endpoint into this Harbor (O(src_registry)) or pushes from this
    Harbor to an endpoint (O(dest_registry)).
  - Only the options you set are compared and changed; the others keep their current value.
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
      - Name of the rule. Rules are looked up by this name.
    type: str
    required: true
  state:
    description:
      - V(present) creates the rule or updates it to match.
      - V(absent) deletes it.
    type: str
    choices: [present, absent]
    default: present
  description:
    description:
      - Free-text description.
    type: str
  src_registry:
    description:
      - Name of the registry endpoint to pull from. Makes this a pull rule.
      - Exactly one of O(src_registry) and O(dest_registry) is needed to create a rule; setting one on
        an existing rule switches its direction.
    type: str
  dest_registry:
    description:
      - Name of the registry endpoint to push to. Makes this a push rule.
    type: str
  dest_namespace:
    description:
      - Namespace (project) to replicate into. An empty string keeps the source namespace.
    type: str
  dest_namespace_replace_count:
    description:
      - How many leading path components of the source repository O(dest_namespace) replaces.
        V(-1) (Harbor's default) is the legacy flattening mode.
    type: int
  trigger:
    description:
      - When the rule runs.
    type: dict
    suboptions:
      type:
        description: V(manual), V(scheduled) (O(trigger.cron)) or V(event_based) (on push and delete).
        type: str
        choices: [manual, scheduled, event_based]
        required: true
      cron:
        description:
          - Six-field cron expression for V(scheduled), with seconds first, for example C(0 0 2 * * *).
          - Harbor requires the seconds field to be C(0) and does not allow C(*) for the minutes.
        type: str
  filters:
    description:
      - Which resources are replicated, replacing the rule's current filters as a whole. Order does not matter.
    type: list
    elements: dict
    suboptions:
      type:
        description: V(name) (repository, including the project), V(tag), V(label) or V(resource).
        type: str
        choices: [name, tag, label, resource]
        required: true
      value:
        description:
          - Pattern for V(name) and V(tag) (doublestar globbing, for example C(apps/**)), a list of label
            names for V(label), V(image) or V(artifact) for V(resource).
        type: raw
        required: true
      decoration:
        description: For V(tag) and V(label) only, V(matches) or V(excludes).
        type: str
        choices: [matches, excludes]
  enabled:
    description:
      - Whether the rule runs on its trigger. Defaults to V(true) for a new rule.
    type: bool
  override:
    description:
      - Overwrite resources that already exist at the destination. Defaults to V(true) for a new rule.
    type: bool
  replicate_deletion:
    description:
      - Also replicate deletions.
    type: bool
  speed:
    description:
      - Bandwidth limit per task in KB/s. V(0) means unlimited.
    type: int
  copy_by_chunk:
    description:
      - Copy blobs in chunks.
    type: bool
  single_active_replication:
    description:
      - Skip a run while the previous one is still running. Not allowed with an V(event_based) trigger.
    type: bool
'''

EXAMPLES = r'''
- name: Push everything under apps/ to a DR registry every night
  ramanavelineni.harbor.replication:
    url: https://harbor.example.com
    username: admin
    password: "{{ harbor_admin_password }}"
    name: to-dr
    dest_registry: backup
    trigger:
      type: scheduled
      cron: "0 0 2 * * *"
    filters:
      - type: name
        value: "apps/**"
    override: true
'''

RETURN = r'''
replication:
  description:
    - The rule after the change, or as it would be in check mode, with endpoint names. The local
      Harbor side is null.
    - Empty after a deletion.
  returned: always
  type: dict
  sample:
    id: 1
    name: to-dr
    description: ""
    src_registry: null
    dest_registry: backup
    dest_namespace: ""
    dest_namespace_replace_count: -1
    trigger:
      type: scheduled
      cron: "0 0 2 * * *"
    filters:
      - type: name
        value: "apps/**"
        decoration: ""
    enabled: true
    override: true
    replicate_deletion: false
    speed: 0
    copy_by_chunk: false
    single_active_replication: false
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.harbor.plugins.module_utils.harbor import (
    find_by_name,
    harbor_argument_spec,
    id_from_location,
    run_module,
)
from ansible_collections.ramanavelineni.harbor.plugins.module_utils.replication import (
    filters_key,
    normalize_filter,
    replication_view as view,
    validate_cron,
)

SIMPLE = ('description', 'dest_namespace', 'dest_namespace_replace_count', 'enabled', 'override',
          'replicate_deletion', 'speed', 'copy_by_chunk', 'single_active_replication')
DEFAULTS = dict(description='', src_registry=None, dest_registry=None, dest_namespace='',
                dest_namespace_replace_count=-1, trigger=dict(type='manual', cron=''), filters=[],
                enabled=True, override=True, replicate_deletion=False, speed=0, copy_by_chunk=False,
                single_active_replication=False)


def desired_fields(params):
    """The options set, in replication_view's shape (unset ones left out)."""
    out = dict((k, params[k]) for k in SIMPLE if params[k] is not None)
    if 'speed' in out and out['speed'] < 0:
        out['speed'] = 0
    if params['src_registry'] is not None:
        out.update(src_registry=params['src_registry'], dest_registry=None)
    if params['dest_registry'] is not None:
        out.update(dest_registry=params['dest_registry'], src_registry=None)
    if params['trigger'] is not None:
        ttype = params['trigger']['type']
        cron = params['trigger'].get('cron') or ''
        if ttype == 'scheduled':
            validate_cron(cron)
        else:
            cron = ''
        out['trigger'] = dict(type=ttype, cron=cron)
    if params['filters'] is not None:
        out['filters'] = [normalize_filter(f) for f in params['filters']]
    return out


def differs(field, want, have):
    if field == 'filters':
        return filters_key(want) != filters_key(have)
    return want != have


def build_body(after, registry_ids):
    body = dict(
        name=after['name'], description=after['description'], dest_namespace=after['dest_namespace'],
        dest_namespace_replace_count=after['dest_namespace_replace_count'],
        trigger=dict(type=after['trigger']['type']),
        filters=[dict((k, v) for k, v in f.items() if k != 'decoration' or v) for f in after['filters']],
        enabled=after['enabled'], override=after['override'], deletion=after['replicate_deletion'],
        speed=after['speed'], copy_by_chunk=after['copy_by_chunk'],
        single_active_replication=after['single_active_replication'],
    )
    if after['trigger']['type'] == 'scheduled':
        body['trigger']['trigger_settings'] = dict(cron=after['trigger']['cron'])
    if after['src_registry']:
        body['src_registry'] = dict(id=registry_ids[after['src_registry']])
    if after['dest_registry']:
        body['dest_registry'] = dict(id=registry_ids[after['dest_registry']])
    return body


def ensure(module, client):
    params = module.params
    client.warn_if_untested()
    current = find_by_name(client.list('/replication/policies'), params['name'], 'replication rule')

    if params['state'] == 'absent':
        if not current:
            return dict(changed=False, replication={}, diff=dict(before={}, after={}))
        before = view(current)
        if not module.check_mode:
            client.delete('/replication/policies/%d' % current['id'])
        return dict(changed=True, replication={}, diff=dict(before=before, after={}))

    desired = desired_fields(params)
    registry_ids = dict((r['name'], r['id']) for r in client.list('/registries'))
    for option in ('src_registry', 'dest_registry'):
        if params[option] and params[option] not in registry_ids:
            raise ValueError('Registry %r does not exist.' % params[option])

    before = view(current) if current else {}
    after = dict(before or dict(DEFAULTS, name=params['name'], id=None))
    changed = sorted(f for f, v in desired.items() if not current or differs(f, v, before.get(f)))
    after.update((f, desired[f]) for f in desired)

    if not after['src_registry'] and not after['dest_registry']:
        raise ValueError('Replication rule %r needs src_registry (pull) or dest_registry (push).' % params['name'])
    if after['single_active_replication'] and after['trigger']['type'] == 'event_based':
        raise ValueError('single_active_replication is not allowed with an event_based trigger '
                         '(Harbor answers a bare HTTP 500).')

    if not current:
        if not module.check_mode:
            dummy, headers = client.post('/replication/policies', build_body(after, registry_ids))
            policy_id = id_from_location(headers)
            created = client.get('/replication/policies/%d' % policy_id) if policy_id else \
                find_by_name(client.list('/replication/policies'), params['name'], 'replication rule')
            after = view(created)
        return dict(changed=True, replication=after, diff=dict(before={}, after=after))

    if not changed:
        return dict(changed=False, replication=before, diff=dict(before=before, after=before))
    if not module.check_mode:
        # The update replaces the whole rule (omitted fields become empty and
        # dest_namespace_replace_count -1), so every field goes back.
        client.put('/replication/policies/%d' % current['id'], build_body(after, registry_ids))
    return dict(changed=True, replication=after, diff=dict(before=before, after=after))


def main():
    argument_spec = harbor_argument_spec()
    argument_spec.update(
        name=dict(type='str', required=True),
        state=dict(type='str', default='present', choices=['present', 'absent']),
        description=dict(type='str'),
        src_registry=dict(type='str'),
        dest_registry=dict(type='str'),
        dest_namespace=dict(type='str'),
        dest_namespace_replace_count=dict(type='int'),
        trigger=dict(type='dict', options=dict(
            type=dict(type='str', required=True, choices=['manual', 'scheduled', 'event_based']),
            cron=dict(type='str'),
        )),
        filters=dict(type='list', elements='dict', options=dict(
            type=dict(type='str', required=True, choices=['name', 'tag', 'label', 'resource']),
            value=dict(type='raw', required=True),
            decoration=dict(type='str', choices=['matches', 'excludes']),
        )),
        enabled=dict(type='bool'),
        override=dict(type='bool'),
        replicate_deletion=dict(type='bool'),
        speed=dict(type='int'),
        copy_by_chunk=dict(type='bool'),
        single_active_replication=dict(type='bool'),
    )
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True,
                           mutually_exclusive=[('src_registry', 'dest_registry')])
    run_module(module, lambda client: ensure(module, client))


if __name__ == '__main__':
    main()
