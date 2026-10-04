# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""Backups, restores, API tokens and the activity log, against a real server."""

import json
import os
import stat

import pytest

from ansible_collections.ramanavelineni.semaphoreui.plugins.modules import (
    event_info,
    inventory,
    key_store,
    key_store_info,
    project,
    project_backup,
    project_info,
    project_restore,
    repository,
    schedule,
    schedule_info,
    template,
    template_info,
    user_token,
    variable_group,
    variable_group_info,
)

PROJECT = 'live-backup'
COPY = 'live-backup-copy'
TOKEN = 'live-token'
PRIVATE_KEY = '-----BEGIN OPENSSH PRIVATE KEY-----\nlive-test\n-----END OPENSSH PRIVATE KEY-----'


def sweep_tokens(sem):
    """Revoke the suite's tokens. conftest's sweep does projects, runners and users only."""
    for token in sem.api.get('/user/tokens') or []:
        if (token.get('name') or '').startswith('live-'):
            sem.api.call('DELETE', '/user/tokens/%s' % token['id'])


@pytest.fixture(scope='module')
def built(sem):
    """A project with one of everything a backup holds."""
    sweep_tokens(sem)
    sem.ok(project, name=PROJECT, max_parallel_tasks=2)
    sem.ok(key_store, project=PROJECT, name='live-key', type='ssh', ssh=dict(login='git', private_key=PRIVATE_KEY))
    sem.ok(repository, project=PROJECT, name='live-repo', git_url='git@github.com:example/live.git', git_branch='main',
           ssh_key='live-key')
    sem.ok(inventory, project=PROJECT, name='live-inventory', type='static', inventory='localhost', ssh_key='live-key')
    sem.ok(variable_group, project=PROJECT, name='live-vars', env=dict(TZ='UTC'),
           secrets=[dict(name='LIVE_SECRET', value='live-secret-value', type='var')])
    sem.ok(template, project=PROJECT, name='live-site', playbook='site.yml', repository='live-repo',
           inventory='live-inventory', variable_groups=['live-vars'])
    sem.ok(schedule, project=PROJECT, name='live-nightly', template='live-site', cron='0 3 * * *')
    yield sem
    sweep_tokens(sem)


def names(sem, module, key, name):
    return sorted(o['name'] for o in sem.ok(module, project=name)[key])


# -- project_backup ---------------------------------------------------------


def test_backup_holds_the_project_and_no_secret(built):
    result = built.ok(project_backup, project=PROJECT)
    assert result['changed'] is False and result['file'] == ''
    backup = result['backup']
    assert backup['meta']['name'] == PROJECT and backup['meta']['max_parallel_tasks'] == 2
    assert [r['name'] for r in backup['repositories']] == ['live-repo']
    assert [t['name'] for t in backup['templates']] == ['live-site']
    assert [s['name'] for s in backup['schedules']] == ['live-nightly']
    # Objects are named, not numbered, and no secret is in it.
    text = json.dumps(backup)
    assert '"id"' not in text
    assert 'live-test' not in text and 'live-secret-value' not in text
    assert backup['repositories'][0]['ssh_key'] == 'live-key'


def test_backup_by_project_id(built):
    pid = built.ok(project_info, name=PROJECT)['projects'][0]['id']
    assert built.ok(project_backup, project_id=pid)['backup'] == built.ok(project_backup, project=PROJECT)['backup']


def test_backup_is_written_once(built, tmp_path):
    dest = str(tmp_path / 'backup.json')
    checked = built.ok(project_backup, project=PROJECT, dest=dest, check_mode=True)
    assert checked['changed'] is True and not os.path.exists(dest)

    first = built.ok(project_backup, project=PROJECT, dest=dest)
    assert first['changed'] is True and first['file'] == dest
    assert stat.S_IMODE(os.stat(dest).st_mode) == 0o600
    with open(dest, encoding='utf-8') as f:
        assert json.load(f) == first['backup']

    assert built.ok(project_backup, project=PROJECT, dest=dest)['changed'] is False
    assert built.ok(project_backup, project=PROJECT, dest=dest, check_mode=True)['changed'] is False

    os.chmod(dest, 0o644)
    assert built.ok(project_backup, project=PROJECT, dest=dest)['changed'] is True
    assert stat.S_IMODE(os.stat(dest).st_mode) == 0o600


def test_backup_of_a_missing_project_fails(built):
    result = built.run(project_backup, project='live-not-there')
    assert result['failed'] is True and 'live-not-there' in result['msg']


# -- project_restore --------------------------------------------------------


def test_restore_does_nothing_when_the_project_exists(built):
    backup = built.ok(project_backup, project=PROJECT)['backup']
    for check_mode in (True, False):
        result = built.ok(project_restore, backup=backup, check_mode=check_mode)
        assert result['changed'] is False
        assert result['project']['name'] == PROJECT


def test_restore_under_another_name(built, tmp_path):
    src = str(tmp_path / 'backup.json')
    built.ok(project_backup, project=PROJECT, dest=src)

    checked = built.ok(project_restore, src=src, name=COPY, check_mode=True)
    assert checked['changed'] is True and checked['project']['name'] == COPY and 'id' not in checked['project']
    assert built.ok(project_info, name=COPY)['projects'] == []

    restored = built.ok(project_restore, src=src, name=COPY)
    assert restored['changed'] is True
    assert restored['project'] == built.ok(project_info, name=COPY)['projects'][0]
    assert dict(restored['project'], id=None) == dict(checked['project'], id=None)

    again = built.ok(project_restore, src=src, name=COPY)
    assert again['changed'] is False and again['project'] == restored['project']


def test_the_restored_project_has_everything_but_the_secrets(built):
    assert names(built, template_info, 'templates', COPY) == ['live-site']
    assert names(built, schedule_info, 'schedules', COPY) == ['live-nightly']
    restored = built.ok(template_info, project=COPY)['templates'][0]
    original = built.ok(template_info, project=PROJECT)['templates'][0]
    for field in ('repository', 'inventory', 'variable_groups', 'playbook', 'app'):
        assert restored[field] == original[field]
    # A backup names the keys; their secrets stay behind.
    keys = dict((k['name'], k) for k in built.ok(key_store_info, project=COPY)['key_store'])
    assert keys['live-key']['type'] == 'ssh'
    status, raw = built.api.call('GET', '/project/%d/keys' % built.ok(project_info, name=COPY)['projects'][0]['id'])
    assert status == 200
    assert [k.get('empty') for k in raw if k['name'] == 'live-key'] == [True]
    group = built.ok(variable_group_info, project=COPY)['variable_groups'][0]
    assert group['env'] == dict(TZ='UTC') and group['secrets'] == []


def test_restore_refuses_what_is_not_a_backup(built, tmp_path):
    for backup, said in ((dict(), 'no "meta" section'), (dict(meta=dict(alert=False)), 'names no project')):
        result = built.run(project_restore, backup=backup)
        assert result['failed'] is True and said in result['msg']
    garbage = tmp_path / 'garbage.json'
    garbage.write_text('not json')
    result = built.run(project_restore, src=str(garbage))
    assert result['failed'] is True and 'does not hold JSON' in result['msg']
    # No project without a name was created along the way.
    assert [p for p in built.ok(project_info)['projects'] if not p['name']] == []


def test_restore_of_a_backup_semaphore_refuses(built):
    backup = built.ok(project_backup, project=PROJECT)['backup']
    backup['templates'][0]['repository'] = 'live-no-such-repository'
    result = built.run(project_restore, backup=backup, name='live-backup-broken')
    assert result['failed'] is True and 'Nothing was created' in result['msg']
    assert built.ok(project_info, name='live-backup-broken')['projects'] == []


def test_a_restore_that_fails_half_way_says_what_it_left(built):
    # A schedule's template is only looked up after Semaphore created the project.
    partial = dict(meta=dict(name='live-backup-partial'),
                   schedules=[dict(name='live-nightly', template='live-no-such-template', cron_format='0 3 * * *')])
    result = built.run(project_restore, backup=partial)
    left = built.ok(project_info, name='live-backup-partial')['projects']
    assert result['failed'] is True and len(left) == 1
    assert "created project 'live-backup-partial' (id %d) before it failed" % left[0]['id'] in result['msg']
    built.ok(project, name='live-backup-partial', state='absent', confirm_delete=True)


# -- event_info -------------------------------------------------------------


def test_events_of_a_project(built):
    events = built.ok(event_info, project=PROJECT)['events']
    assert events and all(e['project'] == PROJECT for e in events)
    assert events == sorted(events, key=lambda e: e['created'], reverse=True)
    kinds = set(e['object_type'] for e in events)
    assert set(['project', 'key', 'repository', 'inventory', 'environment']) <= kinds
    assert set(e['username'] for e in events) == set(['admin'])
    assert built.ok(event_info, project=PROJECT, limit=2)['events'] == events[:2]
    assert built.ok(event_info, project=PROJECT, limit=0)['events'] == events
    assert built.ok(event_info, project=PROJECT, check_mode=True)['events'] == events


def test_events_of_every_project(built):
    everything = built.ok(event_info, limit=0)['events']
    of_project = built.ok(event_info, project=PROJECT, limit=0)['events']
    assert [e for e in everything if e['project'] == PROJECT] == of_project
    assert len(built.ok(event_info, limit=3)['events']) == 3


def test_events_of_a_missing_project_fail(built):
    result = built.run(event_info, project='live-not-there')
    assert result['failed'] is True and 'live-not-there' in result['msg']


# -- user_token -------------------------------------------------------------


def listed(sem, name=TOKEN):
    return [t for t in sem.api.get('/user/tokens') or [] if t.get('name') == name]


def works(sem, token):
    """Whether Semaphore takes the token."""
    status, dummy = type(sem.api)(sem.connection['url'], None, None, token).call('GET', '/user')
    return status == 200


def test_token_is_created_once_and_returned_once(built):
    checked = built.ok(user_token, name=TOKEN, check_mode=True)
    assert checked['changed'] is True and checked['token'] == '' and listed(built) == []

    created = built.ok(user_token, name=TOKEN)
    assert created['changed'] is True
    token = created['token']
    assert len(token) > 20 and works(built, token)
    # What the module returns of the token besides its value is the start of it, as the server lists it.
    assert created['user_token']['id'] == token[:8] == listed(built)[0]['id']
    assert created['user_token']['name'] == TOKEN and created['user_token']['expired'] is False
    assert token not in json.dumps(created['diff']) and token not in json.dumps(created['user_token'])

    again = built.ok(user_token, name=TOKEN)
    assert again['changed'] is False and again['token'] == ''
    assert again['user_token'] == created['user_token']
    assert len(listed(built)) == 1 and works(built, token)

    asked = built.run(user_token, name=TOKEN, expires_at='2099-01-01T00:00:00Z')
    assert asked['failed'] is True and 'cannot change the expiry' in asked['msg']

    checked = built.ok(user_token, name=TOKEN, state='absent', check_mode=True)
    assert checked['changed'] is True and len(listed(built)) == 1
    removed = built.ok(user_token, name=TOKEN, state='absent')
    assert removed['changed'] is True and removed['user_token'] == {} and removed['token'] == ''
    assert listed(built) == [] and not works(built, token)
    assert built.ok(user_token, name=TOKEN, state='absent')['changed'] is False


def test_token_with_an_expiry(built):
    created = built.ok(user_token, name='live-token-expiring', expires_at='2099-01-01T01:00:00+01:00')
    assert created['user_token']['expires_at'] == '2099-01-01T00:00:00Z'
    assert built.ok(user_token, name='live-token-expiring', expires_at='2099-01-01T00:00:00Z')['changed'] is False
    assert built.ok(user_token, name='live-token-expiring')['changed'] is False
    past = built.run(user_token, name='live-token-past', expires_at='2001-01-01T00:00:00Z')
    assert past['failed'] is True and 'in the past' in past['msg']
    built.ok(user_token, name='live-token-expiring', state='absent')


def test_absent_revokes_every_token_of_the_name(built):
    for attempt in range(2):
        status, body = built.api.call('POST', '/user/tokens', dict(name='live-token-twice'))
        assert status == 201, 'token %d: %s' % (attempt, body)
    present = built.run(user_token, name='live-token-twice')
    assert present['failed'] is True and 'More than one API token' in present['msg']
    assert built.ok(user_token, name='live-token-twice', state='absent')['changed'] is True
    assert listed(built, 'live-token-twice') == []


def test_the_token_a_task_connects_with_is_not_revoked(built):
    if built.auth != 'api_token':
        pytest.skip('needs a run that connects with an API token')
    created = built.ok(user_token, name='live-token-own')
    own = dict(built.connection, api_token=created['token'])
    result = built.run(user_token, name='live-token-own', state='absent', **own)
    assert result['failed'] is True and 'connects with' in result['msg']
    assert works(built, created['token'])
    built.ok(user_token, name='live-token-own', state='absent')
