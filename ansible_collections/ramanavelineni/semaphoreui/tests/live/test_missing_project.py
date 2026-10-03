# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""A project that does not exist: a check run of a whole play, and removals."""

import pytest

from ansible_collections.ramanavelineni.semaphoreui.plugins.modules import (
    integration,
    inventory,
    inventory_info,
    key_store,
    project,
    project_info,
    repository,
    schedule,
    team_member,
    template,
    variable_group,
    view,
)

PROJECT = 'live-not-there'
PRIVATE_KEY = '-----BEGIN OPENSSH PRIVATE KEY-----\nlive-test\n-----END OPENSSH PRIVATE KEY-----'

# A play that builds a project from nothing, in the order it would run.
PLAY = [
    (project, dict(name=PROJECT)),
    (key_store, dict(project=PROJECT, name='live-key', type='ssh', ssh=dict(login='git', private_key=PRIVATE_KEY))),
    (repository, dict(project=PROJECT, name='live-repo', git_url='git@github.com:example/live.git', git_branch='main',
                      ssh_key='live-key')),
    (inventory, dict(project=PROJECT, name='live-inventory', type='static', inventory='localhost', ssh_key='live-key')),
    (variable_group, dict(project=PROJECT, name='live-vars', env=dict(TZ='UTC'))),
    (view, dict(project=PROJECT, name='live-view')),
    (template, dict(project=PROJECT, name='live-site', playbook='site.yml', repository='live-repo',
                    inventory='live-inventory', variable_groups=['live-vars'], view='live-view')),
    (schedule, dict(project=PROJECT, name='live-nightly', template='live-site', cron='0 3 * * *')),
    (integration, dict(project=PROJECT, name='live-hook', template='live-site')),
    (team_member, dict(project=PROJECT, user='admin', role='owner')),
]
IDS = [module.__name__.rsplit('.', 1)[-1] for module, dummy in PLAY]


def exists(sem):
    return [p for p in sem.ok(project_info)['projects'] if p['name'] == PROJECT]


@pytest.mark.parametrize('module, options', PLAY, ids=IDS)
def test_check_run_on_an_empty_server(sem, module, options):
    """--check of a play whose first task would create the project: every task reports a change, none fails."""
    assert exists(sem) == []
    result = sem.ok(module, check_mode=True, **options)
    assert result['changed'] is True
    assert exists(sem) == []


@pytest.mark.parametrize('module, options', PLAY[1:], ids=IDS[1:])
def test_real_run_fails_without_the_project(sem, module, options):
    """Outside check mode a missing project is still a failure that names it."""
    result = sem.run(module, **options)
    assert result['failed'] is True
    assert PROJECT in result['msg']
    assert exists(sem) == []


@pytest.mark.parametrize('module, options', PLAY, ids=IDS)
def test_removal_from_a_missing_project(sem, module, options):
    """state: absent has nothing to do when the project is already gone."""
    name = dict((k, v) for k, v in options.items() if k in ('project', 'name', 'user'))
    extra = dict(confirm_delete=True) if module is project else {}
    result = sem.ok(module, state='absent', **dict(name, **extra))
    assert result['changed'] is False
    assert sem.ok(module, check_mode=True, state='absent', **dict(name, **extra))['changed'] is False


def test_info_fails_for_a_missing_project(sem):
    result = sem.run(inventory_info, project=PROJECT)
    assert result['failed'] is True
    assert PROJECT in result['msg']
    assert sem.run(inventory_info, check_mode=True, project=PROJECT)['failed'] is True
