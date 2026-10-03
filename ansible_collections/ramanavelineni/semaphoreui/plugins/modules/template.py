#!/usr/bin/python
# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

DOCUMENTATION = r'''
module: template
short_description: Manage task templates in a Semaphore UI project
version_added: 0.1.0
description:
  - Creates, updates or deletes a task template in a project, found by its name.
  - Only the options you set are compared and changed; the others keep their current value.
  - Repositories, inventories, variable groups, views, keys and build templates are referred to
    by name.
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
      - Name of the project the template belongs to.
    type: str
    required: true
  name:
    description:
      - Name of the template. Templates are looked up by this name within the project.
    type: str
    required: true
  state:
    description:
      - V(present) creates the template or updates it to match.
      - V(absent) deletes it. It fails, listing them, while schedules, integrations or other
        objects still use it.
    type: str
    choices: [present, absent]
    default: present
  app:
    description:
      - The tool the template runs. It has to be registered on the Semaphore server
        (see the M(ramanavelineni.semaphoreui.info) module's C(apps)).
      - Defaults to V(ansible) for a new template.
    type: str
    choices: [ansible, terraform, tofu, terragrunt, bash, powershell, python, pulumi]
  playbook:
    description:
      - Path of the playbook or script in the repository. Required to create a template, except
        for the Terraform-family apps.
    type: str
  repository:
    description:
      - Name of the repository the template runs from. Required to create a template.
    type: str
  inventory:
    description:
      - Name of the inventory. Required to create an V(ansible) template.
      - For a Terraform-family template created without one, Semaphore creates an inventory named
        C(default) for it.
      - An empty string removes the inventory.
    type: str
  variable_groups:
    description:
      - Names of the variable groups the template uses, in order. Required to create a template.
    type: list
    elements: str
  view:
    description:
      - Title of the view (tab) the template appears in. An empty string removes it from its view.
    type: str
  description:
    description:
      - Free-text description.
    type: str
  git_branch:
    description:
      - Branch to run from instead of the repository's branch. An empty string removes the override.
    type: str
  arguments:
    description:
      - Extra command-line arguments, one list item per argument.
    type: list
    elements: str
  type:
    description:
      - V(task) for an ordinary template, V(build) for one that produces versioned builds,
        V(deploy) for one that deploys a build template's output.
      - Defaults to V(task) for a new template.
    type: str
    choices: [task, build, deploy]
  start_version:
    description:
      - First version number of a V(build) template.
    type: str
  build_template:
    description:
      - Name of the V(build) template whose builds a V(deploy) template deploys. Required for V(deploy).
    type: str
  autorun:
    description:
      - For a V(deploy) template, run it automatically after each successful build.
    type: bool
  allow_override_args_in_task:
    description:
      - Let users change the arguments when they start a task.
    type: bool
  allow_override_branch_in_task:
    description:
      - Let users choose the branch when they start a task.
    type: bool
  allow_parallel_tasks:
    description:
      - Let more than one task of this template run at the same time.
    type: bool
  suppress_success_alerts:
    description:
      - Send alerts only for failed tasks.
    type: bool
  runner_tag:
    description:
      - Run only on runners with this tag. An empty string removes the tag.
    type: str
  task_params:
    description:
      - App-specific settings. Only the keys you set are compared and changed.
      - For V(ansible) the keys are C(allow_debug), C(allow_override_inventory),
        C(allow_override_limit), C(allow_override_tags), C(allow_override_skip_tags), C(limit),
        C(tags), C(skip_tags) (the last three lists), C(skip_galaxy_install) and
        C(allow_override_skip_galaxy_install).
      - For V(terraform), V(tofu) and V(terragrunt) the keys are C(allow_destroy),
        C(allow_auto_approve), C(auto_approve), C(override_backend) and C(backend_filename).
      - Other apps take no keys. An unknown key fails, rather than being silently ignored.
    type: dict
  vaults:
    description:
      - Ansible Vault passwords passed to the playbook, replacing the template's current list as a whole.
    type: list
    elements: dict
    suboptions:
      name:
        description: Vault id, passed as C(--vault-id NAME@...).
        type: str
        default: default
      type:
        description: V(password) takes the password from a key, V(script) from a client script.
        type: str
        choices: [password, script]
        default: password
      key:
        description: Name of a V(login_password) key holding the vault password, for V(password).
        type: str
      script:
        description: Path of the vault client script, for V(script).
        type: str
  survey_vars:
    description:
      - Variables the user is asked for when starting a task, replacing the current list as a whole.
      - A variable that keeps its name keeps the fields this module has no option for, such as the
        C(target) that Semaphore 2.19 stores.
    type: list
    elements: dict
    suboptions:
      name:
        description: Variable name.
        type: str
        required: true
      title:
        description: Label shown to the user.
        type: str
        required: true
      type:
        description:
          - V(string) (the default), V(int), V(enum) (choose from O(survey_vars[].values)), or
            V(text) (multi-line). V(text) needs Semaphore 2.19.
        type: str
        choices: [string, int, enum, text]
        default: string
      required:
        description: Whether a value must be given.
        type: bool
        default: false
      description:
        description: Help text.
        type: str
        default: ''
      default_value:
        description: Value filled in by default.
        type: str
        default: ''
      values:
        description: Choices for V(enum).
        type: list
        elements: dict
        suboptions:
          name:
            description: Label of the choice.
            type: str
            required: true
          value:
            description: Value of the choice.
            type: str
            required: true
notes:
  - Fields this module does not manage (for example 2.19's C(executor_image) and C(jwt_params))
    are sent back unchanged on every update.
'''

EXAMPLES = r'''
- name: Ansible template with a vault password
  ramanavelineni.semaphoreui.template:
    project: homelab
    name: harbor_config
    playbook: playbooks/harbor_config.yaml
    repository: ansible
    inventory: homelab
    variable_groups: [empty]
    view: infra
    vaults:
      - key: ansible-vault
    task_params:
      allow_override_limit: true

- name: OpenTofu template
  ramanavelineni.semaphoreui.template:
    project: homelab
    name: infra-apply
    app: tofu
    repository: terraform
    variable_groups: [tofu]
    task_params:
      auto_approve: true
'''

RETURN = r'''
template:
  description:
    - The template after the change, or as it would be in check mode, with names for everything
      it refers to.
    - Empty after a deletion.
  returned: always
  type: dict
  sample:
    id: 3
    name: harbor_config
    app: ansible
    playbook: playbooks/harbor_config.yaml
    repository: ansible
    inventory: homelab
    variable_groups: [empty]
    view: infra
    type: task
    vaults:
      - name: default
        type: password
        key: ansible-vault
        script: ""
'''

import json

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.semaphore import (
    find_by_name,
    refuse_delete_if_used,
    resolve_project,
    run_module,
    semaphore_argument_spec,
    semaphore_module_kwargs,
    server_minor,
)
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.template import (
    BOOLS,
    SURVEY_TO_API,
    TYPE_TO_API,
    Lookups,
    template_view,
)

ANSIBLE_PARAMS = ('allow_debug', 'allow_override_inventory', 'allow_override_limit', 'allow_override_tags',
                  'allow_override_skip_tags', 'limit', 'tags', 'skip_tags', 'skip_galaxy_install',
                  'allow_override_skip_galaxy_install')
TERRAFORM_PARAMS = ('allow_destroy', 'allow_auto_approve', 'auto_approve', 'override_backend', 'backend_filename')
TASK_PARAMS = dict(ansible=ANSIBLE_PARAMS, terraform=TERRAFORM_PARAMS, tofu=TERRAFORM_PARAMS,
                   terragrunt=TERRAFORM_PARAMS)
TERRAFORM_APPS = ('terraform', 'tofu', 'terragrunt')
ALL_FIELDS = frozenset(('repository', 'inventory', 'view', 'build_template', 'variable_groups', 'vaults',
                        'survey_vars', 'arguments'))
# References an empty string removes.
CLEARABLE = ('inventory', 'view', 'build_template')
CLEAR = '__clear__'


def survey_to_api(var, stored=None):
    """A declared survey variable as the API takes it, on top of the stored one of that name.

    Starting from the stored variable keeps the fields this module doesn't
    manage (2.19's `target`, and whatever a later version adds).
    """
    out = dict(stored or {})
    out.update(name=var['name'], title=var['title'], type=SURVEY_TO_API.get(var['type'], var['type']),
               required=var['required'], description=var['description'], default_value=var['default_value'])
    if var['values']:
        out['values'] = [dict(name=v['name'], value=v['value']) for v in var['values']]
    else:
        out.pop('values', None)
    return out


def validate(params, app, server_version):
    allowed = TASK_PARAMS.get(app, ())
    unknown = sorted(set(params['task_params'] or {}) - set(allowed))
    if unknown:
        raise ValueError('task_params %s are not valid for app %s (valid: %s).'
                         % (', '.join(unknown), app, ', '.join(allowed) or 'none'))
    for vault in params['vaults'] or []:
        if vault['type'] == 'password' and not vault['key']:
            raise ValueError('Vault %r of type password needs key.' % vault['name'])
        if vault['type'] == 'script' and not vault['script']:
            raise ValueError('Vault %r of type script needs script.' % vault['name'])
    names = [v['name'] for v in params['vaults'] or []]
    if len(names) != len(set(names)):
        raise ValueError('Vault names must be unique.')
    for var in params['survey_vars'] or []:
        if var['type'] == 'enum' and not var['values']:
            raise ValueError('Survey variable %r of type enum needs values.' % var['name'])
        if var['type'] == 'text' and (server_minor(server_version) or (2, 19)) < (2, 19):
            raise ValueError('Survey variable %r uses type text, which Semaphore %s does not support '
                             '(it needs 2.19).' % (var['name'], server_version))


def desired_view(params):
    """The options the caller set, in template_view's shape (None = not managed)."""
    out = dict((k, params[k]) for k in ('app', 'playbook', 'description', 'repository', 'inventory', 'view',
                                        'git_branch', 'arguments', 'start_version', 'build_template',
                                        'runner_tag', 'variable_groups') + BOOLS)
    out['type'] = params['type']
    for k in CLEARABLE:
        if out[k] == '':
            out[k] = CLEAR
    if params['vaults'] is not None:
        out['vaults'] = sorted((dict(name=v['name'], type=v['type'],
                                     key=v['key'] if v['type'] == 'password' else None,
                                     script=v['script'] or '' if v['type'] == 'script' else '')
                                for v in params['vaults']), key=lambda v: v['name'])
    if params['survey_vars'] is not None:
        out['survey_vars'] = [dict(name=v['name'], title=v['title'], type=v['type'], required=v['required'],
                                   description=v['description'], default_value=v['default_value'],
                                   values=[dict(name=x['name'], value=x['value']) for x in v['values'] or []])
                              for v in params['survey_vars']]
    return out


def compare(desired, current):
    """Names of the managed fields that differ."""
    changed = []
    for key, value in desired.items():
        if value is None:
            continue
        if value == CLEAR:
            value = None
        if current.get(key) != value:
            changed.append(key)
    return sorted(changed)


def reference_ids(base_tpl, view, lookups, changed):
    """API ids for the references; unchanged ones keep their current id.

    Names are only resolved for what the caller changed: an unchanged
    reference may point at something the lists don't show (a template's own
    workspace inventory), and resolving it by name again would drop it.
    """
    ids = {}
    for option, field, what in (('repository', 'repository_id', 'repository'), ('inventory', 'inventory_id', 'inventory'),
                                ('view', 'view_id', 'view'), ('build_template', 'build_template_id', 'template')):
        if option not in changed:
            ids[field] = base_tpl.get(field)
        else:
            ids[field] = lookups.id(what, view[option]) if view[option] else None
    if 'variable_groups' not in changed:
        ids['environment_ids'] = list(base_tpl.get('environment_ids') or [])
    else:
        ids['environment_ids'] = [lookups.id('variable_group', n) for n in view['variable_groups']]
    return ids


def build_body(base_tpl, view, lookups, params, project_id, changed):
    """The full API object for `view` (template_view shape), on top of base_tpl."""
    ids = reference_ids(base_tpl, view, lookups, changed)
    body = dict(base_tpl)
    body.update(
        project_id=project_id, name=params['name'], app=view['app'], playbook=view['playbook'],
        description=view['description'], repository_id=ids['repository_id'],
        inventory_id=ids['inventory_id'],
        view_id=ids['view_id'],
        git_branch=view['git_branch'] or None,
        type=TYPE_TO_API.get(view['type'], view['type']),
        start_version=(view['start_version'] or None) if view['type'] == 'build' else None,
        build_template_id=ids['build_template_id'] if view['type'] == 'deploy' else None,
        runner_tag=view['runner_tag'] or None,
        task_params=view['task_params'],
    )
    # What the caller didn't change goes back exactly as stored: rebuilding it
    # from the module's own view would drop fields the view doesn't have, and
    # rewrite an arguments string that isn't a JSON list.
    if 'arguments' in changed:
        body['arguments'] = json.dumps(view['arguments']) if view['arguments'] else None
    if 'survey_vars' in changed:
        stored = dict((v.get('name'), v) for v in base_tpl.get('survey_vars') or [])
        body['survey_vars'] = [survey_to_api(v, stored.get(v['name'])) for v in view['survey_vars']]
    else:
        body['survey_vars'] = list(base_tpl.get('survey_vars') or [])
    env_ids = ids['environment_ids']
    body['environment_ids'] = env_ids
    body['environment_id'] = env_ids[0] if env_ids else 0
    # Vaults are rewritten as a whole: one missing here is deleted. Existing
    # rows keep their id (matched by name) so they are updated in place.
    existing = dict((v.get('name') or 'default', v.get('id')) for v in base_tpl.get('vaults') or [])
    if 'vaults' not in changed:
        body['vaults'] = list(base_tpl.get('vaults') or [])
    else:
        body['vaults'] = [dict(id=existing.get(v['name'], 0), name=v['name'], type=v['type'],
                               vault_key_id=lookups.id('key', v['key']) if v['type'] == 'password' else None,
                               script=v['script'] if v['type'] == 'script' else None)
                          for v in view['vaults']]
    for b in BOOLS:
        body[b] = view[b]
    for k in ('tasks', 'last_task', 'permissions'):
        body.pop(k, None)
    return body


def ensure(module, client):
    params = module.params
    client.warn_if_untested()

    project_id = resolve_project(client, params['project'], missing_ok=params['state'] == 'absent')
    if project_id is None:
        # The project is gone, and everything in it went with it.
        return dict(changed=False, template={}, diff=dict(before={}, after={}))
    base = '/project/%d' % project_id
    lookups = Lookups(client, base, params['project'])
    found = find_by_name(lookups.items['template'], params['name'], 'template')

    if params['state'] == 'absent':
        if not found:
            return dict(changed=False, template={}, diff=dict(before={}, after={}))
        refuse_delete_if_used(client, '%s/templates/%d' % (base, found['id']), 'template', params['name'])
        if not module.check_mode:
            client.delete('%s/templates/%d' % (base, found['id']))
        return dict(changed=True, template={}, diff=dict(before=dict(id=found['id'], name=found['name']), after={}))

    # The list leaves out vaults; the single read has everything.
    current_tpl = client.get('%s/templates/%d' % (base, found['id'])) if found else {}
    app = params['app'] or (current_tpl.get('app') if found else None) or 'ansible'
    validate(params, app, client.info().get('version', ''))
    desired = desired_view(params)

    if not found:
        after = dict(template_view(dict(app='ansible', type=''), lookups), vaults=[], survey_vars=[],
                     variable_groups=[], arguments=[], task_params={})
        after.pop('id')
        after.update((k, None if v == CLEAR else v) for k, v in desired.items() if v is not None)
        after['app'] = app
        after['type'] = params['type'] or 'task'
        after['task_params'] = dict(params['task_params'] or {})
        missing = [o for o in ('repository', 'variable_groups') if not params[o]]
        if app not in TERRAFORM_APPS and not params['playbook']:
            missing.append('playbook')
        if app == 'ansible' and not params['inventory']:
            missing.append('inventory')
        if after['type'] == 'deploy' and not params['build_template']:
            missing.append('build_template')
        if missing:
            raise ValueError('Creating template %r needs %s.' % (params['name'], ', '.join(missing)))
        body = build_body({}, after, lookups, params, project_id, ALL_FIELDS)
        if not module.check_mode:
            # A Terraform-family template created without an inventory gets
            # a workspace inventory named "default" from the server.
            after = template_view(client.post(base + '/templates', body), lookups)
        return dict(changed=True, template=after, diff=dict(before={}, after=after))

    before = template_view(current_tpl, lookups)
    changed = compare(desired, before)
    params_changed = [k for k, v in (params['task_params'] or {}).items() if before['task_params'].get(k) != v]
    if not changed and not params_changed:
        return dict(changed=False, template=before, diff=dict(before=before, after=before))

    after = dict(before)
    after.update((k, None if desired[k] == CLEAR else desired[k]) for k in changed)
    after['task_params'] = dict(before['task_params'], **(params['task_params'] or {}))
    if after['type'] == 'deploy' and not after['build_template']:
        raise ValueError('A deploy template needs build_template.')
    body = build_body(current_tpl, after, lookups, params, project_id, set(changed))
    if not module.check_mode:
        # The update rewrites every column, the vault list and the variable
        # group list, so the whole current template goes back with the
        # changes applied.
        client.put('%s/templates/%d' % (base, current_tpl['id']), body)
    return dict(changed=True, template=after, diff=dict(before=before, after=after))


def main():
    argument_spec = semaphore_argument_spec()
    argument_spec.update(
        project=dict(type='str', required=True),
        name=dict(type='str', required=True),
        state=dict(type='str', default='present', choices=['present', 'absent']),
        app=dict(type='str', choices=['ansible', 'terraform', 'tofu', 'terragrunt', 'bash', 'powershell',
                                      'python', 'pulumi']),
        playbook=dict(type='str'),
        repository=dict(type='str'),
        inventory=dict(type='str'),
        variable_groups=dict(type='list', elements='str'),
        view=dict(type='str'),
        description=dict(type='str'),
        git_branch=dict(type='str'),
        arguments=dict(type='list', elements='str'),
        type=dict(type='str', choices=['task', 'build', 'deploy']),
        start_version=dict(type='str'),
        build_template=dict(type='str'),
        autorun=dict(type='bool'),
        allow_override_args_in_task=dict(type='bool'),
        allow_override_branch_in_task=dict(type='bool'),
        allow_parallel_tasks=dict(type='bool'),
        suppress_success_alerts=dict(type='bool'),
        runner_tag=dict(type='str'),
        task_params=dict(type='dict'),
        vaults=dict(type='list', elements='dict', no_log=False, options=dict(
            name=dict(type='str', default='default'),
            type=dict(type='str', default='password', choices=['password', 'script']),
            key=dict(type='str', no_log=False),
            script=dict(type='str'),
        )),
        survey_vars=dict(type='list', elements='dict', options=dict(
            name=dict(type='str', required=True),
            title=dict(type='str', required=True),
            type=dict(type='str', default='string', choices=['string', 'int', 'enum', 'text']),
            required=dict(type='bool', default=False),
            description=dict(type='str', default=''),
            default_value=dict(type='str', default=''),
            values=dict(type='list', elements='dict', options=dict(
                name=dict(type='str', required=True),
                value=dict(type='str', required=True),
            )),
        )),
    )
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True, **semaphore_module_kwargs())
    run_module(module, lambda client: ensure(module, client), placeholder=dict(template={}))


if __name__ == '__main__':
    main()
