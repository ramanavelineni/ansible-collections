#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: registry_info
short_description: List Harbor registry endpoints
version_added: 0.1.0
description:
  - Lists the registry endpoints (Administration > Registries), optionally only the one with a given
    name. Secrets are never returned.
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
      - Only return endpoints with this name.
    type: str
'''

EXAMPLES = r'''
- name: List the registry endpoints
  ramanavelineni.harbor.registry_info:
    url: https://harbor.example.com
    username: admin
    password: "{{ harbor_admin_password }}"
  register: result
'''

RETURN = r'''
registries:
  description: Matching endpoints, sorted by name. C(has_secret) says whether a secret is stored.
  returned: always
  type: list
  elements: dict
  sample:
    - id: 3
      name: dockerhub
      type: docker-hub
      url: https://hub.docker.com
      description: ""
      insecure: false
      credential_type: ""
      access_key: ""
      has_secret: false
      ca_certificate: ""
      status: healthy
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.harbor.plugins.module_utils.harbor import (
    harbor_argument_spec,
    run_module,
)
from ansible_collections.ramanavelineni.harbor.plugins.module_utils.replication import registry_view


def list_registries(module, client):
    client.warn_if_untested()
    out = [registry_view(r) for r in client.list('/registries')
           if module.params['name'] is None or r.get('name') == module.params['name']]
    return dict(changed=False, registries=sorted(out, key=lambda r: (r['name'] or '', r['id'] or 0)))


def main():
    argument_spec = harbor_argument_spec()
    argument_spec.update(name=dict(type='str'))
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)
    run_module(module, lambda client: list_registries(module, client))


if __name__ == '__main__':
    main()
