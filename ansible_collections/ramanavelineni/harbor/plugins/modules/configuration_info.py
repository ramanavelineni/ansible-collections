#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: configuration_info
short_description: Read Harbor's system configuration
version_added: 0.1.0
description:
  - Reads every system setting (Administration > Configuration) by its API name. Secrets are never
    included.
  - A key this collection does not know is left out as well when its name contains C(secret),
    C(password), C(passwd), C(token), C(credential) or C(private_key), so that a secret a newer Harbor
    adds is not shown.
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
seealso:
  - module: ramanavelineni.harbor.configuration
    description: Change Harbor's system configuration.
'''

EXAMPLES = r'''
# The connection options (url, username, password) are left out of these examples. Set them once with
# module_defaults for the group/ramanavelineni.harbor.harbor action group, or with the HARBOR_URL,
# HARBOR_USERNAME and HARBOR_PASSWORD environment variables.

- name: Read the configuration
  ramanavelineni.harbor.configuration_info:
  register: harbor_config

- name: Show the authentication mode
  ansible.builtin.debug:
    msg: "{{ harbor_config.configuration.auth_mode }}"
'''

RETURN = r'''
configuration:
  description: Every setting's value by API name, secrets left out.
  returned: always
  type: dict
  sample:
    auth_mode: db_auth
    robot_name_prefix: robot$
    session_timeout: 60
auth_mode_editable:
  description: Whether auth_mode can still change (only while no user other than the admin exists).
  returned: always
  type: bool
  sample: true
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.harbor.plugins.module_utils.configuration import flat
from ansible_collections.ramanavelineni.harbor.plugins.module_utils.harbor import (
    harbor_argument_spec,
    run_module,
)


def read(module, client):
    client.warn_if_untested()
    raw = client.get('/configurations') or {}
    auth = raw.get('auth_mode')
    # flat() keeps secrets out: Harbor returns the UAA client secret in clear text.
    return dict(changed=False, configuration=flat(raw),
                auth_mode_editable=bool(auth.get('editable')) if isinstance(auth, dict) else False)


def main():
    module = AnsibleModule(argument_spec=harbor_argument_spec(), supports_check_mode=True)
    run_module(module, lambda client: read(module, client))


if __name__ == '__main__':
    main()
