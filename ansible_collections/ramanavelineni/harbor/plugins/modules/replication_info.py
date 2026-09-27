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
'''

EXAMPLES = r'''
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
