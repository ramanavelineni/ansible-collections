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
      - Only return templates with this name.
    type: str
notes:
  - Semaphore's template list leaves out each template's vaults, so every matching template is also
    read on its own.
seealso:
  - module: ramanavelineni.semaphoreui.template
    description: Creates, changes and deletes templates.
  - module: ramanavelineni.semaphoreui.project
    description: Manages the project.
'''

EXAMPLES = r'''
# The connection options (url and api_token, or username and password) are left out here. Set them once
# with module_defaults, or in the SEMAPHORE_URL and SEMAPHORE_API_TOKEN environment variables; the
# collection's README shows both under "Connecting".

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
  contains:
    id:
      description: Template id.
      type: int
    name:
      description: Name of the template.
      type: str
    app:
      description: The tool the template runs.
      type: str
    playbook:
      description: Path of the playbook or script in the repository.
      type: str
    description:
      description: Free-text description.
      type: str
    repository:
      description: Name of the repository the template runs from.
      type: str
    inventory:
      description: Name of the inventory. Null when there is none.
      type: str
    variable_groups:
      description: Names of the variable groups the template uses, in order.
      type: list
      elements: str
    view:
      description: Title of the view (tab) the template appears in. Null when it is in none.
      type: str
    git_branch:
      description: Branch to run from instead of the repository's. Empty when not set.
      type: str
    arguments:
      description: Extra command-line arguments.
      type: list
      elements: str
    type:
      description: V(task), V(build) or V(deploy).
      type: str
    start_version:
      description: First version number of a V(build) template. Empty for the other types.
      type: str
    build_template:
      description: Name of the V(build) template a V(deploy) template deploys. Null for the other types.
      type: str
    runner_tag:
      description: Tag a runner needs to run the template. Empty when not set.
      type: str
    task_params:
      description: App-specific settings.
      type: dict
    vaults:
      description: Ansible Vault passwords passed to the playbook, sorted by name.
      type: list
      elements: dict
      contains:
        name:
          description: Vault id.
          type: str
        type:
          description: V(password) or V(script).
          type: str
        key:
          description: Name of the key that holds the vault password. Null for V(script).
          type: str
        script:
          description: Path of the vault client script. Empty for V(password).
          type: str
    survey_vars:
      description: Variables the user is asked for when starting a task.
      type: list
      elements: dict
      contains:
        name:
          description: Variable name.
          type: str
        title:
          description: Label shown to the user.
          type: str
        type:
          description: V(string), V(int), V(enum) or V(text).
          type: str
        required:
          description: Whether a value must be given.
          type: bool
        description:
          description: Help text.
          type: str
        default_value:
          description: Value filled in by default.
          type: str
        values:
          description: Choices for V(enum), each with a C(name) and a C(value).
          type: list
          elements: dict
    autorun:
      description: Whether a V(deploy) template runs after each successful build.
      type: bool
    allow_override_args_in_task:
      description: Whether users may change the arguments when they start a task.
      type: bool
    allow_override_branch_in_task:
      description: Whether users may choose the branch when they start a task.
      type: bool
    allow_parallel_tasks:
      description: Whether more than one task of the template may run at the same time.
      type: bool
    suppress_success_alerts:
      description: Whether alerts are sent only for failed tasks.
      type: bool
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
    PROJECT_OPTIONS,
    project_ref,
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
    project_id, project = project_ref(client, module.params)
    base = '/project/%d' % project_id
    lookups = Lookups(client, base, project)
    out = []
    for tpl in lookups.items['template']:
        if module.params['name'] is not None and tpl.get('name') != module.params['name']:
            continue
        full = client.get('%s/templates/%d' % (base, tpl['id'])) or tpl
        out.append(template_view(full, lookups))
    return dict(changed=False, templates=sorted(out, key=lambda t: (t['name'] or '', t['id'] or 0)))


def main():
    argument_spec = semaphore_argument_spec()
    argument_spec.update(project=dict(type='str'), project_id=dict(type='int'), name=dict(type='str'))
    module = AnsibleModule(
        argument_spec=argument_spec, supports_check_mode=True,
        **semaphore_module_kwargs(mutually_exclusive=[PROJECT_OPTIONS], required_one_of=[PROJECT_OPTIONS])
    )
    run_module(module, lambda client: list_templates(module, client))


if __name__ == '__main__':
    main()
