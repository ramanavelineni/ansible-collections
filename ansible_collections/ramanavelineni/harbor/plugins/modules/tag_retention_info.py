#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: tag_retention_info
short_description: Read a Harbor project's tag retention policy
version_added: 0.1.0
description:
  - Reads the tag retention policy of a Harbor project, if it has one.
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
  project:
    description:
      - Name of the project.
    type: str
    required: true
'''

EXAMPLES = r'''
- name: Read the retention policy of the apps project
  ramanavelineni.harbor.tag_retention_info:
    url: https://harbor.example.com
    username: admin
    password: "{{ harbor_admin_password }}"
    project: apps
  register: result
'''

RETURN = r'''
tag_retention:
  description: The policy, in the shape the M(ramanavelineni.harbor.tag_retention) module takes; empty when the project has none.
  returned: always
  type: dict
  sample:
    id: 3
    project: apps
    schedule: "0 0 3 * * *"
    rules:
      - template: latestPushedK
        value: 10
        repositories: "**"
        repositories_decoration: matches
        tags: "**"
        tags_decoration: matches
        untagged: false
        disabled: false
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.harbor.plugins.module_utils.harbor import (
    harbor_argument_spec,
    project_by_name,
    retention_view,
    run_module,
)


def read(module, client):
    client.warn_if_untested()
    project = project_by_name(client, module.params['project'])
    policy_id = (project.get('metadata') or {}).get('retention_id')
    if not policy_id:
        return dict(changed=False, tag_retention={})
    return dict(changed=False, tag_retention=retention_view(client.get('/retentions/%s' % policy_id),
                                                            module.params['project']))


def main():
    argument_spec = harbor_argument_spec()
    argument_spec.update(project=dict(type='str', required=True))
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)
    run_module(module, lambda client: read(module, client))


if __name__ == '__main__':
    main()
