# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""The project_export filters against a real Semaphore.

The role itself needs ansible-playbook; what it does with the server is here:
a project is built with the modules, read with the _info modules, turned into
the project file by the filters, and the options in that file are given back
to the modules. Nothing may change, and nothing the server keeps secret may be
in the file.

It also holds the filter's table of defaults against the server: an object
created with only what its module requires must come back from the _info
module with every other option at the value the table calls its default, or
the export would leave out something that was set.
"""

import yaml

from ansible_collections.ramanavelineni.semaphoreui.plugins.filter import project_export as plugin
from ansible_collections.ramanavelineni.semaphoreui.plugins.modules import (
    integration,
    integration_info,
    inventory,
    inventory_info,
    key_store,
    key_store_info,
    project,
    project_info,
    repository,
    repository_info,
    schedule,
    schedule_info,
    team_member,
    team_member_info,
    template,
    template_info,
    variable_group,
    variable_group_info,
    view,
    view_info,
)

PROJECT = 'live-export'
BARE = 'live-export-bare'
PRIVATE_KEY = '-----BEGIN OPENSSH PRIVATE KEY-----\nlive-export-key-body\n-----END OPENSSH PRIVATE KEY-----\n'
PASSWORD = 'live-export-pw-1'
TOKEN = 'live-export-token-1'

# Section: the module that manages it, its _info module and the key of its result.
SECTIONS = dict(
    key_store=(key_store, key_store_info, 'key_store'),
    repository=(repository, repository_info, 'repositories'),
    inventory=(inventory, inventory_info, 'inventories'),
    variable_group=(variable_group, variable_group_info, 'variable_groups'),
    view=(view, view_info, 'views'),
    template=(template, template_info, 'templates'),
    schedule=(schedule, schedule_info, 'schedules'),
    integration=(integration, integration_info, 'integrations'),
    team_member=(team_member, team_member_info, 'members'),
)

# What the vault would hold for the project built below.
VAULT = {
    'vault_live_export_key_live_export_ssh_ssh_login': 'git',
    'vault_live_export_key_live_export_ssh_ssh_passphrase': '',
    'vault_live_export_key_live_export_ssh_ssh_private_key': PRIVATE_KEY,
    'vault_live_export_key_live_export_login_login_password_login': 'ops',
    'vault_live_export_key_live_export_login_login_password_password': PASSWORD,
    'vault_live_export_var_live_export_vars_token': TOKEN,
    'vault_live_export_var_live_export_vars_db_password': 'live-export-db-1',
}


class Loader(yaml.SafeLoader):
    """Reads !unsafe the way Ansible does: the text, as it is."""


Loader.add_constructor('!unsafe', lambda loader, node: loader.construct_scalar(node))


def load(text):
    return yaml.load(text, Loader=Loader)  # nosec B506 - a SafeLoader with one more tag


def read(sem, name):
    """The project as the _info modules return it, under the names the filters know."""
    info = dict(project=[p for p in sem.ok(project_info, name=name)['projects'] if p['name'] == name][0])
    for section, (dummy, info_module, key) in SECTIONS.items():
        info[section] = sem.ok(info_module, project=name)[key]
    return info


def from_vault(value, vault):
    """The exported options as Ansible would hand them to a module: each reference replaced by its variable."""
    # Only the references: data that looks like a template was written as !unsafe and stays as it is.
    if isinstance(value, str) and value.startswith('{{ vault_') and value.endswith(' }}'):
        return vault[value[3:-3]]
    if isinstance(value, dict):
        return dict((key, from_vault(item, vault)) for key, item in value.items())
    if isinstance(value, list):
        return [from_vault(item, vault) for item in value]
    return value


def build(sem):
    sem.ok(project, name=PROJECT, max_parallel_tasks=2, alert=True, alert_chat='-100123')
    sem.ok(key_store, project=PROJECT, name='live-export-ssh', type='ssh', ssh=dict(login='git', private_key=PRIVATE_KEY))
    sem.ok(key_store, project=PROJECT, name='live-export-login', type='login_password',
           login_password=dict(login='ops', password=PASSWORD))
    sem.ok(key_store, project=PROJECT, name='live-export-none', type='none')
    sem.ok(repository, project=PROJECT, name='live-export-repo', git_url='git@github.com:example/live.git',
           git_branch='main', ssh_key='live-export-ssh')
    sem.ok(inventory, project=PROJECT, name='live-export-static', type='static',
           inventory='[all]\nlocalhost ansible_connection=local\n', ssh_key='live-export-none',
           become_key='live-export-login')
    sem.ok(inventory, project=PROJECT, name='live-export-file', type='file', inventory='inventories/hosts',
           repository='live-export-repo', ssh_key='live-export-ssh')
    sem.ok(variable_group, project=PROJECT, name='live-export-vars',
           json=dict(region='eu', replicas=2, greeting='{{ not_a_variable }}', nested=dict(a=[1, dict(b=None)])),
           env=dict(TZ='UTC'),
           secrets=[dict(name='TOKEN', type='env', value=TOKEN), dict(name='db_password', type='var', value='live-export-db-1')])
    sem.ok(variable_group, project=PROJECT, name='live-export-empty')
    sem.ok(view, project=PROJECT, name='live-export-view', position=1)
    sem.ok(template, project=PROJECT, name='live-export-site', playbook='site.yml', repository='live-export-repo',
           inventory='live-export-static', variable_groups=['live-export-vars'], view='live-export-view',
           description='Made by the live tests', arguments=['-v', '--diff'], allow_override_args_in_task=True,
           survey_vars=[dict(name='region', title='Region', type='enum', values=[dict(name='Europe', value='eu')]),
                        dict(name='count', title='How many', type='int', required=True, default_value='1')],
           vaults=[dict(key='live-export-login')], task_params=dict(allow_debug=True, limit=['web']))
    sem.ok(template, project=PROJECT, name='live-export-z-build', type='build', start_version='1.0.0',
           playbook='build.yml', repository='live-export-repo', inventory='live-export-static',
           variable_groups=['live-export-empty'])
    # Named to sort before the build template it needs.
    sem.ok(template, project=PROJECT, name='live-export-a-deploy', type='deploy', build_template='live-export-z-build',
           autorun=True, playbook='deploy.yml', repository='live-export-repo', inventory='live-export-static',
           variable_groups=['live-export-empty'])
    sem.ok(schedule, project=PROJECT, name='live-export-nightly', template='live-export-site', cron='0 3 * * *',
           active=False)
    sem.ok(schedule, project=PROJECT, name='live-export-poll', template='live-export-site', cron='*/5 * * * *',
           repository='live-export-repo')
    sem.ok(schedule, project=PROJECT, name='live-export-once', template='live-export-site',
           run_at='2099-01-01T05:00:00+02:00', delete_after_run=True)
    sem.ok(integration, project=PROJECT, name='live-export-hook', template='live-export-site', auth_method='token',
           auth_key='live-export-login', auth_header='X-Token', searchable=True,
           matchers=[dict(name='main', key='ref', value='refs/heads/main', method='contains')],
           extract_values=[dict(name='sha', key='after', variable='COMMIT_SHA')])
    sem.ok(integration, project=PROJECT, name='live-export-plain', template='live-export-site')


def apply(sem, config, vault, target, on_create=True):
    """Give every exported entry to its module. Returns what changed."""
    changed = []
    own = dict((key, value) for key, value in config.items() if key not in plugin.SECTIONS)
    if sem.ok(project, **dict(own, name=target))['changed']:
        changed.append('project')
    for section in plugin.SECTIONS:
        manage = SECTIONS[section][0]
        for name, options in config.get(section, {}).items():
            args = dict(from_vault(options, vault), project=target)
            args['user' if section == 'team_member' else 'name'] = name
            if on_create and section in plugin.SECRETS:
                # A secret can't be compared with the stored one, so the modules send it on every run unless told not to.
                args['update_secret'] = 'on_create'
            if sem.ok(manage, **args)['changed']:
                changed.append('%s %s' % (section, name))
    return changed


def test_the_exported_project_names_everything_and_no_secret(sem):
    build(sem)
    info = read(sem, PROJECT)
    text = plugin.project_export_yaml(info)
    config = load(text)
    assert config == plugin.project_export_config(info)
    assert config['name'] == PROJECT and config['max_parallel_tasks'] == 2 and config['alert'] is True

    assert set(['live-export-ssh', 'live-export-login', 'live-export-none']) <= set(config['key_store'])
    assert sorted(config['repository']) == ['live-export-repo']
    assert sorted(config['inventory']) == ['live-export-file', 'live-export-static']
    assert sorted(config['variable_group']) == ['live-export-empty', 'live-export-vars']
    assert 'live-export-view' in config['view']
    # The build template first: project_apply creates the templates in this order.
    assert list(config['template']) == ['live-export-z-build', 'live-export-a-deploy', 'live-export-site']
    assert sorted(config['schedule']) == ['live-export-nightly', 'live-export-once', 'live-export-poll']
    assert sorted(config['integration']) == ['live-export-hook', 'live-export-plain']
    # Whoever created the project is its owner.
    assert list(config['team_member'].values()) == [dict(role='owner')]

    # What was set comes back, what was left alone is not in the file.
    assert config['inventory']['live-export-static']['inventory'] == '[all]\nlocalhost ansible_connection=local\n'
    assert config['variable_group']['live-export-vars']['json']['greeting'] == '{{ not_a_variable }}'
    assert 'greeting: !unsafe "{{ not_a_variable }}"' in text
    assert config['variable_group']['live-export-empty'] == {}
    assert config['template']['live-export-site']['vaults'] == [dict(key='live-export-login')]
    assert config['schedule']['live-export-nightly'] == dict(template='live-export-site', cron='0 3 * * *', active=False)
    assert config['schedule']['live-export-poll'] == dict(template='live-export-site', cron='*/5 * * * *',
                                                          repository='live-export-repo')
    assert config['schedule']['live-export-once'] == dict(template='live-export-site', run_at='2099-01-01T03:00:00Z',
                                                          delete_after_run=True)
    assert config['integration']['live-export-plain'] == dict(template='live-export-site')
    for section in plugin.SECTIONS:
        for options in config[section].values():
            assert not set(options) & set(('id', 'project_id', 'kind', 'webhook_urls', 'repositories', 'state'))

    # No secret, and one variable for each.
    for secret in ('live-export-key-body', PASSWORD, TOKEN, 'live-export-db-1', 'OPENSSH'):
        assert secret not in text
    listed = [entry['name'] for entry in plugin.project_export_vault_variables(info)]
    assert sorted(listed) == sorted(VAULT)
    assert load(plugin.project_export_vault(info)) == dict((name, '') for name in VAULT)


def test_applying_the_export_to_the_same_project_changes_nothing(sem):
    info = read(sem, PROJECT)
    config = load(plugin.project_export_yaml(info))
    assert apply(sem, config, VAULT, PROJECT) == []
    # And the project is still what it was: exporting again gives the same text.
    assert plugin.project_export_yaml(read(sem, PROJECT)) == plugin.project_export_yaml(info)


def test_the_parts_of_a_directory_are_the_same_project(sem):
    info = read(sem, PROJECT)
    together = {}
    for part in ('project',) + plugin.SECTIONS:
        text = plugin.project_export_yaml(info, part)
        assert text, 'the project has objects of every kind, also %s' % part
        together.update(load(text))
    assert together == load(plugin.project_export_yaml(info))


def test_the_export_builds_the_same_project_again(sem):
    """Applied under another name, with the secrets from the vault, the export gives a project that exports the same."""
    info = read(sem, PROJECT)
    copy_name = 'live-export-copy'
    vault = dict((name.replace('vault_live_export_', 'vault_live_export_copy_'), value) for name, value in VAULT.items())
    copied = load(plugin.project_export_yaml(dict(info, project=dict(info['project'], name=copy_name))))

    first = apply(sem, copied, vault, copy_name, on_create=False)
    assert 'project' in first and 'template live-export-a-deploy' in first
    # A second run changes only what holds a secret, which is sent every time. Not the key the repository uses:
    # the module leaves that one alone unless force_repository_key_update is set.
    again = apply(sem, copied, vault, copy_name, on_create=False)
    assert sorted(again) == ['key_store live-export-login', 'variable_group live-export-vars']

    exported_copy = load(plugin.project_export_yaml(read(sem, copy_name)))
    assert exported_copy == copied
    assert dict(exported_copy, name=PROJECT) == load(
        plugin.project_export_yaml(info).replace('vault_live_export_', 'vault_live_export_copy_'))
    sem.ok(project, name=copy_name, state='absent', confirm_delete=True)


def test_an_object_made_with_only_what_is_required_exports_as_only_that(sem):
    """The table of defaults against the server: what is left out of the file is what the server gives a new object."""
    sem.ok(project, name=BARE)
    sem.ok(key_store, project=BARE, name='live-export-key', type='none')
    # A repository needs a key; the one of type none is as little as there is.
    sem.ok(repository, project=BARE, name='live-export-repo', git_url='https://example.com/live.git', git_branch='main',
           ssh_key='live-export-key')
    sem.ok(inventory, project=BARE, name='live-export-inventory', type='static', inventory='localhost')
    sem.ok(variable_group, project=BARE, name='live-export-vars')
    sem.ok(view, project=BARE, name='live-export-view')
    sem.ok(template, project=BARE, name='live-export-site', playbook='site.yml', repository='live-export-repo',
           inventory='live-export-inventory', variable_groups=['live-export-vars'])
    sem.ok(schedule, project=BARE, name='live-export-nightly', template='live-export-site', cron='0 3 * * *')
    sem.ok(integration, project=BARE, name='live-export-hook', template='live-export-site')

    config = load(plugin.project_export_yaml(read(sem, BARE)))
    assert sorted(key for key in config if key not in plugin.SECTIONS) == ['name']
    assert config['key_store']['live-export-key'] == dict(type='none')
    assert config['repository']['live-export-repo'] == dict(git_url='https://example.com/live.git', git_branch='main',
                                                            ssh_key='live-export-key')
    stored = config['inventory']['live-export-inventory']
    assert dict((key, stored[key]) for key in ('type', 'inventory')) == dict(type='static', inventory='localhost')
    assert not set(stored) & set(('repository', 'become_key'))
    assert config['variable_group']['live-export-vars'] == {}
    assert sorted(config['view']['live-export-view']) == ['position']
    assert config['template']['live-export-site'] == dict(app='ansible', playbook='site.yml', repository='live-export-repo',
                                                          inventory='live-export-inventory',
                                                          variable_groups=['live-export-vars'])
    assert config['schedule']['live-export-nightly'] == dict(template='live-export-site', cron='0 3 * * *')
    assert config['integration']['live-export-hook'] == dict(template='live-export-site')
    assert load(plugin.project_export_vault(read(sem, BARE))) == {}

    sem.ok(project, name=BARE, state='absent', confirm_delete=True)


def test_removing_the_project(sem):
    assert sem.ok(project, name=PROJECT, state='absent', confirm_delete=True)['changed'] is True
