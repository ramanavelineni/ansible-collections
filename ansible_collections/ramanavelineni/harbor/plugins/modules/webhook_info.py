#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: webhook_info
short_description: List the webhooks of a Harbor project
version_added: 0.1.0
description:
  - Lists a project's webhooks, optionally only the one with a given name. Auth headers are never
    returned; C(auth_header_set) says whether a webhook has one.
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
  name:
    description:
      - Only return webhooks with this name.
    type: str
seealso:
  - module: ramanavelineni.harbor.webhook
    description: Manage a project's webhooks.
'''

EXAMPLES = r'''
# The connection options (url, username, password) can be set once instead of on every task, with
# module_defaults for the group/ramanavelineni.harbor.harbor action group, or with the HARBOR_URL,
# HARBOR_USERNAME and HARBOR_PASSWORD environment variables.

- name: List the webhooks of the apps project
  ramanavelineni.harbor.webhook_info:
    url: https://harbor.example.com
    username: admin
    password: "{{ harbor_admin_password }}"
    project: apps
  register: result
'''

RETURN = r'''
webhooks:
  description: Matching webhooks, sorted by name. C(endpoints) is the number of endpoints; the other
    target fields describe the first one.
  returned: always
  type: list
  elements: dict
  sample:
    - id: 3
      name: ci-notify
      project: apps
      project_id: 2
      description: ""
      enabled: true
      event_types: [DELETE_ARTIFACT, PUSH_ARTIFACT]
      notify_type: http
      address: https://ci.example.com/hooks/harbor
      auth_header_set: true
      skip_cert_verify: false
      payload_format: Default
      endpoints: 1
  contains:
    id:
      description: Harbor's id of the webhook.
      type: int
    name:
      description: Name of the webhook.
      type: str
    project:
      description: Name of the project the webhook belongs to.
      type: str
    project_id:
      description: Harbor's id of that project.
      type: int
    description:
      description: Description, empty when there is none.
      type: str
    enabled:
      description: Whether the webhook sends notifications.
      type: bool
    event_types:
      description: The events that trigger a notification, sorted.
      type: list
      elements: str
    notify_type:
      description: V(http) or V(slack).
      type: str
    address:
      description: The endpoint URL the notifications are sent to.
      type: str
    auth_header_set:
      description: Whether an auth header is stored. The header itself is never returned.
      type: bool
    skip_cert_verify:
      description: Whether notifications are sent without verifying the endpoint's TLS certificate.
      type: bool
    payload_format:
      description: Format of the V(http) notification body, V(null) when Harbor reports none.
      type: str
    endpoints:
      description: Number of endpoints the webhook has. The target fields above describe the first one.
      type: int
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.harbor.plugins.module_utils.harbor import (
    harbor_argument_spec,
    require_project,
    run_module,
    webhook_view,
)


def list_webhooks(module, client):
    client.warn_if_untested()
    name = module.params['project']
    project = require_project(client, name)
    out = []
    for policy in client.list('/projects/%d/webhook/policies' % project['project_id']):
        if module.params['name'] is not None and policy.get('name') != module.params['name']:
            continue
        view = webhook_view(policy, name)
        view['endpoints'] = len(policy.get('targets') or [])
        out.append(view)
    return dict(changed=False, webhooks=sorted(out, key=lambda w: (w['name'] or '', w['id'] or 0)))


def main():
    argument_spec = harbor_argument_spec()
    argument_spec.update(project=dict(type='str', required=True), name=dict(type='str'))
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)
    run_module(module, lambda client: list_webhooks(module, client))


if __name__ == '__main__':
    main()
