#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: configuration
short_description: Manage Harbor's system configuration
version_added: 0.1.0
description:
  - Sets Harbor's system settings (Administration > Configuration), such as authentication (database,
    LDAP, OIDC, UAA, HTTP auth proxy), security, the robot account name prefix, project quotas and
    audit log forwarding.
  - Only the keys you set are compared and changed; every other setting keeps its value.
author:
  - ramanavelineni (@ramanavelineni)
extends_documentation_fragment:
  - ramanavelineni.harbor.auth
  - ramanavelineni.harbor.attributes
attributes:
  check_mode:
    support: full
  diff_mode:
    support: full
options:
  settings:
    description:
      - Settings to apply, by Harbor's API names with their native types, for example
        C(auth_mode), C(oidc_endpoint), C(robot_name_prefix), C(session_timeout).
      - An unknown key or a value of the wrong type fails before anything is sent (Harbor itself
        silently ignores unknown keys).
      - A value that went through a template may arrive as a string. An integer setting therefore also
        takes a string of digits, and a boolean setting also takes V(true), V(false), V(yes), V(no),
        V(on) and V(off) as strings, in any case.
      - Secrets don't belong here; use O(oidc_client_secret), O(ldap_search_password) and
        O(uaa_client_secret), so they are never shown in the output.
      - Harbor only lets C(auth_mode) change while no user other than the admin exists, and
        C(skip_audit_log_database=true) needs C(audit_log_forward_endpoint).
      - A setting that Harbor reports as not editable, and whose value would change, fails the task
        before anything is sent, with the names of those settings. A value that is already in place
        is not a change and passes.
    type: dict
    default: {}
  oidc_client_secret:
    description:
      - The OIDC client secret. Harbor never returns it; see O(update_secret).
    type: str
  ldap_search_password:
    description:
      - Password of the LDAP search DN. Harbor never returns it; see O(update_secret).
    type: str
  uaa_client_secret:
    description:
      - The UAA client secret. Harbor returns this one, so it is compared like any setting, but it
        is never included in the module's output.
    type: str
  update_secret:
    description:
      - For O(oidc_client_secret) and O(ldap_search_password), which Harbor never returns.
      - V(always) sends them on every run, so the task always reports C(changed) when one is set.
      - V(on_create) sends one only while its client is being set up, that is when its partner setting
        (C(oidc_client_id) or C(ldap_search_dn)) is currently empty or changes in the same task.
    type: str
    choices: [always, on_create]
    default: always
'''

EXAMPLES = r'''
- name: OIDC login through Dex
  ramanavelineni.harbor.configuration:
    settings:
      auth_mode: oidc_auth
      oidc_name: dex
      oidc_endpoint: https://dex.example.com
      oidc_client_id: harbor
      oidc_scope: openid,profile,email,groups,offline_access
      oidc_groups_claim: groups
      oidc_admin_group: harbor-admins
      oidc_auto_onboard: true
      oidc_user_claim: preferred_username
    oidc_client_secret: "{{ vault_harbor_oidc_client_secret }}"

- name: Robot accounts named bot+<name>, 60-minute sessions
  ramanavelineni.harbor.configuration:
    settings:
      robot_name_prefix: bot+
      session_timeout: 60
'''

RETURN = r'''
configuration:
  description:
    - Every setting's value after the change, or as it would be after it in check mode, by API name.
    - Secrets are never included. A key this module does not know is left out as well when its name
      contains C(secret), C(password), C(passwd), C(token), C(credential) or C(private_key), so that a
      secret a newer Harbor adds is not shown.
  returned: always
  type: dict
  sample:
    auth_mode: oidc_auth
    robot_name_prefix: robot$
    session_timeout: 60
changed_settings:
  description: Names of the settings that were changed or (secrets) sent.
  returned: always
  type: list
  elements: str
  sample: [session_timeout]
'''

import re

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.harbor.plugins.module_utils.configuration import (
    READABLE_SECRETS,
    SETTING_TYPES,
    WRITE_ONLY,
    flat,
    locked,
)
from ansible_collections.ramanavelineni.harbor.plugins.module_utils.harbor import (
    harbor_argument_spec,
    run_module,
)

TYPE_NAMES = {str: 'a string', bool: 'a boolean', int: 'an integer'}

BOOL_WORDS = dict(true=True, yes=True, on=True, false=False, no=False, off=False)


def coerce(value, wanted):
    """`value` as the setting's type, or None when it can't be read as one.

    Values that went through a template may arrive as strings ("60",
    "true"), depending on the ansible-core version.
    """
    if wanted is bool:
        if isinstance(value, bool):
            return value
        return BOOL_WORDS.get(value.strip().lower()) if isinstance(value, str) else None
    if wanted is int:
        # bool is a subclass of int: an integer setting must not take true/false.
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str) and re.match(r'^[+-]?\d+$', value.strip()):
            return int(value.strip())
        return None
    return value if isinstance(value, str) else None


def validate(settings):
    """The settings with every value in its setting's type; fails on anything Harbor would not take."""
    out = {}
    for key, value in settings.items():
        if key in WRITE_ONLY or key in READABLE_SECRETS:
            raise ValueError('%s is a secret; set it with the %s option instead of in settings, so it '
                             'is never shown in the output.' % (key, key))
        if key == 'scan_all_policy':
            raise ValueError('scan_all_policy is read-only; use the scan_all module for the Scan All schedule.')
        wanted = SETTING_TYPES.get(key)
        if wanted is None:
            raise ValueError('Unknown setting %r. Harbor would ignore it silently. Known settings: %s.'
                             % (key, ', '.join(sorted(SETTING_TYPES))))
        coerced = coerce(value, wanted)
        if coerced is None:
            raise ValueError('Setting %s must be %s, not %r.' % (key, TYPE_NAMES[wanted], value))
        out[key] = coerced
    return out


def ensure(module, client):
    params = module.params
    settings = validate(params['settings'] or {})
    client.warn_if_untested()

    raw = client.get('/configurations') or {}
    before = flat(raw)
    changed = sorted(k for k, v in settings.items() if before.get(k) != v)
    body = dict((k, settings[k]) for k in changed)

    for key in READABLE_SECRETS:
        current = raw.get(key)
        if isinstance(current, dict):
            current = current.get('value')
        if params[key] is not None and params[key] != current:
            body[key] = params[key]
    # Harbor refuses these, some with a message that doesn't say which key it
    # was. A declared value that is already in place is not in `body`.
    refused = locked(raw, body)
    if refused:
        raise ValueError(
            'Harbor reports %s as not editable at the moment, so %s cannot be changed: %s.%s'
            % ('this setting' if len(refused) == 1 else 'these settings',
               'it' if len(refused) == 1 else 'they', ', '.join(refused),
               ' auth_mode can only change while no user other than the admin exists.'
               if 'auth_mode' in refused else ''))
    for key, partner in WRITE_ONLY.items():
        value = params[key]
        if value is None:
            continue
        setting_up = not before.get(partner) or partner in changed
        if params['update_secret'] == 'always' or setting_up:
            body[key] = value

    after = dict(before)
    after.update((k, settings[k]) for k in changed)
    sent = sorted(body)
    if not body:
        return dict(changed=False, configuration=before, changed_settings=[],
                    diff=dict(before=dict((k, before.get(k)) for k in settings),
                              after=dict((k, before.get(k)) for k in settings)))

    if not module.check_mode:
        # A partial PUT: Harbor changes only the keys sent.
        client.put('/configurations', body)
        after = flat(client.get('/configurations'))
    diff_keys = sorted(set(settings) | set(changed))
    return dict(changed=True, configuration=after, changed_settings=sent,
                diff=dict(before=dict((k, before.get(k)) for k in diff_keys),
                          after=dict((k, after.get(k)) for k in diff_keys)))


def main():
    argument_spec = harbor_argument_spec()
    argument_spec.update(
        settings=dict(type='dict', default={}),
        oidc_client_secret=dict(type='str', no_log=True),
        ldap_search_password=dict(type='str', no_log=True),
        uaa_client_secret=dict(type='str', no_log=True),
        update_secret=dict(type='str', default='always', choices=['always', 'on_create'], no_log=False),
    )
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)
    run_module(module, lambda client: ensure(module, client))


if __name__ == '__main__':
    main()
