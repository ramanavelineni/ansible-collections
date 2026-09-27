# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""Name lookups and the returned shape shared by the template modules."""

import json

from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.semaphore import find_by_name

BOOLS = ('autorun', 'allow_override_args_in_task', 'allow_override_branch_in_task',
         'allow_parallel_tasks', 'suppress_success_alerts')
# The API spells an ordinary template's type and a string survey variable's
# type as "".
TYPE_TO_API = dict(task='', build='build', deploy='deploy')
SURVEY_TO_API = dict(string='', int='int', enum='enum', text='text')


class Lookups(object):
    """Name <-> id maps for everything a template refers to."""

    def __init__(self, client, base, project):
        self.client = client
        self.base = base
        self.project = project
        self.items = dict(
            repository=client.list(base + '/repositories'),
            inventory=client.list(base + '/inventory'),
            variable_group=client.list(base + '/environment'),
            view=client.list(base + '/views'),
            key=client.list(base + '/keys'),
            template=client.list(base + '/templates'),
        )

    def name(self, what, obj_id):
        if not obj_id:
            return None
        field = 'title' if what == 'view' else 'name'
        for item in self.items[what]:
            if item.get('id') == obj_id:
                return item.get(field)
        if what == 'inventory':
            # The inventory list leaves out inventories a template owns (the
            # workspace inventory of a Terraform-family template); read it.
            item = self.client.get('%s/inventory/%d' % (self.base, obj_id)) or {}
            self.items[what].append(item)
            return item.get(field)
        return None

    def id(self, what, name):
        field = 'title' if what == 'view' else 'name'
        found = find_by_name(self.items[what], name, what.replace('_', ' '), field=field)
        if found is None:
            raise ValueError('%s %r does not exist in project %r.'
                             % (what.replace('_', ' ').capitalize(), name, self.project))
        return found['id']


def parse_arguments(text):
    if not text:
        return []
    try:
        value = json.loads(text)
    except ValueError:
        return [text]
    return value if isinstance(value, list) else [value]


def survey_view(var):
    return dict(
        name=var.get('name'), title=var.get('title'),
        type=dict((v, k) for k, v in SURVEY_TO_API.items()).get(var.get('type') or '', var.get('type')),
        required=bool(var.get('required', False)), description=var.get('description') or '',
        default_value=var.get('default_value') or '',
        values=[dict(name=v.get('name'), value=v.get('value')) for v in var.get('values') or []],
    )


def vault_view(vault, lookups):
    return dict(name=vault.get('name') or 'default', type=vault.get('type') or 'password',
                key=lookups.name('key', vault.get('vault_key_id')) if (vault.get('type') or 'password') == 'password' else None,
                script=vault.get('script') or '')


def template_view(tpl, lookups):
    return dict(
        id=tpl.get('id'), name=tpl.get('name'), app=tpl.get('app') or 'ansible',
        playbook=tpl.get('playbook') or '', description=tpl.get('description') or '',
        repository=lookups.name('repository', tpl.get('repository_id')),
        inventory=lookups.name('inventory', tpl.get('inventory_id')),
        variable_groups=[lookups.name('variable_group', i) for i in tpl.get('environment_ids') or []],
        view=lookups.name('view', tpl.get('view_id')),
        git_branch=tpl.get('git_branch') or '',
        arguments=parse_arguments(tpl.get('arguments')),
        type=dict((v, k) for k, v in TYPE_TO_API.items()).get(tpl.get('type') or '', tpl.get('type')),
        start_version=tpl.get('start_version') or '',
        build_template=lookups.name('template', tpl.get('build_template_id')),
        runner_tag=tpl.get('runner_tag') or '',
        task_params=dict(tpl.get('task_params') or {}),
        vaults=sorted((vault_view(v, lookups) for v in tpl.get('vaults') or []), key=lambda v: v['name']),
        survey_vars=[survey_view(v) for v in tpl.get('survey_vars') or []],
        **dict((b, bool(tpl.get(b, False))) for b in BOOLS)
    )
