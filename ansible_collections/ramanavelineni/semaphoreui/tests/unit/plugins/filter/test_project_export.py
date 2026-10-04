# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""The filters of the project_export role.

Three things are held here:

  - the tables in the filter plugin against the modules' own argument specs,
    so an option a module gains, a default it changes or a secret it adds
    fails a test instead of going missing from an export;
  - the YAML the plugin writes, by reading it back with a YAML library;
  - the round trip on the recorded servers: what the _info modules return is
    exported, the exported options are given to the module that manages the
    object, and nothing may change.
"""

import copy
import random

import pytest
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
from ansible_collections.ramanavelineni.semaphoreui.tests.unit.plugins.modules import test_every_operation as recorded
from ansible_collections.ramanavelineni.semaphoreui.tests.unit.plugins.modules.test_examples import module_spec

# What every module has and no project file sets: where the server is, and
# which project and object an entry is about.
CONNECTION = ('url', 'api_token', 'username', 'password', 'validate_certs', 'ca_path', 'client_cert', 'client_key',
              'use_proxy', 'timeout', 'retries', 'retry_delay')
ADDRESS = ('project', 'project_id', 'name', 'user')
# Options that say what a run should do, not what the object is.
RUN_ONLY = dict(
    project=('state', 'confirm_delete'),
    key_store=('state', 'update_secret', 'force_repository_key_update'),
    repository=('state',),
    inventory=('state',),
    variable_group=('state', 'purge_secrets', 'update_secret'),
    view=('state',),
    template=('state',),
    schedule=('state',),
    integration=('state',),
    team_member=('state',),
)

# Section: the module that manages it, its _info module, the key of the _info
# result, and the routes of the recorded server that hold one such object.
SECTIONS = dict(
    key_store=(key_store, key_store_info, 'key_store', recorded.key_list),
    repository=(repository, repository_info, 'repositories', recorded.repository_list),
    inventory=(inventory, inventory_info, 'inventories', recorded.inventory_list),
    variable_group=(variable_group, variable_group_info, 'variable_groups', recorded.variable_group_list),
    view=(view, view_info, 'views', recorded.view_list),
    template=(template, template_info, 'templates', recorded.template_list),
    schedule=(schedule, schedule_info, 'schedules', recorded.schedule_list),
    integration=(integration, integration_info, 'integrations', recorded.integration_list),
    team_member=(team_member, team_member_info, 'members', recorded.team_member_list),
)


# Objects of a recorded listing that the recorded server cannot answer a
# module's own lookups for: the search for the user admin was never recorded.
NOT_RECORDED = dict(team_member=('admin',))


class Loader(yaml.SafeLoader):
    """Reads !unsafe the way Ansible does: the text, as it is."""


Loader.add_constructor('!unsafe', lambda loader, node: loader.construct_scalar(node))


def load(text):
    return yaml.load(text, Loader=Loader)  # nosec B506 - a SafeLoader with one more tag


def spec_of(section):
    return module_spec(section)['argument_spec']


def info_of(**sections):
    return dict(dict(project=dict(id=1, name='homelab', alert=False, alert_chat='', max_parallel_tasks=0, type='')),
                **sections)


# ---- the tables against the modules -----------------------------------------------

@pytest.mark.parametrize('section', sorted(plugin.OPTIONS) + ['project'])
def test_every_option_of_the_module_is_exported_or_known_as_not_exported(section):
    options = set(spec_of(section)) - set(CONNECTION) - set(ADDRESS)
    if section == 'project':
        exported = set(name for name, dummy in plugin.PROJECT_OPTIONS)
    else:
        exported = set(name for name, dummy in plugin.OPTIONS[section])
    secret_options = set(path.split('.')[0] for path in plugin.SECRETS.get(section, ()))
    if section == 'key_store':
        secret_options = set(option for option, dummy in plugin.KEY_SECRETS.values())
    # An option that holds a secret among other things (a variable group's
    # secrets, with their names) is exported without the secret.
    assert exported | secret_options | set(RUN_ONLY[section]) == options
    assert not exported & set(RUN_ONLY[section])


def test_the_sections_are_the_ones_with_tables():
    assert sorted(plugin.SECTIONS) == sorted(plugin.OPTIONS)


@pytest.mark.parametrize('section, option', sorted(plugin.ENTRIES))
def test_list_entries_have_the_keys_and_defaults_of_the_argument_spec(section, option):
    suboptions = spec_of(section)[option]['options']
    secret = set(path.split('.')[1] for path in plugin.SECRETS.get(section, ()) if path.startswith(option + '.'))
    table = dict(plugin.ENTRIES[(section, option)])
    assert set(table) | secret == set(suboptions)
    for key, default in table.items():
        declared = suboptions[key].get('default')
        if default is plugin.KEEP:
            assert declared is None, '%s.%s.%s has a default, so it need not always be written' % (section, option, key)
        elif declared is not None:
            assert default == declared
        else:
            # No default in the module: the table holds what the _info module shows for "not set".
            assert default in (None, '', [])


def no_log_paths(spec, prefix=''):
    found = []
    for name, option in spec.items():
        if option.get('no_log') is True:
            found.append(prefix + name)
        if option.get('options'):
            found.extend(no_log_paths(option['options'], prefix + name + '.'))
    return found


@pytest.mark.parametrize('section', sorted(plugin.OPTIONS) + ['project'])
def test_the_secrets_are_the_options_the_module_marks_no_log(section):
    spec = dict((name, option) for name, option in spec_of(section).items() if name not in CONNECTION)
    assert sorted(no_log_paths(spec)) == sorted(plugin.SECRETS.get(section, ()))


def test_a_key_asks_for_every_field_of_its_secret():
    spec = spec_of('key_store')
    assert sorted(plugin.KEY_SECRETS) == sorted(kind for kind in spec['type']['choices'] if kind != 'none')
    for option, fields in plugin.KEY_SECRETS.values():
        assert sorted(fields) == sorted(spec[option]['options'])


def test_no_info_module_returns_a_secret(server, run_module):
    """What is asked from a vault is really not to be had from the server."""
    recorded.key_list(server)
    for key in run_module(key_store_info.main, dict(project='homelab'))['key_store']:
        assert not set(key) & set(('ssh', 'login_password', 'login', 'password', 'private_key', 'passphrase'))
    recorded.variable_group_list(server)
    for group in run_module(variable_group_info.main, dict(project='homelab'))['variable_groups']:
        for secret in group['secrets']:
            assert sorted(secret) == ['name', 'type']


# ---- what is written ----------------------------------------------------------------

KEYS = [dict(id=4, name='deploy', type='ssh', project_id=1, repositories=['ansible']),
        dict(id=5, name='vault pw', type='login_password', project_id=1, repositories=[]),
        dict(id=6, name='None', type='none', project_id=1, repositories=[])]
GROUPS = [dict(id=1, name='harbor', project_id=1, json=dict(harbor_url='https://harbor.example.com'), env={},
               secrets=[dict(name='HARBOR_TOKEN', type='env'), dict(name='db_pw', type='var')])]


def test_ids_and_server_fields_are_left_out_and_defaults_too():
    schedules = [dict(id=3, name='nightly', template='site', kind='cron', cron='0 3 * * *', repository=None,
                      run_at=None, delete_after_run=False, active=True, project_id=1)]
    views = [dict(id=1, name='All', position=0, hidden=False, sort_column='', sort_reverse=False, type='all',
                  project_id=1)]
    config = plugin.project_export_config(info_of(schedule=schedules, view=views))
    assert config == dict(name='homelab', view=dict(All=dict(position=0)),
                          schedule=dict(nightly=dict(template='site', cron='0 3 * * *')))


def test_project_options_that_are_set_are_written():
    info = dict(project=dict(id=1, name='homelab', alert=True, alert_chat='-100', max_parallel_tasks=2, type=''))
    assert plugin.project_export_config(info) == dict(name='homelab', alert=True, alert_chat='-100',
                                                      max_parallel_tasks=2)


def test_a_key_refers_to_vault_variables_for_all_of_its_secret():
    config = plugin.project_export_config(info_of(key_store=KEYS))
    assert config['key_store'] == {
        'None': dict(type='none'),
        'deploy': dict(type='ssh', ssh=dict(login='{{ vault_homelab_key_deploy_ssh_login }}',
                                            passphrase='{{ vault_homelab_key_deploy_ssh_passphrase }}',
                                            private_key='{{ vault_homelab_key_deploy_ssh_private_key }}')),
        'vault pw': dict(type='login_password', login_password=dict(
            login='{{ vault_homelab_key_vault_pw_login_password_login }}',
            password='{{ vault_homelab_key_vault_pw_login_password_password }}')),
    }


def test_a_variable_group_refers_to_one_vault_variable_per_secret():
    config = plugin.project_export_config(info_of(variable_group=GROUPS), vault_prefix='secret')
    assert config['variable_group']['harbor'] == dict(
        json=dict(harbor_url='https://harbor.example.com'),
        secrets=[dict(name='HARBOR_TOKEN', value='{{ secret_homelab_var_harbor_harbor_token }}'),
                 dict(name='db_pw', type='var', value='{{ secret_homelab_var_harbor_db_pw }}')])


def test_the_vault_variables_are_listed_in_the_order_of_the_file():
    listed = plugin.project_export_vault_variables(info_of(key_store=KEYS, variable_group=GROUPS))
    assert [entry['name'] for entry in listed] == [
        'vault_homelab_key_deploy_ssh_login', 'vault_homelab_key_deploy_ssh_passphrase',
        'vault_homelab_key_deploy_ssh_private_key', 'vault_homelab_key_vault_pw_login_password_login',
        'vault_homelab_key_vault_pw_login_password_password', 'vault_homelab_var_harbor_harbor_token',
        'vault_homelab_var_harbor_db_pw']
    assert listed[2]['description'] == 'key deploy: ssh.private_key'
    assert listed[5]['description'] == 'variable group harbor: the value of secret HARBOR_TOKEN'
    text = plugin.project_export_yaml(info_of(key_store=KEYS, variable_group=GROUPS))
    positions = [text.index('{{ %s }}' % entry['name']) for entry in listed]
    assert positions == sorted(positions)


def test_names_that_differ_in_punctuation_or_case_get_variables_of_their_own():
    keys = [dict(id=1, name='a-b', type='login_password'), dict(id=2, name='a_b', type='login_password'),
            dict(id=3, name='A b', type='login_password')]
    names = [entry['name'] for entry in plugin.project_export_vault_variables(info_of(key_store=keys))]
    assert len(names) == len(set(names)) == 6
    assert 'vault_homelab_key_a_b_login_password_password' in names
    assert 'vault_homelab_key_a_b_login_password_password_2' in names
    assert 'vault_homelab_key_a_b_login_password_password_3' in names


def test_the_vault_file_is_a_mapping_of_empty_values():
    text = plugin.project_export_vault(info_of(key_store=KEYS, variable_group=GROUPS))
    listed = plugin.project_export_vault_variables(info_of(key_store=KEYS, variable_group=GROUPS))
    assert load(text) == dict((entry['name'], '') for entry in listed)
    assert '# key deploy: ssh.private_key\nvault_homelab_key_deploy_ssh_private_key: ""\n' in text
    assert load(plugin.project_export_vault(info_of())) == {}
    assert 'no secrets' in plugin.project_export_vault(info_of())


@pytest.mark.parametrize('prefix', ['', '1vault', 'my vault', 'vault-x', 'Vault', '{{ x }}', 'vault\n'])
def test_a_prefix_that_is_not_a_variable_name_is_refused(prefix):
    with pytest.raises(ValueError, match='not a variable name'):
        plugin.project_export_config(info_of(), vault_prefix=prefix)


def test_a_poller_is_written_without_active_and_a_run_at_schedule_without_cron():
    # The module refuses active for a poller, whatever the server has stored for it.
    schedules = [dict(id=1, name='poll', template='site', kind='poller', cron='*/5 * * * *', repository='ansible',
                      run_at=None, delete_after_run=False, active=False),
                 dict(id=2, name='once', template='site', kind='run_at', cron='', repository=None,
                      run_at='2099-01-01T03:00:00Z', delete_after_run=True, active=False)]
    assert plugin.project_export_config(info_of(schedule=schedules))['schedule'] == dict(
        poll=dict(template='site', cron='*/5 * * * *', repository='ansible'),
        once=dict(template='site', run_at='2099-01-01T03:00:00Z', delete_after_run=True, active=False))


def named_template(name, **more):
    return dict(dict(id=1, name=name, app='ansible', playbook='site.yml', repository='ansible', inventory='homelab',
                     variable_groups=['empty'], view=None, type='task', build_template=None), **more)


def test_a_build_template_comes_before_the_deploy_templates_that_name_it():
    templates = [named_template('a-deploy', type='deploy', build_template='z-build'),
                 named_template('m-task'),
                 named_template('z-build', type='build', start_version='1.0.0')]
    for order in (templates, templates[::-1]):
        config = plugin.project_export_config(info_of(template=order))
        assert list(config['template']) == ['z-build', 'a-deploy', 'm-task']
    assert config['template']['a-deploy']['build_template'] == 'z-build'
    assert list(load(plugin.project_export_yaml(info_of(template=templates)))['template']) == [
        'z-build', 'a-deploy', 'm-task']


def test_templates_that_name_each_other_do_not_loop():
    templates = [named_template('a', type='deploy', build_template='b'),
                 named_template('b', type='deploy', build_template='a')]
    assert sorted(plugin.project_export_config(info_of(template=templates))['template']) == ['a', 'b']


def test_entries_of_a_list_lose_their_defaults_and_keep_their_order():
    templates = [named_template('site', vaults=[dict(name='default', type='password', key='deploy', script='')],
                                survey_vars=[
                                    dict(name='host', title='Host', type='string', required=False, description='',
                                         default_value='', values=[], target='env'),
                                    dict(name='env', title='Env', type='enum', required=True, description='which',
                                         default_value='dev',
                                         values=[dict(name='Dev', value='dev'), dict(name='Prod', value='prod')])])]
    site = plugin.project_export_config(info_of(template=templates))['template']['site']
    assert site['vaults'] == [dict(key='deploy')]
    assert site['survey_vars'] == [
        dict(name='host', title='Host'),
        dict(name='env', title='Env', type='enum', required=True, description='which', default_value='dev',
             values=[dict(name='Dev', value='dev'), dict(name='Prod', value='prod')])]


def test_the_same_project_gives_the_same_text_whatever_the_order_of_the_listing():
    info = info_of(key_store=KEYS, variable_group=GROUPS,
                   repository=[dict(id=1, name=name, git_url='git@example.com:%s.git' % name, git_branch='main',
                                    ssh_key='deploy') for name in ('b', 'a', 'c')])
    shuffled = copy.deepcopy(info)
    for section in ('key_store', 'repository'):
        shuffled[section].reverse()
    assert plugin.project_export_yaml(shuffled) == plugin.project_export_yaml(info)
    assert plugin.project_export_vault(shuffled) == plugin.project_export_vault(info)
    assert list(load(plugin.project_export_yaml(info))['repository']) == ['a', 'b', 'c']


def test_the_text_is_the_mapping():
    info = info_of(key_store=KEYS, variable_group=GROUPS, template=[named_template('site')])
    text = plugin.project_export_yaml(info)
    assert text.startswith('---\n# Semaphore project homelab\n')
    assert load(text) == plugin.project_export_config(info)
    # The sections come in the order project_apply applies them.
    assert list(load(text)) == ['name', 'key_store', 'variable_group', 'template']


def test_the_parts_of_a_directory_add_up_to_the_project():
    info = info_of(key_store=KEYS, variable_group=GROUPS, template=[named_template('site')])
    together = {}
    for part in ('project',) + plugin.SECTIONS:
        text = plugin.project_export_yaml(info, part)
        if part in ('project', 'key_store', 'variable_group', 'template'):
            assert set(load(text)) == set([part] if part != 'project' else ['name'])
            together.update(load(text))
        else:
            assert text == ''
    assert together == plugin.project_export_config(info)
    with pytest.raises(ValueError, match='no part'):
        plugin.project_export_yaml(info, 'runner')


def test_two_objects_of_one_name_are_refused():
    keys = [dict(id=1, name='deploy', type='none'), dict(id=2, name='deploy', type='none')]
    with pytest.raises(ValueError, match='two entries named'):
        plugin.project_export_config(info_of(key_store=keys))


@pytest.mark.parametrize('info', [None, [], {}, dict(project=None), dict(project=dict(id=1)),
                                  dict(project=dict(name='homelab'), key_store=dict(deploy=1))])
def test_something_that_is_not_what_the_info_modules_return_is_refused(info):
    with pytest.raises(ValueError, match='project_export'):
        plugin.project_export_config(info)


def test_what_looks_like_a_template_is_written_as_data():
    groups = [dict(id=1, name='tpl', json=dict(greeting='{{ name }}', loop='{% for x in y %}', plain='text'), env={},
                   secrets=[dict(name='TOKEN', type='env')])]
    text = plugin.project_export_yaml(info_of(variable_group=groups))
    assert 'greeting: !unsafe "{{ name }}"' in text
    assert 'loop: !unsafe "{% for x in y %}"' in text
    assert 'plain: text' in text
    # The reference to the vault is the one thing that is meant to be rendered.
    assert 'value: "{{ vault_homelab_var_tpl_token }}"' in text
    assert load(text)['variable_group']['tpl']['json']['greeting'] == '{{ name }}'


# ---- the YAML -----------------------------------------------------------------------

AWKWARD = [
    '', ' ', 'a', 'yes', 'No', 'on', 'OFF', 'true', 'False', 'null', 'None', '~', 'y', 'n', '0', '007', '1.5', '1e3',
    '0x1f', '-1', '+1', '.inf', '.nan', '2026-10-04', '12:30', 'a: b', 'a #b', '#a', '- a', '-', '?', ':', '{', '[a]',
    '*a', '&a', '!a', '|', '>', '%a', '@a', '`a', "'a'", '"a"', 'a"b', "a'b", 'a\\b', 'tab\there', 'trailing ',
    ' leading', 'two  spaces', 'git@github.com:example/live.git', 'https://example.com/a?b=c#d', '0 3 * * *',
    'refs/heads/main', 'X-Token', 'line one\nline two', 'line one\nline two\n', 'ends in newline\n', '\nstarts so',
    'a\n\nb', 'a\n  indented\nb', 'trailing space \nnext', 'two\n\n', u'caf\xe9', u'\u65e5\u672c\u8a9e',
    u'nb\xa0sp', u'line\u2028sep', u'del\x7f', u'bell\x07', u'\x85', u'\ufeffbom', u'emoji \U0001f600',
    '[all]\nlocalhost ansible_connection=local\n\n[web]\nweb1 ansible_host=10.0.0.1\n',
    '---\nall:\n  hosts:\n    localhost:\n      key: "value # not a comment"\n',
    '{{ x }}', 'a {% b %}', '{# c #}', '{{ x }}\n{{ y }}\n',
]


@pytest.mark.parametrize('text', AWKWARD, ids=[repr(text)[:30] for text in AWKWARD])
def test_a_text_comes_back_as_it_was(text):
    data = {'key': text, text or 'empty': 1, 'in a list': [text, {'nested': text}]}
    assert load(plugin.to_yaml(data)) == data


def test_values_that_are_not_text_come_back_as_they_were():
    data = dict(none=None, yes=True, no=False, zero=0, big=2 ** 40, negative=-3, half=0.5, large=1e300,
                empty_dict={}, empty_list=[], nested=dict(a=dict(b=dict(c=[1, [2, [3]], dict(d=[])]))),
                list_of_maps=[dict(name='a', value=1), dict(name='b', nested=dict(x=[dict(y=1)]))],
                list_of_lists=[[1, 2], [], [[3]]])
    assert load(plugin.to_yaml(data)) == data
    assert load(plugin.to_yaml(dict(infinite=float('inf'))))['infinite'] == float('inf')


def random_text(rng):
    alphabet = u'ab Z09_-./:#@!\'"\\{}[]%*&|>,?~\n\t \u00e9\u2028'
    return ''.join(rng.choice(alphabet) for dummy in range(rng.randrange(0, 12)))


def random_value(rng, depth=0):
    kind = rng.randrange(8 if depth < 3 else 5)
    if kind < 3:
        return random_text(rng)
    if kind == 3:
        return rng.choice([None, True, False, 0, 1, -7, 12345, 0.25])
    if kind == 4:
        return rng.choice(['yes', 'no', 'null', '1', '1.0', 'a b', 'plain', 'x: y', '{{ v }}'])
    if kind == 5:
        return [random_value(rng, depth + 1) for dummy in range(rng.randrange(0, 4))]
    return dict((random_text(rng) if rng.randrange(3) else 'k%d' % n, random_value(rng, depth + 1))
                for n in range(rng.randrange(0, 4)))


def test_made_up_data_comes_back_as_it_was():
    rng = random.Random(20261004)
    for dummy in range(1500):
        data = dict(root=random_value(rng), more=[random_value(rng), random_value(rng)])
        text = plugin.to_yaml(data)
        assert load(text) == data, text


def test_a_mapping_key_that_is_not_text_is_refused():
    with pytest.raises(ValueError, match='key has to be text'):
        plugin.to_yaml({'a': {0.5: 1}})


def test_the_text_is_block_style_with_no_long_flow_collections():
    text = plugin.to_yaml(dict(a=dict(b=[dict(c=1, d=[2, 3])]), e=[], f={}))
    assert text == 'a:\n  b:\n    - c: 1\n      d:\n        - 2\n        - 3\ne: []\nf: {}\n'


def test_a_text_of_several_lines_is_a_block():
    text = plugin.to_yaml(dict(inventory='[all]\nlocalhost\n', key='a\nb'))
    assert text == 'inventory: |\n  [all]\n  localhost\nkey: |-\n  a\n  b\n'


# ---- the round trip on the recorded servers -----------------------------------------

def stand_in(value):
    """The exported options with each reference to a vault variable replaced by a value."""
    if isinstance(value, str) and value.startswith('{{ vault_'):
        return 'from-the-vault'
    if isinstance(value, dict):
        return dict((key, stand_in(item)) for key, item in value.items())
    if isinstance(value, list):
        return [stand_in(item) for item in value]
    return value


@pytest.mark.parametrize('section', sorted(SECTIONS))
def test_applying_what_was_exported_changes_nothing(server, run_module, section):
    manage, info_module, key, routes = SECTIONS[section]
    scope = routes(server)
    found = run_module(info_module.main, scope)
    assert found.get('failed') is not True, found.get('msg')
    assert found[key], 'the recorded server has no %s' % section
    project_name = scope['project']
    info = dict(project=dict(id=1, name=project_name), **{section: found[key]})
    exported = load(plugin.project_export_yaml(info, section))[section]
    assert sorted(exported) == sorted('%s' % item[plugin.NAME_FIELD.get(section, 'name')] for item in found[key])

    # A server that takes no write: a change would fail the task.
    recorded.drop_write_routes(server)
    for name, options in exported.items():
        if name in NOT_RECORDED.get(section, ()):
            continue
        args = dict(stand_in(options), project=project_name)
        args['user' if section == 'team_member' else 'name'] = name
        if section in plugin.SECRETS:
            # A secret can't be compared with what is stored, so the modules
            # send it on every run unless told not to.
            args['update_secret'] = 'on_create'
        result = run_module(manage.main, args)
        assert result.get('failed') is not True, '%s %s: %s' % (section, name, result.get('msg'))
        assert result['changed'] is False, '%s %s: %s' % (section, name, result.get('diff'))
    assert recorded.writes(server) == []


def test_applying_the_exported_project_options_changes_nothing(server, run_module):
    recorded.project_list(server)
    found = run_module(project_info.main, {})['projects']
    for stored in found:
        options = load(plugin.project_export_yaml(dict(project=stored), 'project'))
        recorded.drop_write_routes(server)
        result = run_module(project.main, options)
        assert result.get('failed') is not True, result.get('msg')
        assert result['changed'] is False, result.get('diff')
