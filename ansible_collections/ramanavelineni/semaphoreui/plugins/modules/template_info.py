#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: template_info
short_description: List the task templates in a Semaphore UI project
version_added: 0.1.0
description:
  - Lists a project's task templates, optionally only the one with a given name, in the shape the
    M(ramanavelineni.semaphoreui.template) module takes, with names for everything they refer to.
author:
  - ramanavelineni (@ramanavelineni)
extends_documentation_fragment:
  - ramanavelineni.semaphoreui.auth
  - ramanavelineni.semaphoreui.attributes
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
  name:
    description:
      - Only return templates with this name.
    type: str
notes:
  - Semaphore's template list leaves out each template's vaults, so every matching template is also
    read on its own.
'''

EXAMPLES = r'''
- name: List the homelab project's templates
  ramanavelineni.semaphoreui.template_info:
    project: homelab
  register: result

- name: Show one template's vaults
  ramanavelineni.semaphoreui.template_info:
    project: homelab
    name: harbor_config
  register: harbor_config
'''

RETURN = r'''
templates:
  description: Matching templates, sorted by name, in the shape the template module takes.
  returned: always
  type: list
  elements: dict
  sample:
    - id: 3
      name: harbor_config
      app: ansible
      playbook: playbooks/harbor_config.yaml
      repository: ansible
      inventory: homelab
      variable_groups: [empty]
      view: infra
      type: task
      arguments: []
      task_params: {}
      vaults:
        - name: default
          type: password
          key: ansible-vault
          script: ""
      survey_vars: []
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.semaphore import (
    resolve_project,
    run_module,
    semaphore_argument_spec,
    semaphore_module_kwargs,
)
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.template import (
    Lookups,
    template_view,
)


def list_templates(module, client):
    client.warn_if_untested()
    base = '/project/%d' % resolve_project(client, module.params['project'])
    lookups = Lookups(client, base, module.params['project'])
    out = []
    for tpl in lookups.items['template']:
        if module.params['name'] is not None and tpl.get('name') != module.params['name']:
            continue
        full = client.get('%s/templates/%d' % (base, tpl['id'])) or tpl
        out.append(template_view(full, lookups))
    return dict(changed=False, templates=sorted(out, key=lambda t: (t['name'] or '', t['id'] or 0)))


def main():
    argument_spec = semaphore_argument_spec()
    argument_spec.update(project=dict(type='str', required=True), name=dict(type='str'))
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True, **semaphore_module_kwargs())
    run_module(module, lambda client: list_templates(module, client))


if __name__ == '__main__':
    main()
