#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: replication_info
short_description: List Harbor replication rules
version_added: 0.1.0
description:
  - Lists the replication rules (Administration > Replications), optionally only the one with a given name.
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
  name:
    description:
      - Only return rules with this name.
    type: str
seealso:
  - module: ramanavelineni.harbor.replication
    description: Manage replication rules.
  - module: ramanavelineni.harbor.registry_info
    description: List registry endpoints.
'''

EXAMPLES = r'''
# The connection options (url, username, password) can be set once instead of on every task, with
# module_defaults for the group/ramanavelineni.harbor.harbor action group, or with the HARBOR_URL,
# HARBOR_USERNAME and HARBOR_PASSWORD environment variables.

- name: List the replication rules
  ramanavelineni.harbor.replication_info:
    url: https://harbor.example.com
    username: admin
    password: "{{ harbor_admin_password }}"
  register: result
'''

RETURN = r'''
replications:
  description: Matching rules, sorted by name, with endpoint names. The local Harbor side is null.
  returned: always
  type: list
  elements: dict
  sample:
    - id: 1
      name: to-dr
      description: ""
      src_registry: null
      dest_registry: backup
      dest_namespace: ""
      dest_namespace_replace_count: -1
      trigger:
        type: scheduled
        cron: "0 0 2 * * *"
      filters: []
      enabled: true
      override: true
      replicate_deletion: false
      speed: 0
      copy_by_chunk: false
      single_active_replication: false
  contains:
    id:
      description: Harbor's id of the rule.
      type: int
    name:
      description: Name of the rule.
      type: str
    description:
      description: Description, empty when there is none.
      type: str
    src_registry:
      description: Name of the endpoint the rule pulls from, V(null) when the source is this Harbor.
      type: str
    dest_registry:
      description: Name of the endpoint the rule pushes to, V(null) when the destination is this Harbor.
      type: str
    dest_namespace:
      description: Namespace (project) replicated into, empty when the source namespace is kept.
      type: str
    dest_namespace_replace_count:
      description: How many leading path components of the source repository C(dest_namespace) replaces. V(-1) is the legacy flattening mode.
      type: int
    trigger:
      description: When the rule runs.
      type: dict
      contains:
        type:
          description: V(manual), V(scheduled) or V(event_based).
          type: str
        cron:
          description: Six-field cron expression of a V(scheduled) rule, empty otherwise.
          type: str
    filters:
      description: Which resources are replicated.
      type: list
      elements: dict
      contains:
        type:
          description: V(name), V(tag), V(label) or V(resource).
          type: str
        value:
          description: Pattern, resource kind, or a sorted list of label names for a V(label) filter.
          type: raw
        decoration:
          description: V(matches) or V(excludes) for a V(tag) or V(label) filter, empty for the others.
          type: str
    enabled:
      description: Whether the rule runs on its trigger.
      type: bool
    override:
      description: Whether resources that already exist at the destination are overwritten.
      type: bool
    replicate_deletion:
      description: Whether deletions are replicated too.
      type: bool
    speed:
      description: Bandwidth limit per task in KB/s, V(0) for unlimited.
      type: int
    copy_by_chunk:
      description: Whether blobs are copied in chunks.
      type: bool
    single_active_replication:
      description: Whether a run is skipped while the previous one is still running.
      type: bool
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.harbor.plugins.module_utils.harbor import (
    harbor_argument_spec,
    run_module,
)
from ansible_collections.ramanavelineni.harbor.plugins.module_utils.replication import replication_view


def list_rules(module, client):
    client.warn_if_untested()
    out = [replication_view(p) for p in client.list('/replication/policies')
           if module.params['name'] is None or p.get('name') == module.params['name']]
    return dict(changed=False, replications=sorted(out, key=lambda p: (p['name'] or '', p['id'] or 0)))


def main():
    argument_spec = harbor_argument_spec()
    argument_spec.update(name=dict(type='str'))
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)
    run_module(module, lambda client: list_rules(module, client))


if __name__ == '__main__':
    main()
