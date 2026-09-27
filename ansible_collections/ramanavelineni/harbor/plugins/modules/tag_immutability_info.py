#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: tag_immutability_info
short_description: List the tag immutability rules of a Harbor project
version_added: 0.1.0
description:
  - Lists the tag immutability rules of a Harbor project.
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
- name: List the immutability rules of the apps project
  ramanavelineni.harbor.tag_immutability_info:
    url: https://harbor.example.com
    username: admin
    password: "{{ harbor_admin_password }}"
    project: apps
  register: result
'''

RETURN = r'''
tag_immutability:
  description: The rules, in the shape the M(ramanavelineni.harbor.tag_immutability) module takes, sorted by id.
  returned: always
  type: list
  elements: dict
  sample:
    - id: 1
      project: apps
      repositories: "**"
      repositories_decoration: matches
      tags: "v*"
      tags_decoration: matches
      disabled: false
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.harbor.plugins.module_utils.harbor import (
    harbor_argument_spec,
    immutability_rule_view,
    project_by_name,
    run_module,
)


def read(module, client):
    client.warn_if_untested()
    project = project_by_name(client, module.params['project'])
    rules = client.list('/projects/%d/immutabletagrules' % project['project_id'])
    return dict(changed=False, tag_immutability=sorted(
        (immutability_rule_view(r, module.params['project']) for r in rules), key=lambda r: r['id'] or 0))


def main():
    argument_spec = harbor_argument_spec()
    argument_spec.update(project=dict(type='str', required=True))
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)
    run_module(module, lambda client: read(module, client))


if __name__ == '__main__':
    main()
