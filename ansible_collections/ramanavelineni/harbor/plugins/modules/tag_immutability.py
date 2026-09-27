#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: tag_immutability
short_description: Manage a tag immutability rule of a Harbor project
version_added: 0.1.0
description:
  - Creates, enables, disables or deletes one tag immutability rule of a Harbor project. Tags the
    rule matches cannot be overwritten or deleted.
  - A rule is identified by what it matches, that is O(repositories), O(repositories_decoration),
    O(tags) and O(tags_decoration). A rule with other patterns is another rule. Only O(disabled) is
    changed in place.
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
  project:
    description:
      - Name of the project.
    type: str
    required: true
  state:
    description:
      - V(present) creates the rule, or switches it on or off to match O(disabled).
      - V(absent) deletes it.
    type: str
    choices: [present, absent]
    default: present
  repositories:
    description: Doublestar pattern for the repositories the rule applies to.
    type: str
    default: '**'
  repositories_decoration:
    description: Whether the rule applies to the repositories that V(matches) or V(excludes) the pattern.
    type: str
    choices: [matches, excludes]
    default: matches
  tags:
    description: Doublestar pattern for the immutable tags.
    type: str
    required: true
  tags_decoration:
    description: Whether the tags that V(matches) or V(excludes) the pattern are immutable.
    type: str
    choices: [matches, excludes]
    default: matches
  disabled:
    description:
      - Whether the rule is switched off. Defaults to V(false) for a new rule.
    type: bool
'''

EXAMPLES = r'''
- name: Release tags can't be overwritten
  ramanavelineni.harbor.tag_immutability:
    url: https://harbor.example.com
    username: admin
    password: "{{ harbor_admin_password }}"
    project: apps
    tags: "v*"

- name: Switch the rule off without deleting it
  ramanavelineni.harbor.tag_immutability:
    url: https://harbor.example.com
    username: admin
    password: "{{ harbor_admin_password }}"
    project: apps
    tags: "v*"
    disabled: true
'''

RETURN = r'''
tag_immutability:
  description:
    - The rule after the change, or as it would be in check mode.
    - Empty after a deletion.
  returned: always
  type: dict
  sample:
    id: 1
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
    id_from_location,
    immutability_rule_view,
    project_by_name,
    run_module,
    selectors_body,
)

SIGNATURE = ('repositories', 'repositories_decoration', 'tags', 'tags_decoration')


def rule_body(options, disabled, rule_id=None):
    body = dict(disabled=disabled, action='immutable', template='immutable_template')
    body.update(selectors_body(options, with_untagged=False))
    if rule_id is not None:
        body['id'] = rule_id
    return body


def ensure(module, client):
    params = module.params
    client.warn_if_untested()
    project = project_by_name(client, params['project'])
    base = '/projects/%d/immutabletagrules' % project['project_id']
    wanted = dict((k, params[k]) for k in SIGNATURE)

    matches = [r for r in client.list(base)
               if dict((k, v) for k, v in immutability_rule_view(r, params['project']).items() if k in SIGNATURE) == wanted]
    current = matches[0] if matches else None
    before = immutability_rule_view(current, params['project']) if current else {}

    if params['state'] == 'absent':
        if not current:
            return dict(changed=False, tag_immutability={}, diff=dict(before={}, after={}))
        if not module.check_mode:
            client.delete('%s/%d' % (base, current['id']))
        return dict(changed=True, tag_immutability={}, diff=dict(before=before, after={}))

    disabled = params['disabled']
    if current:
        if disabled is None or disabled == before['disabled']:
            return dict(changed=False, tag_immutability=before, diff=dict(before=before, after=before))
        after = dict(before, disabled=disabled)
        if not module.check_mode:
            # An update whose "disabled" differs from the stored value only
            # switches the rule on or off; Harbor ignores the rest of the body.
            client.put('%s/%d' % (base, current['id']), rule_body(wanted, disabled, current['id']))
        return dict(changed=True, tag_immutability=after, diff=dict(before=before, after=after))

    after = dict(wanted, id=None, project=params['project'], disabled=bool(disabled))
    if not module.check_mode:
        dummy, headers = client.post(base, rule_body(wanted, False))
        after['id'] = id_from_location(headers)
        if disabled:
            # Harbor stores every new rule enabled, whatever the request says.
            client.put('%s/%d' % (base, after['id']), rule_body(wanted, True, after['id']))
    return dict(changed=True, tag_immutability=after, diff=dict(before={}, after=after))


def main():
    argument_spec = harbor_argument_spec()
    argument_spec.update(
        project=dict(type='str', required=True),
        state=dict(type='str', default='present', choices=['present', 'absent']),
        repositories=dict(type='str', default='**'),
        repositories_decoration=dict(type='str', default='matches', choices=['matches', 'excludes']),
        tags=dict(type='str', required=True),
        tags_decoration=dict(type='str', default='matches', choices=['matches', 'excludes']),
        disabled=dict(type='bool'),
    )
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)
    run_module(module, lambda client: ensure(module, client))


if __name__ == '__main__':
    main()
