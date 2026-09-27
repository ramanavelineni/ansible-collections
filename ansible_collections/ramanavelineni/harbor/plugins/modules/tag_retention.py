#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: tag_retention
short_description: Manage a Harbor project's tag retention policy
version_added: 0.1.0
description:
  - Creates, updates or deletes the tag retention policy of a Harbor project, with its rules and its
    schedule. A project has at most one policy.
  - Rules B(retain) artifacts and are combined with OR. When the policy runs, an artifact is
    B(deleted) unless at least one rule keeps it. Preview a new rule set with the project's dry run
    in the Harbor UI before giving it a schedule.
  - Only the options you set are compared and changed. O(rules), when set, is the complete list.
  - The module never starts a retention run.
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
      - V(present) creates the policy or updates it to match.
      - V(absent) deletes the policy (the artifacts are not touched).
    type: str
    choices: [present, absent]
    default: present
  schedule:
    description:
      - When the policy runs, as a 6-field cron expression (seconds first), for example C(0 0 3 * * *).
      - An empty string means no schedule; the policy then only runs when started by hand.
      - Defaults to no schedule for a new policy.
    type: str
  rules:
    description:
      - The retention rules, in order; at most 15. Two identical rules are not allowed.
      - Defaults to no rules for a new policy (which retains nothing when run by hand).
    type: list
    elements: dict
    suboptions:
      template:
        description:
          - What the rule keeps, as Harbor's rule template.
          - V(latestPushedK) the most recently pushed O(rules[].value) artifacts,
            V(latestPulledN) the most recently pulled O(rules[].value) artifacts,
            V(nDaysSinceLastPush) artifacts pushed within the last O(rules[].value) days,
            V(nDaysSinceLastPull) artifacts pulled within the last O(rules[].value) days,
            V(always) every artifact.
        type: str
        required: true
        choices: [latestPushedK, latestPulledN, nDaysSinceLastPush, nDaysSinceLastPull, always]
      value:
        description:
          - The count or number of days. Required for every template except V(always), which takes none.
        type: int
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
        description: Doublestar pattern for the tags the rule applies to.
        type: str
        default: '**'
      tags_decoration:
        description: Whether the rule applies to the tags that V(matches) or V(excludes) the pattern.
        type: str
        choices: [matches, excludes]
        default: matches
      untagged:
        description: Whether untagged artifacts count as matching the tag pattern too.
        type: bool
        default: false
      disabled:
        description: Whether the rule is switched off.
        type: bool
        default: false
notes:
  - Harbor accepts rules with an unknown template or a missing number and stores them as they are,
    so the module checks them before sending anything.
'''

EXAMPLES = r'''
- name: Keep the 10 newest artifacts of every repository, pruned nightly
  ramanavelineni.harbor.tag_retention:
    url: https://harbor.example.com
    username: admin
    password: "{{ harbor_admin_password }}"
    project: apps
    schedule: "0 0 3 * * *"
    rules:
      - template: latestPushedK
        value: 10
      - template: nDaysSinceLastPull
        value: 180

- name: Remove the policy
  ramanavelineni.harbor.tag_retention:
    url: https://harbor.example.com
    username: admin
    password: "{{ harbor_admin_password }}"
    project: apps
    state: absent
'''

RETURN = r'''
tag_retention:
  description:
    - The policy after the change, or as it would be in check mode.
    - Empty after a deletion.
  returned: always
  type: dict
  sample:
    id: 3
    project: apps
    schedule: "0 0 3 * * *"
    rules:
      - template: latestPushedK
        value: 10
        repositories: "**"
        repositories_decoration: matches
        tags: "**"
        tags_decoration: matches
        untagged: false
        disabled: false
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.harbor.plugins.module_utils.harbor import (
    RETENTION_TEMPLATES,
    harbor_argument_spec,
    id_from_location,
    project_by_name,
    retention_view,
    run_module,
    selectors_body,
)

MAX_RULES = 15
RULE_FIELDS = ('template', 'value', 'repositories', 'repositories_decoration', 'tags', 'tags_decoration',
               'untagged', 'disabled')


def desired_rules(rules):
    """The rules option, checked, in the shape retention_view returns."""
    if len(rules) > MAX_RULES:
        raise ValueError('A retention policy holds at most %d rules, not %d.' % (MAX_RULES, len(rules)))
    out = []
    for n, rule in enumerate(rules, 1):
        unit = RETENTION_TEMPLATES[rule['template']]
        if unit is None and rule['value'] is not None:
            raise ValueError('Rule %d: template always takes no value.' % n)
        if unit is not None and (rule['value'] is None or rule['value'] < 1):
            raise ValueError('Rule %d: template %s needs value, a %s of at least 1.' % (n, rule['template'], unit))
        view = dict((k, rule[k]) for k in RULE_FIELDS)
        if view in out:
            raise ValueError('Rules %d and %d are identical; Harbor refuses duplicate rules.' % (out.index(view) + 1, n))
        out.append(view)
    return out


def policy_body(project_id, schedule, rules):
    body_rules = []
    for rule in rules:
        body = dict(disabled=rule['disabled'], action='retain', template=rule['template'],
                    params={} if rule['value'] is None else {rule['template']: rule['value']})
        body.update(selectors_body(rule, with_untagged=True))
        body_rules.append(body)
    return dict(algorithm='or', scope=dict(level='project', ref=project_id),
                trigger=dict(kind='Schedule', settings=dict(cron=schedule)), rules=body_rules)


def ensure(module, client):
    params = module.params
    client.warn_if_untested()
    rules = desired_rules(params['rules']) if params['rules'] is not None else None

    project = project_by_name(client, params['project'])
    project_id = project['project_id']
    policy_id = (project.get('metadata') or {}).get('retention_id')
    current = client.get('/retentions/%s' % policy_id) if policy_id else None
    before = retention_view(current, params['project']) if current else {}

    if params['state'] == 'absent':
        if not current:
            return dict(changed=False, tag_retention={}, diff=dict(before={}, after={}))
        if not module.check_mode:
            client.delete('/retentions/%s' % policy_id)
        return dict(changed=True, tag_retention={}, diff=dict(before=before, after={}))

    after = dict(before) if current else dict(id=None, project=params['project'], schedule='', rules=[])
    if params['schedule'] is not None:
        after['schedule'] = params['schedule']
    if rules is not None:
        after['rules'] = rules
    if current and after == before:
        return dict(changed=False, tag_retention=before, diff=dict(before=before, after=before))

    body = policy_body(project_id, after['schedule'], after['rules'])
    if not module.check_mode:
        if current:
            client.put('/retentions/%s' % policy_id, body)
        else:
            dummy, headers = client.post('/retentions', body)
            after['id'] = id_from_location(headers)
    return dict(changed=True, tag_retention=after, diff=dict(before=before, after=after))


def main():
    argument_spec = harbor_argument_spec()
    argument_spec.update(
        project=dict(type='str', required=True),
        state=dict(type='str', default='present', choices=['present', 'absent']),
        schedule=dict(type='str'),
        rules=dict(type='list', elements='dict', options=dict(
            template=dict(type='str', required=True, choices=sorted(RETENTION_TEMPLATES)),
            value=dict(type='int'),
            repositories=dict(type='str', default='**'),
            repositories_decoration=dict(type='str', default='matches', choices=['matches', 'excludes']),
            tags=dict(type='str', default='**'),
            tags_decoration=dict(type='str', default='matches', choices=['matches', 'excludes']),
            untagged=dict(type='bool', default=False),
            disabled=dict(type='bool', default=False),
        )),
    )
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)
    run_module(module, lambda client: ensure(module, client))


if __name__ == '__main__':
    main()
