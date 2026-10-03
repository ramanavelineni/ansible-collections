# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""One project built up module by module on a real server, then taken down again.

The tests run in the order they are written and build on each other: each
leaves its object for the next. What the unit tests cannot show is shown here:
that the server accepts what a module sends, and that a second run with the
same options changes nothing.
"""

import pytest

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

PROJECT = 'live-chain'
# Not a usable key; Semaphore stores what it is given.
PRIVATE_KEY = '-----BEGIN OPENSSH PRIVATE KEY-----\nlive-test\n-----END OPENSSH PRIVATE KEY-----'


def named(listing, name, field='name'):
    return [item for item in listing if item.get(field) == name]


def without(obj, *keys):
    return dict((k, v) for k, v in obj.items() if k not in keys)


def lifecycle(sem, module, info_module, key, info_key, create, update, scope=None, name_field='name', field=None,
              predicted_differs=(), create_differs=(), info_only=(), volatile=()):
    """Create and update one object, checking each step against the server.

    `create` and `update` are the options of the two tasks; `scope` is what
    the _info module takes (the project). `predicted_differs` names the fields
    of the returned object that only the server can tell, which check mode
    cannot predict; `create_differs` those it gets wrong for a create (see the
    xfail tests); `info_only` those the _info module adds to each object;
    `volatile` those the server changes by itself. `name_field` is the option
    that names the object and `field` the field it is returned in.
    """
    scope = scope if scope is not None else dict(project=PROJECT)
    field = field or name_field

    def clean(obj):
        return without(obj, *volatile)

    def stored():
        listing = sem.ok(info_module, **scope)[info_key]
        return [without(obj, *(tuple(info_only) + tuple(volatile))) for obj in named(listing, create[name_field], field)]

    # Check mode predicts the create and creates nothing.
    predicted = sem.ok(module, check_mode=True, **create)
    assert predicted['changed'] is True
    assert stored() == []

    created = sem.ok(module, **create)
    assert created['changed'] is True
    differs = ('id',) + tuple(predicted_differs) + tuple(create_differs) + tuple(volatile)
    assert without(predicted[key], *differs) == without(created[key], *differs)
    assert created['diff']['before'] == {}

    # The same task again changes nothing: the server stored what was sent.
    again = sem.ok(module, **create)
    assert again['changed'] is False, 'second run changed: %s' % again.get('diff')
    assert clean(again[key]) == clean(created[key])

    # The _info module returns the object in the same shape.
    assert stored() == [clean(created[key])]

    # Check mode predicts the update and leaves the object alone.
    predicted = sem.ok(module, check_mode=True, **update)
    assert predicted['changed'] is True
    assert stored() == [clean(created[key])]

    updated = sem.ok(module, **update)
    assert updated['changed'] is True
    differs = tuple(predicted_differs) + tuple(volatile)
    assert without(predicted[key], *differs) == without(updated[key], *differs)
    assert updated['diff'] == predicted['diff']

    again = sem.ok(module, **update)
    assert again['changed'] is False, 'second run changed: %s' % again.get('diff')
    assert stored() == [clean(updated[key])]
    return updated


def removal(sem, module, info_module, info_key, options, scope=None, name_field='name', field=None, volatile=()):
    """Delete one object: predicted, done, and a no-op the second time."""
    scope = scope if scope is not None else dict(project=PROJECT)
    lookup = options[name_field]
    options = dict(options, state='absent')

    def stored():
        return [without(obj, *volatile) for obj in named(sem.ok(info_module, **scope)[info_key], lookup, field or name_field)]

    before = stored()
    assert len(before) == 1

    predicted = sem.ok(module, check_mode=True, **options)
    assert predicted['changed'] is True
    assert stored() == before

    deleted = sem.ok(module, **options)
    assert deleted['changed'] is True
    assert without(deleted['diff']['before'], *volatile) == without(predicted['diff']['before'], *volatile)
    assert deleted['diff']['after'] == {}
    assert stored() == []

    again = sem.ok(module, **options)
    assert again['changed'] is False


# -- building up ------------------------------------------------------------------

def test_project(sem):
    updated = lifecycle(
        sem, project, project_info, 'project', 'projects',
        create=dict(name=PROJECT),
        update=dict(name=PROJECT, max_parallel_tasks=2),
        scope={}, predicted_differs=('created',))
    assert updated['project']['max_parallel_tasks'] == 2


def test_key_store(sem):
    lifecycle(
        sem, key_store, key_store_info, 'key', 'key_store',
        create=dict(project=PROJECT, name='live-key', type='ssh', update_secret='on_create',
                    ssh=dict(login='git', private_key=PRIVATE_KEY)),
        update=dict(project=PROJECT, name='live-key', type='login_password', update_secret='on_create',
                    login_password=dict(login='deploy', password='live-pw-1')),
        info_only=('repositories',))
    # A second key, kept as an SSH key, for the repository and the inventory.
    created = sem.ok(key_store, project=PROJECT, name='live-ssh', type='ssh', update_secret='on_create',
                     ssh=dict(login='git', private_key=PRIVATE_KEY))
    assert created['changed'] is True and created['secret_updated'] is True
    # The API never returns a secret, so with update_secret=always every run sends it again.
    resent = sem.ok(key_store, project=PROJECT, name='live-ssh', type='ssh', ssh=dict(login='git', private_key=PRIVATE_KEY))
    assert resent['changed'] is True and resent['secret_updated'] is True
    assert PRIVATE_KEY not in repr(resent)
    assert 'live-test' not in repr(resent)


def test_repository(sem):
    lifecycle(
        sem, repository, repository_info, 'repository', 'repositories',
        create=dict(project=PROJECT, name='live-repo', git_url='git@github.com:example/live.git', git_branch='main',
                    ssh_key='live-ssh'),
        update=dict(project=PROJECT, name='live-repo', git_branch='develop'))


def test_inventory(sem):
    lifecycle(
        sem, inventory, inventory_info, 'inventory', 'inventories',
        create=dict(project=PROJECT, name='live-inventory', type='static', inventory='localhost ansible_connection=local',
                    ssh_key='live-ssh'),
        update=dict(project=PROJECT, name='live-inventory', become_key='live-key'))
    # An inventory that is a file in a repository.
    created = sem.ok(inventory, project=PROJECT, name='live-inventory-file', type='file', inventory='inventories/hosts',
                     repository='live-repo', ssh_key='live-ssh')
    assert created['changed'] is True
    assert created['inventory']['repository'] == 'live-repo'
    assert sem.ok(inventory, project=PROJECT, name='live-inventory-file', type='file', inventory='inventories/hosts',
                  repository='live-repo', ssh_key='live-ssh')['changed'] is False


def test_variable_group(sem):
    secrets = [dict(name='TOKEN', type='env', value='live-tok-1'), dict(name='db_pw', type='var', value='live-pw-1')]
    updated = lifecycle(
        sem, variable_group, variable_group_info, 'variable_group', 'variable_groups',
        create=dict(project=PROJECT, name='live-vars', json=dict(region='eu', replicas=2), env=dict(TZ='UTC'),
                    secrets=secrets, update_secret='on_create'),
        update=dict(project=PROJECT, name='live-vars', env=dict(TZ='Europe/Oslo'), update_secret='on_create'))
    assert updated['variable_group']['json'] == dict(region='eu', replicas=2)
    assert 'live-tok-1' not in repr(updated) and 'live-pw-1' not in repr(updated)
    # Secrets stay when they are not named; purge_secrets takes away the ones that are not declared.
    purged = sem.ok(variable_group, project=PROJECT, name='live-vars', purge_secrets=True, update_secret='on_create',
                    secrets=[dict(name='TOKEN', type='env', value='live-tok-1')])
    assert purged['changed'] is True
    assert [s['name'] for s in purged['variable_group']['secrets']] == ['TOKEN']


def test_view(sem):
    lifecycle(
        sem, view, view_info, 'view', 'views',
        create=dict(project=PROJECT, name='live-view'),
        update=dict(project=PROJECT, name='live-view', position=3))


def template_options(sem):
    survey = [dict(name='host', title='Host'),
              dict(name='mode', title='Mode', type='enum', required=True,
                   values=[dict(name='Dry run', value='check'), dict(name='Apply', value='apply')])]
    if sem.at_least(19):
        survey.append(dict(name='notes', title='Notes', type='text'))
    return dict(project=PROJECT, name='live-site', playbook='site.yml', repository='live-repo', inventory='live-inventory',
                variable_groups=['live-vars'], view='live-view', arguments=['-v'], task_params=dict(limit=['web']),
                survey_vars=survey, vaults=[dict(key='live-key')], allow_override_args_in_task=True)


def test_template(sem):
    updated = lifecycle(
        sem, template, template_info, 'template', 'templates',
        create=template_options(sem),
        update=dict(project=PROJECT, name='live-site', description='updated by the live tests'),
        create_differs=('name',))
    assert updated['template']['arguments'] == ['-v']
    assert updated['template']['variable_groups'] == ['live-vars']
    # The whole declaration again, after the update, is still no change.
    assert sem.ok(template, **template_options(sem))['changed'] is False


def test_template_create_in_check_mode_names_the_template(sem):
    options = dict(project=PROJECT, name='live-predicted', playbook='site.yml', repository='live-repo',
                   inventory='live-inventory', variable_groups=['live-vars'])
    predicted = sem.ok(template, check_mode=True, **options)
    assert predicted['template']['name'] == 'live-predicted'
    assert predicted['diff']['after']['name'] == 'live-predicted'


def test_template_build_and_deploy(sem):
    """start_version and build_template are stored for the types that take them, and refused for the others."""
    base = dict(project=PROJECT, playbook='build.yml', repository='live-repo', inventory='live-inventory',
                variable_groups=['live-vars'])
    build = dict(base, name='live-build', type='build', start_version='1.0.0')
    assert sem.ok(template, **build)['changed'] is True
    assert sem.ok(template, **build)['changed'] is False
    deploy = dict(base, name='live-deploy', type='deploy', build_template='live-build', autorun=True)
    created = sem.ok(template, **deploy)
    assert created['changed'] is True
    assert created['template']['build_template'] == 'live-build'
    assert sem.ok(template, **deploy)['changed'] is False
    refused = sem.run(template, project=PROJECT, name='live-site', start_version='2.0.0')
    assert refused['failed'] is True
    assert 'start_version' in refused['msg']
    for name in ('live-deploy', 'live-build'):
        assert sem.ok(template, project=PROJECT, name=name, state='absent')['changed'] is True


def test_schedule(sem):
    lifecycle(
        sem, schedule, schedule_info, 'schedule', 'schedules',
        create=dict(project=PROJECT, name='live-nightly', template='live-site', cron='0 3 * * *'),
        update=dict(project=PROJECT, name='live-nightly', active=False))


def test_schedule_run_at(sem):
    """A run-at schedule: the time is sent in UTC and compares equal however it is written."""
    options = dict(project=PROJECT, name='live-once', template='live-site', run_at='2099-01-01T05:00:00+02:00')
    created = sem.ok(schedule, **options)
    assert created['changed'] is True
    assert sem.ok(schedule, **options)['changed'] is False
    assert sem.ok(schedule, **dict(options, run_at='2099-01-01T03:00:00Z'))['changed'] is False
    assert sem.ok(schedule, **dict(options, run_at='2099-01-01 03:00:00+00:00'))['changed'] is False
    assert sem.ok(schedule, project=PROJECT, name='live-once', state='absent')['changed'] is True


def test_schedule_commit_poller(sem):
    """A schedule that watches a repository lives in the template's own list."""
    options = dict(project=PROJECT, name='live-poll', template='live-site', cron='*/5 * * * *', repository='live-repo')
    assert sem.ok(schedule, **options)['changed'] is True
    assert sem.ok(schedule, **options)['changed'] is False
    assert named(sem.ok(schedule_info, project=PROJECT)['schedules'], 'live-poll')[0]['repository'] == 'live-repo'
    assert sem.ok(schedule, project=PROJECT, name='live-poll', state='absent')['changed'] is True
    assert sem.ok(schedule, project=PROJECT, name='live-poll', state='absent')['changed'] is False


def test_integration(sem):
    updated = lifecycle(
        sem, integration, integration_info, 'integration', 'integrations',
        create=dict(project=PROJECT, name='live-hook', template='live-site', auth_method='token', auth_key='live-key',
                    auth_header='X-Token', matchers=[dict(name='main', key='ref', value='refs/heads/main')],
                    extract_values=[dict(name='sha', key='after', variable='COMMIT_SHA')]),
        update=dict(project=PROJECT, name='live-hook', searchable=True),
        info_only=('webhook_urls',))
    assert [m['name'] for m in updated['integration']['matchers']] == ['main']
    assert updated['webhook_urls']
    # A matcher and a value changed in place, found by their names.
    options = dict(project=PROJECT, name='live-hook',
                   matchers=[dict(name='main', key='ref', value='refs/tags/', method='contains')],
                   extract_values=[dict(name='sha', key='head_commit.id', variable='COMMIT_SHA')])
    changed = sem.ok(integration, **options)
    assert changed['changed'] is True
    assert changed['integration']['matchers'][0]['method'] == 'contains'
    assert changed['integration']['extract_values'][0]['key'] == 'head_commit.id'
    assert sem.ok(integration, **options)['changed'] is False
    # One more of each, added next to the ones that are there.
    options['matchers'].append(dict(name='pusher', key='pusher.name', value='ci'))
    options['extract_values'].append(dict(name='ref', key='ref', variable='GIT_REF'))
    assert sem.ok(integration, **options)['changed'] is True
    assert sem.ok(integration, **options)['changed'] is False


@pytest.mark.xfail(strict=True, reason='Semaphore 2.18.30 and 2.19.12 answer 204 to DELETE .../integrations/<id>/matchers/<id> and '
                                       '.../values/<id> and delete nothing. integration reports the removal as done, returns the '
                                       'object without the undeclared entries, and reports a change again on every run')
def test_integration_removes_undeclared_matchers_and_values(sem):
    options = dict(project=PROJECT, name='live-hook', extract_values=[],
                   matchers=[dict(name='main', key='ref', value='refs/tags/', method='contains')])
    assert sem.ok(integration, **options)['changed'] is True
    stored = named(sem.ok(integration_info, project=PROJECT)['integrations'], 'live-hook')[0]
    assert [m['name'] for m in stored['matchers']] == ['main']
    assert stored['extract_values'] == []
    assert sem.ok(integration, **options)['changed'] is False


def test_runner(sem):
    updated = lifecycle(
        sem, runner, runner_info, 'runner', 'runners',
        create=dict(name='live-runner', max_parallel_tasks=2, tags=['b', 'a']),
        update=dict(name='live-runner', webhook='https://hooks.example.com/live'),
        scope={}, volatile=('status',))
    assert sorted(updated['runner']['tags']) == ['a', 'b']
    # A new token on request, and none without one.
    assert sem.ok(runner, name='live-runner')['registration_token'] == ''
    fresh = sem.ok(runner, name='live-runner', regenerate_token=True)
    assert fresh['changed'] is True
    assert fresh['registration_token']


def test_user_and_team_member(sem):
    lifecycle(
        sem, user, user_info, 'user', 'users',
        create=dict(login='live-user', name='Live Test', email='live-user@example.com', user_password='live-user-pw-1',
                    update_secret='on_create'),
        update=dict(login='live-user', name='Live Test User', alert=True, update_secret='on_create'),
        scope={}, name_field='login', field='username', predicted_differs=('created',))
    changed = sem.ok(user, login='live-user', user_password='live-user-pw-2')
    assert changed['changed'] is True and changed['password_updated'] is True
    assert 'live-user-pw-2' not in repr(changed)

    lifecycle(
        sem, team_member, team_member_info, 'member', 'members',
        create=dict(project=PROJECT, user='live-user', role='manager'),
        update=dict(project=PROJECT, user='live-user', role='task_runner'),
        name_field='user', field='username')


# -- other ways to name the project ------------------------------------------------

def test_project_id(sem):
    """project_id reaches the same project without the project list."""
    pid = named(sem.ok(project_info)['projects'], PROJECT)[0]['id']
    by_name = sem.ok(repository_info, project=PROJECT)
    by_id = sem.ok(repository_info, project_id=pid)
    assert by_id['repositories'] == by_name['repositories']
    assert sem.ok(view, project_id=pid, name='live-view', position=3)['changed'] is False
    created = sem.ok(view, project_id=pid, name='live-view-by-id')
    assert created['changed'] is True
    assert named(sem.ok(view_info, project=PROJECT)['views'], 'live-view-by-id') == [created['view']]
    assert sem.ok(view, project_id=pid, name='live-view-by-id', state='absent')['changed'] is True
    # An id no project has: a failure for a read, a no-op for a removal.
    missing = sem.run(repository_info, project_id=pid + 100000)
    assert missing['failed'] is True
    assert sem.ok(view, project_id=pid + 100000, name='live-view', state='absent')['changed'] is False
    both = sem.run(repository_info, project=PROJECT, project_id=pid)
    assert both['failed'] is True and 'mutually exclusive' in both['msg']


def test_survey_variable_target_survives(sem):
    """A field the module has no option for is kept by an update of something else (2.19 stores `target`)."""
    if not sem.at_least(19):
        pytest.skip('Semaphore 2.18 does not store a survey variable target')
    pid = named(sem.ok(project_info)['projects'], PROJECT)[0]['id']
    tid = named(sem.ok(template_info, project=PROJECT)['templates'], 'live-site')[0]['id']
    path = '/project/%d/templates/%d' % (pid, tid)
    stored = sem.api.get(path)
    stored['survey_vars'][0]['target'] = 'env'
    status, dummy = sem.api.call('PUT', path, stored)
    assert status == 204
    assert sem.api.get(path)['survey_vars'][0].get('target') == 'env'

    assert sem.ok(template, project=PROJECT, name='live-site', description='target kept')['changed'] is True
    assert sem.api.get(path)['survey_vars'][0].get('target') == 'env'
    # Also when the survey variables themselves change: a variable that keeps its name keeps the field.
    options = template_options(sem)
    options['survey_vars'][0]['title'] = 'Host name'
    assert sem.ok(template, **options)['changed'] is True
    after = sem.api.get(path)['survey_vars'][0]
    assert after['title'] == 'Host name'
    assert after.get('target') == 'env'
    assert sem.ok(template, **options)['changed'] is False


def test_custom_app(sem):
    """A template for an app registered on the server, if there is one. The suite registers none."""
    builtin = set(('ansible', 'terraform', 'tofu', 'terragrunt', 'bash', 'powershell', 'python', 'pulumi'))
    custom = [app['id'] for app in sem.ok(info)['apps'] if app['id'] not in builtin]
    unknown = sem.run(template, project=PROJECT, name='live-app', app='live-no-such-app', playbook='run.sh',
                      repository='live-repo', inventory='live-inventory', variable_groups=['live-vars'])
    assert unknown['failed'] is True
    assert 'live-no-such-app' in unknown['msg']
    if not custom:
        pytest.skip('no custom app is registered on this server')
    options = dict(project=PROJECT, name='live-app', app=custom[0], playbook='run.sh', repository='live-repo',
                   inventory='live-inventory', variable_groups=['live-vars'])
    assert sem.ok(template, **options)['changed'] is True
    assert sem.ok(template, **options)['changed'] is False
    assert sem.ok(template, project=PROJECT, name='live-app', state='absent')['changed'] is True


# -- taking it down ----------------------------------------------------------------

def test_removal(sem):
    removal(sem, team_member, team_member_info, 'members', dict(project=PROJECT, user='live-user'), name_field='user',
            field='username')
    removal(sem, user, user_info, 'users', dict(login='live-user'), scope={}, name_field='login', field='username')
    removal(sem, runner, runner_info, 'runners', dict(name='live-runner'), scope={}, volatile=('status',))
    removal(sem, integration, integration_info, 'integrations', dict(project=PROJECT, name='live-hook'))
    removal(sem, schedule, schedule_info, 'schedules', dict(project=PROJECT, name='live-nightly'))
    removal(sem, template, template_info, 'templates', dict(project=PROJECT, name='live-site'))
    removal(sem, view, view_info, 'views', dict(project=PROJECT, name='live-view'))
    removal(sem, variable_group, variable_group_info, 'variable_groups', dict(project=PROJECT, name='live-vars'))
    removal(sem, inventory, inventory_info, 'inventories', dict(project=PROJECT, name='live-inventory-file'))
    removal(sem, inventory, inventory_info, 'inventories', dict(project=PROJECT, name='live-inventory'))
    removal(sem, repository, repository_info, 'repositories', dict(project=PROJECT, name='live-repo'))
    removal(sem, key_store, key_store_info, 'key_store', dict(project=PROJECT, name='live-ssh'))
    removal(sem, key_store, key_store_info, 'key_store', dict(project=PROJECT, name='live-key'))


def test_project_removal(sem):
    refused = sem.run(project, name=PROJECT, state='absent')
    assert refused['failed'] is True
    assert 'confirm_delete' in refused['msg']
    removal(sem, project, project_info, 'projects', dict(name=PROJECT, confirm_delete=True), scope={})
