# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""The modules run by a user who is not an administrator of Harbor.

Registries and quotas are system-level in Harbor. `project` and
`project_info` read them, and treat a refusal (HTTP 401 or 403) as "this user
may not see them". These tests show what Harbor really answers such a user,
and that the modules then do what their documentation says.
"""

from ansible_collections.ramanavelineni.harbor.plugins.modules import project as project_module
from ansible_collections.ramanavelineni.harbor.plugins.modules import (
    configuration_info, garbage_collection_info, project_info, registry, registry_info, robot_account,
    robot_account_info, tag_immutability, tag_retention, webhook, webhook_info,
)
from ansible_collections.ramanavelineni.harbor.tests.live.conftest import PREFIX, changed


def forbidden(answer):
    """Whether an (status, body, headers) answer is Harbor's 403 FORBIDDEN."""
    status, body, dummy = answer
    return status == 403 and body['errors'][0]['code'] == 'FORBIDDEN'


def test_what_harbor_answers_a_non_admin(api, project, member):
    """The facts the modules build on: system-level reads are refused with 403, the own project is visible."""
    pid = api.projects(project)[0]['project_id']
    assert forbidden(api.call('GET', '/registries', **member))
    assert forbidden(api.call('GET', '/quotas?reference=project&reference_id=%d' % pid, **member))
    assert forbidden(api.call('GET', '/configurations', **member))
    assert forbidden(api.call('GET', '/replication/adapters', **member))
    assert forbidden(api.call('GET', '/system/gc/schedule', **member))
    status, mine, dummy = api.call('GET', '/projects?name=%s' % project, **member)
    assert status == 200
    assert [p['name'] for p in mine] == [project]
    status, me, dummy = api.call('GET', '/users/current', **member)
    assert status == 200 and me['sysadmin_flag'] is False


def test_project_modules_as_a_project_admin(run, project, member):
    read = run(project_info.main, dict(member, name=project))
    assert not read.get('failed'), read.get('msg')
    assert len(read['projects']) == 1
    # What only an administrator may read is null, not an error.
    assert read['projects'][0]['quota_gb'] is None
    assert read['projects'][0]['proxy_registry'] is None

    wanted = dict(member, name=project, public=False, metadata=dict(auto_scan=True))
    would = run(project_module.main, wanted, check=True)
    assert changed(would) is True
    stored = run(project_module.main, wanted)
    assert changed(stored) is True
    assert stored['project']['metadata']['auto_scan'] == 'true'
    assert stored['project']['quota_gb'] is None
    assert changed(run(project_module.main, wanted)) is False
    assert run(project_info.main, dict(member, name=project))['projects'] == [stored['project']]

    # Without a name: every project the user can see, each without its quota.
    everything = run(project_info.main, dict(member))
    assert not everything.get('failed'), everything.get('msg')
    assert project in [p['name'] for p in everything['projects']]
    assert all(p['quota_gb'] is None for p in everything['projects'])


def test_quota_and_proxy_registry_need_an_administrator(api, run, project, member):
    quota = run(project_module.main, dict(member, name=project, quota_gb=5))
    assert quota.get('failed') is True
    assert 'administrator' in quota['msg'] and '403' in quota['msg']

    proxy = run(project_module.main, dict(member, name=PREFIX + 'member-proxy', proxy_registry=PREFIX + 'no-such-endpoint'))
    assert proxy.get('failed') is True
    assert 'administrator' in proxy['msg']
    assert api.projects(PREFIX + 'member-proxy') == []


def test_a_non_admin_creates_and_deletes_a_project_of_their_own(api, run, member):
    name = PREFIX + 'member-made'
    wanted = dict(member, name=name, public=False)
    created = run(project_module.main, wanted)
    assert changed(created) is True
    assert created['project']['name'] == name
    assert created['project']['quota_gb'] is None
    assert changed(run(project_module.main, wanted)) is False
    assert changed(run(project_module.main, dict(member, name=name, state='absent', confirm_delete=True))) is True
    assert api.projects(name) == []


def test_project_scoped_modules_as_a_project_admin(run, project, member):
    hook = dict(member, project=project, name=PREFIX + 'member-hook', event_types=['PUSH_ARTIFACT'],
                address='http://live-suite.invalid/hook')
    assert changed(run(webhook.main, hook)) is True
    assert changed(run(webhook.main, hook)) is False
    assert len(run(webhook_info.main, dict(member, project=project))['webhooks']) == 1

    robot = dict(member, name=PREFIX + 'member-ci', level='project', project=project,
                 permissions=[dict(access=[dict(resource='repository', action='pull')])])
    made = run(robot_account.main, robot)
    assert changed(made) is True
    assert made['secret']
    assert changed(run(robot_account.main, robot)) is False
    assert len(run(robot_account_info.main, dict(member, project=project))['robot_accounts']) == 1

    rule = dict(member, project=project, tags='v*')
    assert changed(run(tag_immutability.main, rule)) is True
    assert changed(run(tag_immutability.main, rule)) is False

    policy = dict(member, project=project, rules=[dict(template='latestPushedK', value=5)])
    assert changed(run(tag_retention.main, policy)) is True
    assert changed(run(tag_retention.main, policy)) is False


def test_system_level_modules_refuse_a_non_admin_clearly(run, member):
    """Each fails with Harbor's refusal in the message: no traceback, nothing half done."""
    attempts = (
        (registry.main, dict(name=PREFIX + 'member-registry', type='harbor', endpoint_url='http://proxy:8080')),
        (registry_info.main, dict()),
        (robot_account.main, dict(name=PREFIX + 'member-robot', permissions=[
            dict(namespace='*', access=[dict(resource='repository', action='pull')])])),
        (configuration_info.main, dict()),
        (garbage_collection_info.main, dict()),
    )
    for main, args in attempts:
        result = run(main, dict(member, **args))
        assert result.get('failed') is True, main.__module__
        assert '403' in result['msg'], result['msg']
        assert 'Unexpected' not in result['msg']
        assert 'exception' not in result
