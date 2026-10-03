# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""Option checks, name filters and failure branches that had no test."""

import io
import json
from urllib.error import HTTPError

import pytest

from ansible.module_utils.basic import AnsibleModule

from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.semaphore import LIST_CAP
from ansible_collections.ramanavelineni.semaphoreui.plugins.modules import (
    integration,
    integration_info,
    inventory_info,
    key_store,
    project,
    project_info,
    runner_info,
    schedule,
    template,
    template_info,
    user,
    variable_group_info,
    view,
    view_info,
)


def fid(server, fixture):
    return server.fixtures[fixture]['body']['id']


def writes(server):
    return [r for r in server.requests if r['method'] != 'GET' and not r['path'].startswith('/auth/')]


@pytest.fixture
def base(server):
    """A project with one of everything; returns its API path."""
    server.route('GET', '/projects', 'projects_one')
    path = '/project/%d' % server.fixtures['projects_one']['body'][0]['id']
    server.route('GET', path + '/repositories', 'repositories_one')
    server.route('GET', path + '/inventory', 'inventories_one')
    server.route('GET', path + '/environment', 'variable_groups_for_templates')
    server.route('GET', path + '/views', 'views_two')
    server.route('GET', path + '/keys', 'keys_with_deploy')
    server.route('GET', path + '/templates', 'templates_one')
    server.route('GET', '%s/templates/%d' % (path, fid(server, 'template_create')), 'template_get')
    server.route('GET', path + '/schedules', 'schedules_project_list')
    server.route('GET', '%s/templates/%d/schedules' % (path, fid(server, 'template_create')), 'schedules_empty')
    server.route('GET', path + '/integrations', 'integrations_empty')
    return path


# -- integration ----------------------------------------------------------------

GH = dict(project='homelab', name='gh', template='site')


@pytest.mark.parametrize('option, items', [
    ('matchers', [dict(name='main', key='ref', value='a'), dict(name='main', key='ref', value='b')]),
    ('extract_values', [dict(name='sha', key='after', variable='A'), dict(name='sha', key='before', variable='B')]),
])
def test_integration_item_names_must_be_unique(server, base, run_module, option, items):
    result = run_module(integration.main, dict(GH, **{option: items}))
    assert result['failed'] is True
    assert result['msg'] == '%s names must be unique.' % option
    assert writes(server) == []


@pytest.mark.parametrize('value', [
    dict(name='sha', variable='COMMIT_SHA'),
    dict(name='sha', variable='COMMIT_SHA', value_source='header', body_data_type='string'),
], ids=['json-body', 'header'])
def test_integration_extracted_value_needs_key(server, base, run_module, value):
    result = run_module(integration.main, dict(GH, extract_values=[value]))
    assert result['failed'] is True
    assert result['msg'] == "Extracted value 'sha' needs key."
    assert writes(server) == []


def test_integration_string_body_value_needs_no_key(server, base, run_module):
    value = dict(name='raw', variable='PAYLOAD', body_data_type='string')
    result = run_module(integration.main, dict(GH, extract_values=[value]), check_mode=True)
    assert result.get('failed') is not True, result.get('msg')
    assert result['changed'] is True


def test_integration_unknown_template(server, base, run_module):
    result = run_module(integration.main, dict(GH, template='nope'))
    assert result['failed'] is True
    assert result['msg'] == "Template 'nope' does not exist in project 'homelab'."
    assert writes(server) == []


def test_integration_create_needs_template(server, base, run_module):
    result = run_module(integration.main, dict(project='homelab', name='gh'))
    assert result['failed'] is True
    assert result['msg'] == "Creating integration 'gh' needs template."
    assert writes(server) == []


def test_integration_info_filters_by_name(server, base, run_module):
    path = '%s/integrations/%d' % (base, fid(server, 'integration_create'))
    server.route('GET', base + '/integrations', 'integrations_one')
    server.route('GET', path + '/matchers', 'integration_matchers_one')
    server.route('GET', path + '/values', 'integration_values_one')
    server.route('GET', path + '/aliases', 'integration_aliases_one')
    assert [i['name'] for i in run_module(integration_info.main, dict(project='homelab', name='gh'))['integrations']] == ['gh']
    del server.requests[:]
    assert run_module(integration_info.main, dict(project='homelab', name='other'))['integrations'] == []
    # What is filtered out is not read either.
    assert server.calls('GET', path + '/matchers') == []


def stored_integration(server, base, aliases='integration_aliases_one'):
    path = '%s/integrations/%d' % (base, fid(server, 'integration_create'))
    server.route('GET', base + '/integrations', 'integrations_one')
    server.route('GET', path, 'integration_get')
    server.route('GET', path + '/matchers', 'integration_matchers_one')
    server.route('GET', path + '/values', 'integration_values_one')
    server.route('GET', path + '/aliases', aliases)
    return path


@pytest.mark.parametrize('items', [
    dict(matchers=[dict(name='main', key='ref', value='refs/heads/develop')]),
    dict(matchers=[dict(name='main', key='ref', value='refs/heads/main'), dict(name='event', key='action', value='push')]),
    dict(matchers=[]),
    dict(extract_values=[]),
], ids=['matcher-changed', 'matcher-added', 'matchers-removed', 'values-removed'])
def test_integration_items_in_check_mode(server, base, run_module, items):
    stored_integration(server, base)
    result = run_module(integration.main, dict(project='homelab', name='gh', **items), check_mode=True)
    assert result['changed'] is True
    assert writes(server) == []
    option = list(items)[0]
    assert result['diff']['before'][option] != result['diff']['after'][option]
    # Items are reported sorted by name.
    assert [i['name'] for i in result['integration'][option]] == sorted(i['name'] for i in items[option])


def test_integration_missing_alias_in_check_mode(server, base, run_module):
    stored_integration(server, base, aliases='integration_aliases_empty')
    result = run_module(integration.main, dict(project='homelab', name='gh'), check_mode=True)
    # The webhook URL is the server's to give, so check mode has none to show.
    assert result['changed'] is True and result['webhook_urls'] == []
    assert writes(server) == []


# -- key_store ------------------------------------------------------------------

def test_key_without_secret_stays_as_it_is(server, base, run_module):
    # "None" is the key of type none every project starts with.
    result = run_module(key_store.main, dict(project='homelab', name='None', type='none'))
    assert result['changed'] is False and result['secret_updated'] is False
    assert result['key']['type'] == 'none'
    assert writes(server) == []


# -- schedule -------------------------------------------------------------------

def test_run_at_schedule_cannot_poll(server, base, run_module):
    result = run_module(schedule.main, dict(project='homelab', name='once', template='site', repository='ansible',
                                            run_at='2099-01-01T03:00:00Z'))
    assert result['failed'] is True
    assert result['msg'] == 'A run-at schedule cannot poll a repository.'
    assert [r for r in server.requests if r['path'].startswith('/project')] == []


def test_run_at_schedule_may_clear_the_repository(server, base, run_module):
    result = run_module(schedule.main, dict(project='homelab', name='once', template='site', repository='',
                                            run_at='2099-01-01T03:00:00Z'), check_mode=True)
    assert result.get('failed') is not True, result.get('msg')
    assert result['schedule']['kind'] == 'run_at'


@pytest.mark.parametrize('args, message', [
    (dict(template='nope', cron='0 4 * * *'), "Template 'nope' does not exist in project 'homelab'."),
    (dict(template='site', repository='nope', cron='0 4 * * *'), "Repository 'nope' does not exist in project 'homelab'."),
], ids=['template', 'repository'])
def test_schedule_unknown_reference(server, base, run_module, args, message):
    result = run_module(schedule.main, dict(project='homelab', name='new', **args))
    assert result['failed'] is True
    assert result['msg'] == message
    assert writes(server) == []


# -- template -------------------------------------------------------------------

SITE = dict(project='homelab', name='site')


@pytest.mark.parametrize('args, message', [
    (dict(vaults=[dict(name='prod')]), "Vault 'prod' of type password needs key."),
    (dict(vaults=[dict(name='prod', type='script')]), "Vault 'prod' of type script needs script."),
    (dict(vaults=[dict(key='deploy'), dict(key='deploy')]), 'Vault names must be unique.'),
    (dict(survey_vars=[dict(name='env', title='Env', type='enum')]), "Survey variable 'env' of type enum needs values."),
    (dict(type='deploy'), 'A deploy template needs build_template.'),
], ids=['vault-key', 'vault-script', 'vault-names', 'enum-values', 'deploy'])
def test_template_option_checks(server, base, run_module, args, message):
    server.route('PUT', '%s/templates/%d' % (base, fid(server, 'template_create')), 'template_update')
    result = run_module(template.main, dict(SITE, **args))
    assert result['failed'] is True
    assert result['msg'] == message
    assert writes(server) == []


def test_template_enum_values_are_sent(server, base, run_module):
    path = '%s/templates/%d' % (base, fid(server, 'template_create'))
    server.route('PUT', path, 'template_update')
    choices = [dict(name='Production', value='prod'), dict(name='Staging', value='stage')]
    result = run_module(template.main, dict(SITE, survey_vars=[dict(name='env', title='Env', type='enum', values=choices)]))
    assert result['changed'] is True
    sent = server.calls('PUT', path)[0]['body']['survey_vars']
    assert sent == [dict(name='env', title='Env', type='enum', required=False, description='', default_value='',
                         values=choices)]
    assert result['template']['survey_vars'][0]['values'] == choices


def test_template_create_needs_playbook(server, base, run_module):
    server.route('GET', base + '/templates', 'templates_empty')
    result = run_module(template.main, dict(project='homelab', name='new', repository='ansible', inventory='homelab',
                                            variable_groups=['empty']))
    assert result['failed'] is True
    assert result['msg'] == "Creating template 'new' needs playbook."
    assert writes(server) == []


@pytest.mark.parametrize('option, value, message', [
    ('repository', 'nope', "Repository 'nope' does not exist in project 'homelab'."),
    ('inventory', 'nope', "Inventory 'nope' does not exist in project 'homelab'."),
    ('view', 'nope', "View 'nope' does not exist in project 'homelab'."),
    ('variable_groups', ['nope'], "Variable group 'nope' does not exist in project 'homelab'."),
], ids=['repository', 'inventory', 'view', 'variable_group'])
def test_template_unknown_reference(server, base, run_module, option, value, message):
    server.route('PUT', '%s/templates/%d' % (base, fid(server, 'template_create')), 'template_update')
    result = run_module(template.main, dict(SITE, **{option: value}))
    assert result['failed'] is True
    assert result['msg'] == message
    assert writes(server) == []
    # In check mode an earlier task is assumed to create it.
    checked = run_module(template.main, dict(SITE, **{option: value}), check_mode=True)
    assert checked['changed'] is True and message in json.dumps(checked['warnings'])


def test_template_with_a_view_that_is_gone(server, base, run_module):
    # Hand-edited: the recorded template pointing at a view the list doesn't have.
    stored = server.response('template_get')
    stored['body']['view_id'] = 99999
    server.route('GET', '%s/templates/%d' % (base, fid(server, 'template_create')), stored)
    result = run_module(template_info.main, dict(project='homelab'))
    assert result['templates'][0]['view'] is None
    assert result['templates'][0]['repository'] == 'ansible'


def test_template_app_list_that_fails_is_reported(server, base, run_module):
    # Hand-written: no failing /apps answer was recorded.
    server.route('GET', '/apps', dict(status=500, body=dict(error='database is locked')))
    result = run_module(template.main, dict(SITE, app='pulumi-custom'))
    assert result['failed'] is True
    assert 'HTTP 500' in result['msg'] and 'database is locked' in result['msg']
    assert writes(server) == []


def test_template_app_list_in_another_form_is_not_used(server, base, run_module):
    # Hand-written: a server that answers /apps with something else than a list.
    server.route('GET', '/apps', dict(status=200, body=dict(apps='moved')))
    server.route('PUT', '%s/templates/%d' % (base, fid(server, 'template_create')), 'template_update')
    result = run_module(template.main, dict(SITE, app='pulumi-custom'))
    assert result.get('failed') is not True, result.get('msg')
    assert result['changed'] is True and result['template']['app'] == 'pulumi-custom'


# -- view -----------------------------------------------------------------------

def test_view_created_at_the_position_asked_for(server, base, run_module):
    server.route('POST', base + '/views', 'view_create')
    run_module(view.main, dict(project='homelab', name='first', position=0, sort_column='name', sort_reverse=True))
    body = server.calls('POST', base + '/views')[0]['body']
    assert (body['title'], body['position'], body['sort_column'], body['sort_reverse']) == ('first', 0, 'name', True)
    predicted = run_module(view.main, dict(project='homelab', name='first', position=0), check_mode=True)
    assert predicted['view']['position'] == 0
    # Without a position the view goes after the last one.
    after_last = run_module(view.main, dict(project='homelab', name='last'), check_mode=True)
    assert after_last['view']['position'] == 1 + max(v.get('position', 0) for v in server.fixtures['views_two']['body'])


# -- user -----------------------------------------------------------------------

def test_external_user_takes_no_password(server, run_module):
    result = run_module(user.main, dict(login='sso-user', name='S', email='s@example.com', external=True,
                                        user_password='pw-unit-7'))
    assert result['failed'] is True
    assert result['msg'] == 'An external user has no local password; drop user_password or external.'
    assert 'pw-unit-7' not in json.dumps(result)
    assert [r for r in server.requests if r['path'].startswith('/user')] == []


def test_external_false_with_a_password_is_fine(server, run_module):
    server.route('GET', '/user', 'user_me')
    server.route('GET', '/users', 'user_list')
    result = run_module(user.main, dict(login='new-user', name='N', email='n@example.com', external=False,
                                        user_password='pw-unit-6'), check_mode=True)
    assert result.get('failed') is not True, result.get('msg')
    assert result['changed'] is True


# -- name filters of the _info modules ------------------------------------------

@pytest.mark.parametrize('module, key, name', [
    (inventory_info, 'inventories', 'homelab'),
    (variable_group_info, 'variable_groups', 'empty'),
    (view_info, 'views', 'k8s'),
], ids=['inventory', 'variable_group', 'view'])
def test_info_filters_by_name(server, base, run_module, module, key, name):
    group = [g for g in server.fixtures['variable_groups_for_templates']['body'] if g['name'] == 'empty'][0]
    server.route('GET', '%s/environment/%d' % (base, group['id']), dict(status=200, body=group))
    assert [o['name'] for o in run_module(module.main, dict(project='homelab', name=name))[key]] == [name]
    assert run_module(module.main, dict(project='homelab', name='no-such-name'))[key] == []
    assert len(run_module(module.main, dict(project='homelab'))[key]) >= 1


def test_runner_info_filters_by_name(server, run_module):
    listing = server.response('runner_list_one')
    listing['body'].append(dict(listing['body'][0], id=fid(server, 'runner_create') + 1, name='other'))
    server.route('GET', '/runners', listing)
    assert [r['name'] for r in run_module(runner_info.main, {})['runners']] == ['other', 'rn-fixture']
    assert [r['name'] for r in run_module(runner_info.main, dict(name='other'))['runners']] == ['other']
    assert run_module(runner_info.main, dict(name='no-such-name'))['runners'] == []


def test_project_info_warns_at_the_list_cap(server, run_module, mocker):
    # Hand-made: the recorded project, repeated up to the most Semaphore lists.
    listing = server.response('projects_one')
    listing['body'] = [dict(listing['body'][0], id=n, name='p%d' % n) for n in range(LIST_CAP - 1)]
    server.route('GET', '/projects', listing)
    # Warnings pile up across module runs in one process, so the calls are counted, not the result's list.
    warn = mocker.spy(AnsibleModule, 'warn')
    assert len(run_module(project_info.main, {})['projects']) == LIST_CAP - 1
    assert warn.call_count == 0
    listing['body'].append(dict(listing['body'][0], id=LIST_CAP, name='last'))
    server.route('GET', '/projects', listing)
    result = run_module(project_info.main, {})
    assert len(result['projects']) == LIST_CAP
    assert warn.call_count == 1
    assert 'Semaphore returned %d projects, the most it lists; some may be missing.' % LIST_CAP in json.dumps(result['warnings'])


# -- the client -----------------------------------------------------------------

def test_url_that_cannot_be_parsed(server, run_module):
    result = run_module(project.main, dict(name='homelab', url='http://[::1'))
    assert result['failed'] is True
    assert 'url must be the address of the Semaphore server' in result['msg']
    assert server.requests == []


class BrokenBody(io.BytesIO):
    def read(self, size=-1):
        raise OSError('connection lost while the error was read')


def test_error_whose_body_cannot_be_read(server, run_module):
    # Hand-written: an error answer that breaks off before its body arrives.
    server.route('GET', '/projects', HTTPError('https://semaphore.example.com/api/projects', 400, 'error', {}, BrokenBody()))
    result = run_module(project.main, dict(name='homelab'))
    assert result['failed'] is True
    assert 'returned HTTP 400' in result['msg'] and '(empty body)' in result['msg']
    assert server.requests[-1]['path'] == '/auth/logout'
