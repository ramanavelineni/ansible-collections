# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""Every manage module, every operation: check mode against a real run, the diff, and the documented return values.

One table of scenarios. Each sets up the recorded reads and writes of one
operation and returns the task's options. The tests below run a scenario for
real, then again in check mode on a server that has no write route left.
"""

import pytest
import yaml

from ansible_collections.ramanavelineni.semaphoreui.plugins.modules import (
    info,
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
    runner,
    runner_info,
    schedule,
    schedule_info,
    team_member,
    team_member_info,
    template,
    template_info,
    user,
    user_info,
    variable_group,
    variable_group_info,
    view,
    view_info,
)

PRIVATE_KEY = '-----BEGIN OPENSSH PRIVATE KEY-----\nunit-test\n-----END OPENSSH PRIVATE KEY-----'
TEAM_PROJECT = 'fixtures-team'


def fid(server, fixture):
    return server.fixtures[fixture]['body']['id']


def homelab(server):
    server.route('GET', '/projects', 'projects_one')
    return '/project/%d' % server.fixtures['projects_one']['body'][0]['id']


def single(server, fixture):
    """A recorded create answer, served as the answer to a read of that object."""
    answer = server.response(fixture)
    answer['status'] = 200
    return answer


# -- project --------------------------------------------------------------------

def project_create(server):
    server.route('GET', '/projects', 'projects_empty')
    server.route('POST', '/projects', 'project_create')
    return dict(name='homelab')


def project_update(server):
    server.route('GET', '/projects', 'projects_one')
    server.route('PUT', '/project/%d' % fid(server, 'project_create'), 'project_update')
    return dict(name='homelab', alert=True)


def project_delete(server):
    server.route('GET', '/projects', 'projects_one')
    server.route('DELETE', '/project/%d' % fid(server, 'project_create'), 'project_delete')
    return dict(name='homelab', state='absent', confirm_delete=True)


# -- key_store ------------------------------------------------------------------

def key_create(server):
    base = homelab(server)
    server.route('GET', base + '/repositories', 'repositories_empty')
    server.route('GET', base + '/keys', 'keys_new_project')
    server.route('POST', base + '/keys', 'key_create')
    return dict(project='homelab', name='deploy', type='ssh', ssh=dict(login='git', private_key=PRIVATE_KEY))


def key_update(server):
    base = homelab(server)
    server.route('GET', base + '/repositories', 'repositories_empty')
    server.route('GET', base + '/keys', 'keys_with_deploy')
    server.route('PUT', '%s/keys/%d' % (base, fid(server, 'key_create')), 'key_update')
    return dict(project='homelab', name='deploy', type='login_password',
                login_password=dict(login='git', password='pw-unit-key'))


def key_delete(server):
    base = homelab(server)
    path = '%s/keys/%d' % (base, fid(server, 'key_create'))
    server.route('GET', base + '/repositories', 'repositories_empty')
    server.route('GET', base + '/keys', 'keys_with_deploy')
    server.route('GET', path + '/refs', 'key_refs_unused')
    server.route('DELETE', path, 'key_delete')
    return dict(project='homelab', name='deploy', state='absent')


# -- repository -----------------------------------------------------------------

def repository_routes(server, listing):
    base = homelab(server)
    server.route('GET', base + '/keys', 'keys_with_deploy')
    server.route('GET', base + '/repositories', listing)
    return base, '%s/repositories/%d' % (base, fid(server, 'repository_create'))


def repository_create(server):
    base, dummy = repository_routes(server, 'repositories_empty')
    server.route('POST', base + '/repositories', 'repository_create')
    return dict(project='homelab', name='ansible', git_url='git@github.com:example/ansible.git', git_branch='main',
                ssh_key='deploy')


def repository_update(server):
    dummy, path = repository_routes(server, 'repositories_one')
    server.route('PUT', path, 'repository_update')
    return dict(project='homelab', name='ansible', git_branch='develop')


def repository_delete(server):
    dummy, path = repository_routes(server, 'repositories_one')
    server.route('GET', path + '/refs', 'repository_refs_unused')
    server.route('DELETE', path, 'repository_delete')
    return dict(project='homelab', name='ansible', state='absent')


# -- inventory ------------------------------------------------------------------

def inventory_routes(server, listing):
    base = homelab(server)
    server.route('GET', base + '/keys', 'keys_with_deploy')
    server.route('GET', base + '/repositories', 'repositories_one')
    server.route('GET', base + '/inventory', listing)
    return base, '%s/inventory/%d' % (base, fid(server, 'inventory_create'))


def inventory_create(server):
    base, dummy = inventory_routes(server, 'inventories_empty')
    server.route('POST', base + '/inventory', 'inventory_create')
    return dict(project='homelab', name='homelab', type='file', inventory='inventories/homelab/hosts',
                repository='ansible', ssh_key='deploy')


def inventory_update(server):
    dummy, path = inventory_routes(server, 'inventories_one')
    server.route('PUT', path, 'inventory_update')
    return dict(project='homelab', name='homelab', become_key='deploy')


def inventory_delete(server):
    dummy, path = inventory_routes(server, 'inventories_one')
    server.route('GET', path + '/refs', 'inventory_refs_unused')
    server.route('DELETE', path, 'inventory_delete')
    return dict(project='homelab', name='homelab', state='absent')


# -- view -----------------------------------------------------------------------

def view_create(server):
    base = homelab(server)
    # The recorded create answer is the k8s view, so this is the recorded list without it.
    listing = server.response('views_two')
    listing['body'] = [v for v in listing['body'] if v['title'] != 'k8s']
    server.route('GET', base + '/views', listing)
    server.route('POST', base + '/views', 'view_create')
    return dict(project='homelab', name='k8s')


def k8s_view(server):
    base = homelab(server)
    server.route('GET', base + '/views', 'views_two')
    view_id = [v for v in server.fixtures['views_two']['body'] if v['title'] == 'k8s'][0]['id']
    return '%s/views/%d' % (base, view_id)


def view_update(server):
    server.route('PUT', k8s_view(server), 'view_update')
    return dict(project='homelab', name='k8s', hidden=True)


def view_delete(server):
    server.route('DELETE', k8s_view(server), 'view_delete')
    return dict(project='homelab', name='k8s', state='absent')


# -- variable_group -------------------------------------------------------------

def variable_group_create(server):
    base = homelab(server)
    server.route('GET', base + '/environment', 'variable_groups_empty')
    server.route('POST', base + '/environment', 'variable_group_create')
    return dict(project='homelab', name='harbor', json=dict(harbor_url='https://harbor.example.com'), env=dict(TZ='UTC'),
                secrets=[dict(name='TOKEN', type='env', value='tok-1'), dict(name='db_pw', type='var', value='pw-1')])


def stored_variable_group(server):
    base = homelab(server)
    path = '%s/environment/%d' % (base, fid(server, 'variable_group_create'))
    server.route('GET', base + '/environment', 'variable_groups_one')
    server.route('GET', path, 'variable_group_get')
    return path


def variable_group_update(server):
    server.route('PUT', stored_variable_group(server), 'variable_group_update')
    return dict(project='homelab', name='harbor', env=dict(TZ='Europe/Oslo'))


def variable_group_delete(server):
    path = stored_variable_group(server)
    server.route('GET', path + '/refs', 'variable_group_refs_unused')
    server.route('DELETE', path, 'variable_group_delete')
    return dict(project='homelab', name='harbor', state='absent')


# -- template -------------------------------------------------------------------

def template_routes(server, listing):
    base = homelab(server)
    server.route('GET', base + '/repositories', 'repositories_one')
    server.route('GET', base + '/inventory', 'inventories_one')
    server.route('GET', base + '/environment', 'variable_groups_for_templates')
    server.route('GET', base + '/views', 'views_two')
    server.route('GET', base + '/keys', 'keys_with_deploy')
    server.route('GET', base + '/templates', listing)
    path = '%s/templates/%d' % (base, fid(server, 'template_create'))
    server.route('GET', path, 'template_get')
    return base, path


def template_create(server):
    base, dummy = template_routes(server, 'templates_empty')
    server.route('POST', base + '/templates', 'template_create')
    return dict(project='homelab', name='site', playbook='site.yml', repository='ansible', inventory='homelab',
                variable_groups=['empty'], view='k8s', arguments=['-v'], task_params=dict(limit=['web']),
                survey_vars=[dict(name='host', title='Host')], vaults=[dict(key='deploy')])


def template_update(server):
    dummy, path = template_routes(server, 'templates_one')
    server.route('PUT', path, 'template_update')
    return dict(project='homelab', name='site', description='updated')


def template_delete(server):
    dummy, path = template_routes(server, 'templates_one')
    server.route('GET', path + '/refs', 'template_refs_unused')
    server.route('DELETE', path, 'template_delete')
    return dict(project='homelab', name='site', state='absent')


# -- schedule -------------------------------------------------------------------

def schedule_routes(server, listing):
    base = homelab(server)
    server.route('GET', base + '/templates', 'templates_one')
    server.route('GET', base + '/repositories', 'repositories_one')
    server.route('GET', base + '/schedules', listing)
    server.route('GET', '%s/templates/%d/schedules' % (base, fid(server, 'template_create')), 'schedules_empty')
    path = '%s/schedules/%d' % (base, fid(server, 'schedule_create'))
    server.route('GET', path, single(server, 'schedule_get'))
    return base, path


def schedule_create(server):
    base, dummy = schedule_routes(server, 'schedules_empty')
    server.route('POST', base + '/schedules', 'schedule_create')
    return dict(project='homelab', name='nightly', template='site', cron='0 3 * * *')


def schedule_update(server):
    dummy, path = schedule_routes(server, 'schedules_project_list')
    server.route('PUT', path, 'schedule_update')
    return dict(project='homelab', name='nightly', active=False)


def schedule_delete(server):
    dummy, path = schedule_routes(server, 'schedules_project_list')
    server.route('DELETE', path, 'schedule_delete')
    return dict(project='homelab', name='nightly', state='absent')


# -- integration ----------------------------------------------------------------

def integration_routes(server, listing):
    base = homelab(server)
    server.route('GET', base + '/templates', 'templates_one')
    server.route('GET', base + '/keys', 'keys_with_deploy')
    server.route('GET', base + '/integrations', listing)
    path = '%s/integrations/%d' % (base, fid(server, 'integration_create'))
    server.route('GET', path, 'integration_get')
    server.route('GET', path + '/matchers', 'integration_matchers_one')
    server.route('GET', path + '/values', 'integration_values_one')
    server.route('GET', path + '/aliases', 'integration_aliases_one')
    return base, path


def integration_create(server):
    base, path = integration_routes(server, 'integrations_empty')
    server.route('POST', base + '/integrations', 'integration_create')
    server.route('POST', path + '/matchers', 'integration_matcher_create')
    server.route('POST', path + '/values', 'integration_value_create')
    server.route('POST', path + '/aliases', 'integration_alias_create')
    return dict(project='homelab', name='gh', template='site', auth_method='token', auth_key='deploy',
                auth_header='X-Token', matchers=[dict(name='main', key='ref', value='refs/heads/main')],
                extract_values=[dict(name='sha', key='after', variable='COMMIT_SHA')])


def integration_update(server):
    dummy, path = integration_routes(server, 'integrations_one')
    server.route('PUT', path, 'integration_update')
    return dict(project='homelab', name='gh', searchable=True)


def integration_delete(server):
    dummy, path = integration_routes(server, 'integrations_one')
    server.route('GET', path + '/refs', 'integration_refs_unused')
    server.route('DELETE', path, 'integration_delete')
    return dict(project='homelab', name='gh', state='absent')


# -- team_member ----------------------------------------------------------------

def team_routes(server, listing):
    server.route('GET', '/projects', 'team_projects_list')
    server.route('GET', '/user', 'team_user_current')
    server.route('GET', '/users?s=tm-fixture-a', 'team_users_search')
    pid = [p for p in server.fixtures['team_projects_list']['body'] if p['name'] == TEAM_PROJECT][0]['id']
    uid = [u for u in server.fixtures['team_users_search']['body'] if u['username'] == 'tm-fixture-a'][0]['id']
    base = '/project/%d/users' % pid
    server.route('GET', base, listing)
    return base, '%s/%d' % (base, uid)


def team_member_create(server):
    base, dummy = team_routes(server, 'team_members_initial')
    server.route('POST', base, 'team_member_add')
    return dict(project=TEAM_PROJECT, user='tm-fixture-a', role='manager')


def team_member_update(server):
    dummy, path = team_routes(server, 'team_members_two')
    server.route('PUT', path, 'team_member_update')
    return dict(project=TEAM_PROJECT, user='tm-fixture-a', role='owner')


def team_member_delete(server):
    dummy, path = team_routes(server, 'team_members_two')
    server.route('DELETE', path, 'team_member_remove')
    return dict(project=TEAM_PROJECT, user='tm-fixture-a', state='absent')


# -- user -----------------------------------------------------------------------

def user_routes(server, without=None):
    listing = server.response('user_list')
    listing['body'] = [u for u in listing['body'] if u['id'] != without]
    server.route('GET', '/user', 'user_me')
    server.route('GET', '/users', listing)
    return server.fixtures['user_create']['body']


def user_create(server):
    new = user_routes(server, without=fid(server, 'user_create'))
    server.route('POST', '/users', 'user_create')
    return dict(login=new['username'], name='Fixture', email=new['email'], user_password='pw-unit-1')


def user_update(server):
    stored = user_routes(server)
    server.route('PUT', '/users/%d' % stored['id'], 'user_update')
    return dict(login=stored['username'], name='Fixture Team', alert=True)


def user_password(server):
    stored = user_routes(server)
    server.route('POST', '/users/%d/password' % stored['id'], 'user_password')
    return dict(login=stored['username'], user_password='pw-unit-2')


def user_delete(server):
    stored = user_routes(server)
    server.route('DELETE', '/users/%d' % stored['id'], 'user_delete')
    return dict(login=stored['username'], state='absent')


# -- runner ---------------------------------------------------------------------

def runner_routes(server, registered=False, listed=True):
    listing = server.response('runner_list_one')
    listing['body'][0]['registered'] = registered
    if not listed:
        listing['body'] = []
    server.route('GET', '/runners', listing)
    return '/runners/%d' % fid(server, 'runner_create')


def runner_create(server):
    path = runner_routes(server, listed=False)
    server.route('POST', '/runners', 'runner_create')
    server.route('POST', path + '/registration-token', 'runner_registration_token')
    return dict(name='rn-fixture', max_parallel_tasks=2, tags=['b', 'a'])


def runner_update(server):
    server.route('PUT', runner_routes(server), 'runner_update')
    return dict(name='rn-fixture', webhook='https://hooks.example.com/r')


def runner_regenerate(server):
    # No registered runner was recorded: this is the recorded one with the flag set.
    server.route('POST', runner_routes(server, registered=True) + '/registration-token', 'runner_registration_token')
    return dict(name='rn-fixture', regenerate_token=True)


def runner_delete(server):
    server.route('DELETE', runner_routes(server), 'runner_delete')
    return dict(name='rn-fixture', state='absent')


# -- the _info modules ----------------------------------------------------------

def no_options(server):
    return {}


def integration_list(server):
    integration_routes(server, 'integrations_one')
    return dict(project='homelab')


def inventory_list(server):
    inventory_routes(server, 'inventories_one')
    return dict(project='homelab')


def key_list(server):
    base = homelab(server)
    server.route('GET', base + '/keys', 'keys_with_deploy')
    server.route('GET', base + '/repositories', 'repositories_one')
    return dict(project='homelab')


def project_list(server):
    server.route('GET', '/projects', 'projects_one')
    return {}


def repository_list(server):
    repository_routes(server, 'repositories_one')
    return dict(project='homelab')


def runner_list(server):
    runner_routes(server)
    return {}


def schedule_list(server):
    schedule_routes(server, 'schedules_project_list')
    return dict(project='homelab')


def team_member_list(server):
    team_routes(server, 'team_members_two')
    return dict(project=TEAM_PROJECT)


def template_list(server):
    template_routes(server, 'templates_one')
    return dict(project='homelab')


def user_list(server):
    user_routes(server)
    return {}


def variable_group_list(server):
    stored_variable_group(server)
    return dict(project='homelab')


def view_list(server):
    k8s_view(server)
    return dict(project='homelab')


def module_name(module):
    return module.__name__.rsplit('.', 1)[-1]


# module, the result key of its object, operation, setup, and what the diff shows:
# for an update (field, before, after), for a delete (field, value) of what is deleted.
OPERATIONS = [
    (integration, 'integration', 'create', integration_create, None),
    (integration, 'integration', 'update', integration_update, ('searchable', False, True)),
    (integration, 'integration', 'delete', integration_delete, ('name', 'gh')),
    (inventory, 'inventory', 'create', inventory_create, None),
    (inventory, 'inventory', 'update', inventory_update, ('become_key', None, 'deploy')),
    (inventory, 'inventory', 'delete', inventory_delete, ('name', 'homelab')),
    (key_store, 'key', 'create', key_create, None),
    (key_store, 'key', 'update', key_update, ('type', 'ssh', 'login_password')),
    (key_store, 'key', 'delete', key_delete, ('name', 'deploy')),
    (project, 'project', 'create', project_create, None),
    (project, 'project', 'update', project_update, ('alert', False, True)),
    (project, 'project', 'delete', project_delete, ('name', 'homelab')),
    (repository, 'repository', 'create', repository_create, None),
    (repository, 'repository', 'update', repository_update, ('git_branch', 'main', 'develop')),
    (repository, 'repository', 'delete', repository_delete, ('name', 'ansible')),
    (runner, 'runner', 'create', runner_create, None),
    (runner, 'runner', 'update', runner_update, ('webhook', '', 'https://hooks.example.com/r')),
    (runner, 'runner', 'regenerate', runner_regenerate, ('registered', True, False)),
    (runner, 'runner', 'delete', runner_delete, ('name', 'rn-fixture')),
    (schedule, 'schedule', 'create', schedule_create, None),
    (schedule, 'schedule', 'update', schedule_update, ('active', True, False)),
    (schedule, 'schedule', 'delete', schedule_delete, ('name', 'nightly')),
    (team_member, 'member', 'create', team_member_create, None),
    (team_member, 'member', 'update', team_member_update, ('role', 'manager', 'owner')),
    (team_member, 'member', 'delete', team_member_delete, ('username', 'tm-fixture-a')),
    (template, 'template', 'create', template_create, None),
    (template, 'template', 'update', template_update, ('description', '', 'updated')),
    (template, 'template', 'delete', template_delete, ('name', 'site')),
    (user, 'user', 'create', user_create, None),
    (user, 'user', 'update', user_update, ('name', 'Fixture', 'Fixture Team')),
    # Only the password is written, and a password is in no diff.
    (user, 'user', 'password', user_password, None),
    (user, 'user', 'delete', user_delete, ('name', 'Fixture')),
    (variable_group, 'variable_group', 'create', variable_group_create, None),
    (variable_group, 'variable_group', 'update', variable_group_update, ('env', dict(TZ='UTC'), dict(TZ='Europe/Oslo'))),
    (variable_group, 'variable_group', 'delete', variable_group_delete, ('name', 'harbor')),
    (view, 'view', 'create', view_create, None),
    (view, 'view', 'update', view_update, ('hidden', False, True)),
    (view, 'view', 'delete', view_delete, ('name', 'k8s')),
]
OPERATION_IDS = ['%s-%s' % (module_name(o[0]), o[2]) for o in OPERATIONS]

INFO_MODULES = [
    (info, no_options),
    (integration_info, integration_list),
    (inventory_info, inventory_list),
    (key_store_info, key_list),
    (project_info, project_list),
    (repository_info, repository_list),
    (runner_info, runner_list),
    (schedule_info, schedule_list),
    (team_member_info, team_member_list),
    (template_info, template_list),
    (user_info, user_list),
    (variable_group_info, variable_group_list),
    (view_info, view_list),
]
INFO_IDS = [module_name(m) for m, dummy in INFO_MODULES]

# What only the server can tell, so check mode reports it empty: the id of a
# new object, a runner's registration token, a new integration's webhook URL.
SERVER_ASSIGNED = {
    ('runner', 'create'): 'registration_token',
    ('runner', 'regenerate'): 'registration_token',
    ('integration', 'create'): 'webhook_urls',
}

# In every result, whatever the module.
STANDARD_KEYS = set(['changed', 'diff', 'invocation', 'warnings', 'deprecations'])


def writes(server):
    return [r for r in server.requests if r['method'] != 'GET' and not r['path'].startswith('/auth/')]


def drop_write_routes(server):
    """Leave the server with its reads and the login only, and forget what was asked so far."""
    for method, path in list(server.routes):
        if method != 'GET' and not path.startswith('/auth/'):
            del server.routes[(method, path)]
    del server.requests[:]


def real_then_checked(server, run_module, module, setup):
    """The result of a real run, and of the same task in check mode on a server that takes no write."""
    args = setup(server)
    real = run_module(module.main, args)
    assert real.get('failed') is not True, real.get('msg')
    assert writes(server) != []
    drop_write_routes(server)
    checked = run_module(module.main, args, check_mode=True)
    return real, checked


def without_id(obj):
    return dict((k, v) for k, v in obj.items() if k != 'id')


def predictable(result, key, operation, assigned):
    """A result without what only the server can tell."""
    # Warnings pile up across module runs in one process, so they are left out here.
    out = dict((k, v) for k, v in result.items() if k not in ('invocation', 'warnings', 'deprecations', assigned))
    if operation == 'create':
        out[key] = without_id(out[key])
        out['diff'] = dict(out['diff'], after=without_id(out['diff']['after']))
    return out


@pytest.mark.parametrize('module, key, operation, setup, shown', OPERATIONS, ids=OPERATION_IDS)
def test_check_mode_sends_no_write(server, run_module, module, key, operation, setup, shown):
    dummy, checked = real_then_checked(server, run_module, module, setup)
    # A write would have met a server without that route and failed the task.
    assert checked.get('failed') is not True, checked.get('msg')
    assert checked['changed'] is True
    assert writes(server) == []
    assert [r['path'] for r in server.requests if r['method'] != 'GET'] == ['/auth/login', '/auth/logout']


def with_known_gaps(operations):
    """The operations table, with the ones check mode is known to predict wrongly marked."""
    out = []
    for operation in operations:
        marks = []
        if (module_name(operation[0]), operation[2]) == ('template', 'create'):
            marks.append(pytest.mark.xfail(strict=True, reason=(
                'template: a create in check mode returns name: null in template and diff.after, where a real run '
                'returns the name. The predicted view is built without the name option.')))
        out.append(pytest.param(*operation, marks=marks))
    return out


@pytest.mark.parametrize('module, key, operation, setup, shown', with_known_gaps(OPERATIONS), ids=OPERATION_IDS)
def test_check_mode_reports_what_a_real_run_reports(server, run_module, module, key, operation, setup, shown):
    real, checked = real_then_checked(server, run_module, module, setup)
    assigned = SERVER_ASSIGNED.get((module_name(module), operation))
    assert predictable(checked, key, operation, assigned) == predictable(real, key, operation, assigned)
    if operation == 'create' and 'id' in real[key]:
        assert real[key]['id'] and 'id' not in checked[key]
    if assigned:
        assert real[assigned] and not checked[assigned]


@pytest.mark.parametrize('check_mode', [False, True], ids=['real', 'check'])
@pytest.mark.parametrize('module, key, operation, setup, shown', OPERATIONS, ids=OPERATION_IDS)
def test_diff_shows_the_change(server, run_module, module, key, operation, setup, shown, check_mode):
    result = run_module(module.main, setup(server), check_mode=check_mode)
    assert result['changed'] is True
    before, after = result['diff']['before'], result['diff']['after']
    if operation == 'create':
        assert before == {}
        assert after == result[key] and after
    elif operation == 'delete':
        field, value = shown
        assert before[field] == value
        assert after == {} and result[key] == {}
    elif shown is None:
        assert before == after == result[key]
    else:
        field, old, new = shown
        assert (before[field], after[field]) == (old, new)
        assert after == result[key]
        assert sorted(before) == sorted(after)


def documented(module):
    return set(yaml.safe_load(module.RETURN))


@pytest.mark.parametrize('check_mode', [False, True], ids=['real', 'check'])
@pytest.mark.parametrize('module, key, operation, setup, shown', OPERATIONS, ids=OPERATION_IDS)
def test_result_has_the_documented_keys(server, run_module, module, key, operation, setup, shown, check_mode):
    result = run_module(module.main, setup(server), check_mode=check_mode)
    assert set(result) - STANDARD_KEYS == documented(module)
    assert key in documented(module)


@pytest.mark.parametrize('module, setup', INFO_MODULES, ids=INFO_IDS)
def test_info_result_has_the_documented_keys(server, run_module, module, setup):
    result = run_module(module.main, setup(server))
    assert result['changed'] is False
    assert set(result) - STANDARD_KEYS == documented(module)
    assert all(result[k] for k in documented(module)), 'the scenario should return something for every key'


@pytest.mark.parametrize('module, setup', INFO_MODULES, ids=INFO_IDS)
def test_info_is_the_same_in_check_mode(server, run_module, module, setup):
    args = setup(server)
    real = run_module(module.main, args)
    del server.requests[:]
    checked = run_module(module.main, args, check_mode=True)
    assert checked.get('failed') is not True, checked.get('msg')
    assert returned(checked) == returned(real)
    assert writes(server) == []


def returned(result):
    return dict((k, v) for k, v in result.items() if k not in ('invocation', 'warnings', 'deprecations'))
