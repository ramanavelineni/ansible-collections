#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: view
short_description: Manage views (template tabs) in a Semaphore UI project
version_added: 0.1.0
description:
  - Creates, updates or deletes a view, one of the tabs that group a project's templates, found
    by its title.
  - Only the options you set are compared and changed; the others keep their current value.
author:
  - ramanavelineni (@ramanavelineni)
extends_documentation_fragment:
  - ramanavelineni.semaphoreui.auth
  - ramanavelineni.semaphoreui.attributes
attributes:
  check_mode:
    support: full
  diff_mode:
    support: full
options:
  project:
    description:
      - Name of the project the view belongs to.
    type: str
    required: true
  name:
    description:
      - Title of the view. Views are looked up by this title within the project.
    type: str
    required: true
  state:
    description:
      - V(present) creates the view or updates it to match.
      - V(absent) deletes it. Templates in the view stay, without a view.
      - The built-in C(All) view, which lists every template, cannot be deleted by this module.
    type: str
    choices: [present, absent]
    default: present
  position:
    description:
      - Place of the tab, from the left. A new view without a position goes after the last one.
    type: int
  hidden:
    description:
      - Whether the tab is hidden.
    type: bool
  sort_column:
    description:
      - Column the view's templates are sorted by, as the UI names it (for example C(name)).
      - An empty string removes the sort.
    type: str
  sort_reverse:
    description:
      - Sort in reverse order.
    type: bool
notes:
  - Which templates a view shows is set on each template (the template module's C(view) option),
    not here.
'''

EXAMPLES = r'''
- name: Tabs for the homelab project
  ramanavelineni.semaphoreui.view:
    project: homelab
    name: "{{ item.name }}"
    position: "{{ item.position }}"
  loop:
    - {name: k8s, position: 1}
    - {name: infra, position: 2}

- name: Hide the built-in All tab
  ramanavelineni.semaphoreui.view:
    project: homelab
    name: All
    hidden: true
'''

RETURN = r'''
view:
  description:
    - The view after the change, or as it would be in check mode.
    - Empty after a deletion.
  returned: always
  type: dict
  sample:
    id: 2
    name: k8s
    position: 1
    hidden: false
    sort_column: ""
    sort_reverse: false
    type: ""
    project_id: 1
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.semaphore import (
    diff_fields,
    find_by_name,
    resolve_project,
    run_module,
    semaphore_argument_spec,
    semaphore_module_kwargs,
)

BUILT_IN = 'all'


def normalize(view):
    return dict(
        id=view.get('id'), name=view.get('title'), position=int(view.get('position') or 0),
        hidden=bool(view.get('hidden', False)), sort_column=view.get('sort_column') or '',
        sort_reverse=bool(view.get('sort_reverse', False)), type=view.get('type') or '',
        project_id=view.get('project_id'),
    )


def body_for(after, project_id):
    # The update writes title, position, project_id, type, sort and hidden
    # from the body; `type` must go back as it is, or the built-in All view
    # becomes an ordinary one. filter is not written by the update.
    return dict(id=after['id'], project_id=project_id, title=after['name'], position=after['position'],
                type=after['type'], hidden=after['hidden'],
                sort_column=after['sort_column'] or None, sort_reverse=after['sort_reverse'])


def ensure(module, client):
    params = module.params
    client.warn_if_untested()

    project_id = resolve_project(client, params['project'], missing_ok=params['state'] == 'absent')
    if project_id is None:
        # The project is gone, and everything in it went with it.
        return dict(changed=False, view={}, diff=dict(before={}, after={}))
    base = '/project/%d' % project_id
    views = client.list(base + '/views')
    current = find_by_name(views, params['name'], 'view', field='title')

    if params['state'] == 'absent':
        if not current:
            return dict(changed=False, view={}, diff=dict(before={}, after={}))
        if current.get('type') == BUILT_IN:
            raise ValueError('View %r is the built-in view that lists every template; this module does not '
                             'delete it. Set hidden: true to hide it.' % params['name'])
        before = normalize(current)
        if not module.check_mode:
            client.delete('%s/views/%d' % (base, current['id']))
        return dict(changed=True, view={}, diff=dict(before=before, after={}))

    desired = dict((k, params[k]) for k in ('position', 'hidden', 'sort_column', 'sort_reverse'))

    if not current:
        position = params['position']
        if position is None:
            position = max([int(v.get('position') or 0) for v in views] + [-1]) + 1
        after = dict(name=params['name'], position=position, hidden=bool(params['hidden']),
                     sort_column=params['sort_column'] or '', sort_reverse=bool(params['sort_reverse']),
                     type='', project_id=project_id)
        if not module.check_mode:
            body = dict(project_id=project_id, title=params['name'], position=position,
                        hidden=after['hidden'], sort_column=after['sort_column'] or None,
                        sort_reverse=after['sort_reverse'])
            after = normalize(client.post(base + '/views', body))
        return dict(changed=True, view=after, diff=dict(before={}, after=after))

    before = normalize(current)
    changed = diff_fields(desired, before)
    if not changed:
        return dict(changed=False, view=before, diff=dict(before=before, after=before))
    after = dict(before)
    after.update((k, desired[k]) for k in changed)
    if not module.check_mode:
        client.put('%s/views/%d' % (base, current['id']), body_for(after, project_id))
    return dict(changed=True, view=after, diff=dict(before=before, after=after))


def main():
    argument_spec = semaphore_argument_spec()
    argument_spec.update(
        project=dict(type='str', required=True),
        name=dict(type='str', required=True),
        state=dict(type='str', default='present', choices=['present', 'absent']),
        position=dict(type='int'),
        hidden=dict(type='bool'),
        sort_column=dict(type='str'),
        sort_reverse=dict(type='bool'),
    )
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True, **semaphore_module_kwargs())
    run_module(module, lambda client: ensure(module, client))


if __name__ == '__main__':
    main()
