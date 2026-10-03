#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: integration_info
short_description: List the integrations (inbound webhooks) in a Semaphore UI project
version_added: 0.1.0
description:
  - Lists a project's integrations, optionally only the one with a given name, with their
    matchers, extracted values and webhook URLs.
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
      - Only return integrations with this name.
    type: str
'''

EXAMPLES = r'''
- name: Webhook URLs of the homelab project's integrations
  ramanavelineni.semaphoreui.integration_info:
    project: homelab
  register: result
'''

RETURN = r'''
integrations:
  description: Matching integrations, sorted by name, each with C(webhook_urls).
  returned: always
  type: list
  elements: dict
  sample:
    - id: 1
      name: gh-push
      template: harbor_config
      auth_method: github
      auth_key: github-webhook-secret
      auth_header: ""
      searchable: false
      matchers: []
      extract_values: []
      webhook_urls: ["https://semaphore.example.com/api/integrations/Kx8t3VqfL2cM9aZp"]
      project_id: 1
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.semaphore import (
    PROJECT_OPTIONS,
    integration_view,
    project_ref,
    run_module,
    semaphore_argument_spec,
    semaphore_module_kwargs,
)


def list_integrations(module, client):
    client.warn_if_untested()
    base = '/project/%d' % project_ref(client, module.params)[0]
    tpl_names = dict((t['id'], t['name']) for t in client.list(base + '/templates'))
    key_names = dict((k['id'], k['name']) for k in client.list(base + '/keys'))
    out = []
    for integ in client.list(base + '/integrations'):
        if module.params['name'] is not None and integ.get('name') != module.params['name']:
            continue
        path = '%s/integrations/%d' % (base, integ['id'])
        view = integration_view(integ, tpl_names, key_names, client.list(path + '/matchers'), client.list(path + '/values'))
        view['webhook_urls'] = [a.get('url') for a in client.list(path + '/aliases')]
        out.append(view)
    return dict(changed=False, integrations=sorted(out, key=lambda i: (i['name'] or '', i['id'] or 0)))


def main():
    argument_spec = semaphore_argument_spec()
    argument_spec.update(project=dict(type='str'), project_id=dict(type='int'), name=dict(type='str'))
    module = AnsibleModule(
        argument_spec=argument_spec, supports_check_mode=True,
        **semaphore_module_kwargs(mutually_exclusive=[PROJECT_OPTIONS], required_one_of=[PROJECT_OPTIONS])
    )
    run_module(module, lambda client: list_integrations(module, client))


if __name__ == '__main__':
    main()
