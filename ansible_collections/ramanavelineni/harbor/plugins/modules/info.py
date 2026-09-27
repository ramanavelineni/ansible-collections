#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: info
short_description: Read Harbor server information
version_added: 0.1.0
description:
  - Reads C(/api/v2.0/systeminfo) from a Harbor server (version, authentication mode and more) and
    reports whether the version is one this collection is tested against.
  - Fails when Harbor does not accept the credentials. Harbor itself answers this endpoint for
    anonymous users too, with less information.
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
'''

EXAMPLES = r'''
- name: Read server information
  ramanavelineni.harbor.info:
    url: https://harbor.example.com
    username: admin
    password: "{{ harbor_admin_password }}"
  register: harbor

- name: Stop on a version the collection is not tested with
  ansible.builtin.assert:
    that: harbor.tested
    fail_msg: "Harbor {{ harbor.version }} is not tested with this collection"
'''

RETURN = r'''
version:
  description: Version string the server reports.
  returned: always
  type: str
  sample: v2.15.2-a97e7b83
tested:
  description: Whether the server's major.minor version is one this collection is tested against.
  returned: always
  type: bool
  sample: true
info:
  description: The full C(/api/v2.0/systeminfo) response.
  returned: always
  type: dict
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.harbor.plugins.module_utils.harbor import (
    harbor_argument_spec,
    run_module,
    version_is_tested,
)


def read_info(client):
    info = client.info()
    version = info.get('harbor_version', '')
    return dict(changed=False, version=version, tested=version_is_tested(version), info=info)


def main():
    module = AnsibleModule(argument_spec=harbor_argument_spec(), supports_check_mode=True)
    run_module(module, read_info)


if __name__ == '__main__':
    main()
