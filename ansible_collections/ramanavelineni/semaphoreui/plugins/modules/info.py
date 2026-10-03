#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: info
short_description: Read Semaphore UI server information and registered apps
version_added: 0.1.0
description:
  - Reads C(/api/info) (version, enabled features, authentication methods) and
    C(/api/apps) (the apps templates can use) from a Semaphore UI server.
  - Reports whether the server's version is one this collection is tested against.
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
'''

EXAMPLES = r'''
- name: Read server information
  ramanavelineni.semaphoreui.info:
    url: https://semaphore.example.com
    api_token: "{{ semaphore_api_token }}"
  register: semaphore

- name: Stop on a version the collection is not tested with
  ansible.builtin.assert:
    that: semaphore.tested
    fail_msg: "Semaphore {{ semaphore.version }} is not tested with this collection"

- name: Stop if a template app is not registered on the server
  ansible.builtin.assert:
    that: "'terraform' in (semaphore.apps | selectattr('active') | map(attribute='id'))"
'''

RETURN = r'''
version:
  description: Version string the server reports.
  returned: always
  type: str
  sample: v2.19.12
tested:
  description: Whether the server's major.minor version is one this collection is tested against.
  returned: always
  type: bool
  sample: true
info:
  description:
    - The full C(/api/info) response, as the server sends it. The fields depend on the server's version.
  returned: always
  type: dict
  sample:
    version: v2.19.12
    boltdb_used: false
    auth_methods: {}
apps:
  description:
    - The apps the server knows, highest priority first, as returned by C(/api/apps).
    - Semaphore registers an app automatically only when its binary is on the server's C(PATH).
  returned: always
  type: list
  elements: dict
  contains:
    id:
      description: Id of the app, which the template module takes as its C(app).
      type: str
    active:
      description: Whether the app can be used.
      type: bool
    title:
      description: Display name. Empty for the apps Semaphore ships with.
      type: str
    priority:
      description: The app's place in the list; higher comes first.
      type: int
  sample:
    - id: ansible
      active: true
      title: Ansible
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.semaphore import (
    run_module,
    semaphore_argument_spec,
    semaphore_module_kwargs,
    version_is_tested,
)


def read_info(client):
    info = client.info()
    apps = client.get('/apps') or []
    version = info.get('version', '')
    return dict(
        changed=False,
        version=version,
        tested=version_is_tested(version),
        info=info,
        apps=apps,
    )


def main():
    module = AnsibleModule(
        argument_spec=semaphore_argument_spec(),
        supports_check_mode=True,
        **semaphore_module_kwargs()
    )
    run_module(module, read_info)


if __name__ == '__main__':
    main()
