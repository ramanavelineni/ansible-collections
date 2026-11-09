# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""The filters of the project_export role.

Three things are held here:

  - the tables in the filter plugin against the modules' own argument specs,
    so an option a module gains, a default it changes or a secret it adds
    fails a test instead of going missing from an export;
  - the YAML the plugin writes, by reading it back with a YAML library;
  - the round trip on the recorded servers: what an _info module returns is
    exported, the exported options are given to the module that manages the
    object, and nothing may change.
"""

import copy

import pytest
import yaml

from ansible_collections.ramanavelineni.harbor.plugins.filter import project_export as plugin
from ansible_collections.ramanavelineni.harbor.plugins.module_utils.harbor import harbor_argument_spec
from ansible_collections.ramanavelineni.harbor.plugins.modules import (
    project as project_module,
    project_member,
    project_member_info,
    webhook,
    webhook_info,
)
from ansible_collections.ramanavelineni.harbor.tests.unit.plugins.modules.test_examples import module_spec

# A project as the _info modules return it: one of each kind of object, with
# the fields Harbor fills in that an export has to leave out.
INFO = dict(
    project=dict(project_id=3, name='apps', public=False, repo_count=2, registry_id=None, proxy_registry=None,
                 quota_gb=50, metadata={'auto_scan': 'true', 'severity': 'high', 'retention_id': '7',
                                        'proxy_speed_kb': '100'}),
    robot_account=[dict(id=9, name='ci', full_name='robot$apps+ci', level='project', project='apps',
                        description='', duration=90, expires_at=1900000000, disable=False,
                        permissions=[dict(kind='project', namespace='apps',
                                          access=[dict(resource='repository', action='push')])])],
    project_member=[dict(id=1, project='apps', project_id=3, user='admin', group=None, group_type=None,
                         role='project_admin', role_id=1),
                    dict(id=7, project='apps', project_id=3, user=None, group='readers', group_type='oidc',
                         role='guest', role_id=3)],
    tag_retention=dict(id=4, project='apps', schedule='0 0 3 * * *', rules=[
        dict(template='latestPushedK', value=10, repositories='**', repositories_decoration='matches', tags='**',
             tags_decoration='matches', untagged=False, disabled=False),
        dict(template='always', value=None, repositories='base/**', repositories_decoration='matches', tags='**',
             tags_decoration='matches', untagged=False, disabled=True)]),
    tag_immutability=[dict(id=2, project='apps', repositories='**', repositories_decoration='matches', tags='v*',
                           tags_decoration='matches', disabled=False)],
    webhook=[dict(id=5, name='ci-notify', project='apps', project_id=3, description='', enabled=True,
                  event_types=['PUSH_ARTIFACT', 'DELETE_ARTIFACT'], notify_type='http',
                  address='https://ci.example.com/hook', auth_header_set=True, skip_cert_verify=False,
                  payload_format='Default', endpoints=1)],
)

# Hand-derived from INFO: what project_apply should be given.
EXPECTED = {
    'name': 'apps',
    'public': False,
    'metadata': {'auto_scan': True, 'proxy_speed_kb': 100, 'severity': 'high'},
    'quota_gb': 50,
    'robot_account': {'ci': {'duration': 90, 'permissions': [{'access': [{'resource': 'repository', 'action': 'push'}]}],
                             'secret': '{{ vault_apps_robot_ci_secret }}', 'update_secret': 'on_create'}},
    'project_member': [{'user': 'admin', 'role': 'project_admin'},
                       {'group': 'readers', 'group_type': 'oidc', 'role': 'guest'}],
    'tag_retention': {'schedule': '0 0 3 * * *',
                      'rules': [{'template': 'latestPushedK', 'value': 10},
                                {'template': 'always', 'repositories': 'base/**', 'disabled': True}]},
    'tag_immutability': [{'tags': 'v*'}],
    'webhook': {'ci-notify': {'event_types': ['DELETE_ARTIFACT', 'PUSH_ARTIFACT'],
                              'address': 'https://ci.example.com/hook',
                              'auth_header': '{{ vault_apps_webhook_ci_notify_auth_header }}'}},
}


def spec(name):
    return module_spec(name)['argument_spec']


# -- the tables against the modules ---------------------------------------------

@pytest.mark.parametrize('section', sorted(plugin.OPTIONS))
def test_every_exported_option_is_an_option_of_its_module(section):
    options = spec(section)
    for option, default in plugin.OPTIONS[section]:
        assert option in options, '%s has no option %s' % (section, option)
        module_default = options[option].get('default')
        if default is not plugin.KEEP and module_default is not None:
            # Where the module has a default, the table's must be the same. A
            # module without one leaves the option alone; the table holds what
            # Harbor gives a new object then.
            assert module_default == default, (section, option)


def test_retention_rule_defaults_are_the_modules():
    rules = spec('tag_retention')['rules']['options']
    for option, default in plugin.RULE_OPTIONS:
        assert option in rules, option
        if default is not plugin.KEEP:
            assert rules[option].get('default') == default, option


@pytest.mark.parametrize('section', sorted(plugin.SECRETS))
def test_the_secrets_are_the_options_the_module_hides(section):
    # The connection's password is every module's; it is never part of a project file.
    connection = harbor_argument_spec()
    hidden = sorted(name for name, option in spec(section).items() if option.get('no_log') and name not in connection)
    assert sorted(plugin.SECRETS[section]) == hidden


def test_metadata_keys_are_the_project_modules():
    assert plugin.METADATA_BOOL == project_module.BOOL_KEYS
    assert plugin.METADATA_INT == project_module.INT_KEYS


def test_project_options_are_options_of_the_project_module():
    options = spec('project')
    for option, dummy in plugin.PROJECT_OPTIONS:
        assert option in options


# -- what is exported -------------------------------------------------------------

def test_export_leaves_out_ids_defaults_and_secrets():
    assert plugin.project_export_config(INFO) == EXPECTED


def test_the_yaml_reads_back_as_the_config():
    assert yaml.safe_load(plugin.project_export_yaml(INFO)) == EXPECTED


def test_each_part_reads_back_as_its_share():
    project = yaml.safe_load(plugin.project_export_yaml(INFO, 'project'))
    assert project == dict((k, v) for k, v in EXPECTED.items() if k not in plugin.SECTIONS)
    for section in plugin.SECTIONS:
        assert yaml.safe_load(plugin.project_export_yaml(INFO, section)) == {section: EXPECTED[section]}


def test_a_section_without_objects_gives_no_text():
    info = dict(INFO, webhook=[])
    assert plugin.project_export_yaml(info, 'webhook') == ''
    assert 'webhook' not in plugin.project_export_config(info)


def test_the_same_project_gives_the_same_text():
    shuffled = copy.deepcopy(INFO)
    shuffled['robot_account'].append(dict(shuffled['robot_account'][0], id=10, name='alpha'))
    reversed_info = copy.deepcopy(shuffled)
    reversed_info['robot_account'].reverse()
    assert plugin.project_export_yaml(shuffled) == plugin.project_export_yaml(reversed_info)


def test_the_vault_file_lists_every_secret_empty():
    loaded = yaml.safe_load(plugin.project_export_vault(INFO))
    assert loaded == {'vault_apps_robot_ci_secret': '', 'vault_apps_webhook_ci_notify_auth_header': ''}
    assert [v['name'] for v in plugin.project_export_vault_variables(INFO)] == list(loaded)


def test_a_project_without_secrets_has_an_empty_vault_file():
    info = dict(INFO, robot_account=[], webhook=[])
    assert yaml.safe_load(plugin.project_export_vault(info)) == {}
    assert plugin.project_export_vault_variables(info) == []


def test_a_slack_webhook_url_is_a_secret():
    hook = dict(INFO['webhook'][0], notify_type='slack', address='https://hooks.slack.com/T/B/x', auth_header_set=False,
                payload_format=None)
    out = plugin.project_export_config(dict(INFO, webhook=[hook]))['webhook']['ci-notify']
    assert out['address'] == '{{ vault_apps_webhook_ci_notify_address }}'
    assert out['notify_type'] == 'slack'
    assert 'hooks.slack.com' not in plugin.project_export_yaml(dict(INFO, webhook=[hook]))


def test_two_names_that_give_one_variable_get_two():
    robots = [dict(INFO['robot_account'][0], name='ci-x'), dict(INFO['robot_account'][0], name='ci_x')]
    names = [v['name'] for v in plugin.project_export_vault_variables(dict(INFO, robot_account=robots, webhook=[]))]
    assert names == ['vault_apps_robot_ci_x_secret', 'vault_apps_robot_ci_x_secret_2']


def test_a_value_that_looks_like_a_template_is_written_unsafe():
    hook = dict(INFO['webhook'][0], description='{{ not a template }}')
    text = plugin.project_export_yaml(dict(INFO, webhook=[hook]))
    assert 'description: !unsafe "{{ not a template }}"' in text


def test_system_robots_are_not_exported():
    robots = INFO['robot_account'] + [dict(INFO['robot_account'][0], name='puller', level='system')]
    assert list(plugin.project_export_config(dict(INFO, robot_account=robots))['robot_account']) == ['ci']


def test_the_projects_retention_id_and_public_are_not_metadata():
    out = plugin.project_export_config(INFO)
    assert 'retention_id' not in out['metadata'] and 'public' not in out['metadata']


def test_a_proxy_cache_project_names_its_registry():
    project = dict(INFO['project'], registry_id=2, proxy_registry='hub')
    assert plugin.project_export_config(dict(INFO, project=project))['proxy_registry'] == 'hub'


# -- what stops the export --------------------------------------------------------

@pytest.mark.parametrize('change, message', [
    (dict(project_member=[dict(INFO['project_member'][1], group_type=None)]),
     'the type of group member readers of project apps could not be read'),
    (dict(webhook=[dict(INFO['webhook'][0], endpoints=2)]), 'webhook ci-notify of project apps has 2 endpoints'),
    (dict(project=dict(INFO['project'], registry_id=2, proxy_registry=None)),
     'project apps is a proxy cache, but the name of its registry could not be read'),
    (dict(project=dict(INFO['project'], metadata={'brand_new': 'x'})),
     'project apps has the metadata key brand_new, which this collection does not know'),
    (dict(project_member=[dict(INFO['project_member'][0], role=None, role_id=9)]),
     'member admin of project apps has a role this collection does not know'),
    (dict(project=dict(INFO['project'], metadata={'proxy_speed_kb': 'fast'})), 'is not a whole number'),
])
def test_what_project_apply_could_not_apply_stops_the_export(change, message):
    with pytest.raises(ValueError) as failure:
        plugin.project_export_config(dict(INFO, **change))
    assert message in str(failure.value)


@pytest.mark.parametrize('info', [None, {}, dict(project={}), dict(project=dict(name='apps'), webhook={})])
def test_input_that_is_not_what_the_info_modules_return_is_refused(info):
    with pytest.raises(ValueError):
        plugin.project_export_config(info)


def test_a_vault_prefix_that_is_not_a_variable_name_is_refused():
    with pytest.raises(ValueError) as failure:
        plugin.project_export_config(INFO, vault_prefix='My-Vault')
    assert 'not a variable name' in str(failure.value)


def test_an_unknown_part_is_refused():
    with pytest.raises(ValueError):
        plugin.project_export_yaml(INFO, 'registry')


# -- the round trip on the recorded servers ---------------------------------------

@pytest.fixture
def members_base(server):
    server.route('GET', '/projects', 'member_projects')
    return '/projects/%d/members' % server.fixtures['member_projects']['body'][0]['project_id']


def test_exported_members_apply_without_a_change(server, run_module, members_base):
    server.route('GET', members_base, 'member_list_all')
    server.route('GET', '/usergroups', 'member_usergroups_all')
    found = run_module(project_member_info.main, dict(project='fixtures-member'))['members']
    exported = plugin.project_export_config(dict(project=dict(name='fixtures-member', public=False),
                                                 project_member=found))['project_member']
    assert len(exported) == len(found) == 3
    server.route('GET', '/usergroups', 'member_usergroups_one')
    for member in exported:
        result = run_module(project_member.main, dict(member, project='fixtures-member'))
        assert result.get('failed') is not True, result.get('msg')
        assert result['changed'] is False, member
    assert [r['method'] for r in server.requests if r['method'] != 'GET'] == []


def test_an_exported_webhook_applies_without_a_change(server, run_module):
    server.route('GET', '/projects', 'webhook_projects')
    base = '/projects/%d/webhook/policies' % server.fixtures['webhook_projects']['body'][0]['project_id']
    server.route('GET', base, 'webhook_list_one')
    found = run_module(webhook_info.main, dict(project='fixtures-webhook'))['webhooks']
    exported = plugin.project_export_config(dict(project=dict(name='fixtures-webhook', public=False),
                                                 webhook=found))['webhook']
    assert list(exported) == ['ci-notify']
    options = dict(exported['ci-notify'])
    # What the vault would hold: the header the recorded webhook was made with.
    assert options.pop('auth_header') == '{{ vault_fixtures_webhook_webhook_ci_notify_auth_header }}'
    result = run_module(webhook.main, dict(options, project='fixtures-webhook', name='ci-notify',
                                           auth_header='Bearer not-a-real-token'))
    assert result.get('failed') is not True, result.get('msg')
    assert result['changed'] is False
