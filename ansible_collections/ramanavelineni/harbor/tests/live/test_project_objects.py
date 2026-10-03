# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""What lives in a project or beside it: robot accounts, webhooks, tag retention and tag immutability."""

from ansible_collections.ramanavelineni.harbor.plugins.modules import (
    robot_account, robot_account_info, tag_immutability, tag_immutability_info, tag_retention, tag_retention_info,
    webhook, webhook_info,
)
from ansible_collections.ramanavelineni.harbor.tests.live.conftest import PREFIX, changed

SECRET = 'Live-Robot-1x9Q'
OTHER_SECRET = 'Live-Robot-2y8P'


def robot_reads(api, robot, secret, project):
    """HTTP status when the robot lists the project's repositories with this secret."""
    return api.call('GET', '/projects/%s/repositories' % project, username=robot, password=secret)[0]


def test_system_robot(api, run, project):
    name = PREFIX + 'robot'
    wanted = dict(name=name, description='made by the live suite', secret=SECRET, update_secret='on_create', permissions=[
        dict(namespace='*', access=[dict(resource='repository', action='pull'), dict(resource='repository', action='list')])])

    predicted = run(robot_account.main, wanted, check=True)
    assert changed(predicted) is True
    assert predicted['secret_updated'] is True
    assert run(robot_account_info.main, dict(name=name))['robot_accounts'] == []

    created = run(robot_account.main, wanted)
    assert changed(created) is True
    assert created['secret_updated'] is True
    assert created['robot_account']['name'] == name
    assert created['robot_account']['level'] == 'system'
    assert SECRET not in str(created)
    full_name = created['robot_account']['full_name']
    assert full_name.endswith(name)

    # The declared secret is the robot's secret: Harbor accepts it, and nothing else.
    assert robot_reads(api, full_name, SECRET, project) == 200
    assert robot_reads(api, full_name, OTHER_SECRET, project) == 401

    again = run(robot_account.main, wanted)
    assert changed(again) is False
    assert again['secret_updated'] is False
    assert again['robot_account'] == created['robot_account']
    assert run(robot_account_info.main, dict(name=name))['robot_accounts'] == [created['robot_account']]

    # update_secret: always sets the declared secret on every run.
    rotated = run(robot_account.main, dict(name=name, secret=OTHER_SECRET))
    assert changed(rotated) is True
    assert rotated['secret_updated'] is True
    assert robot_reads(api, full_name, OTHER_SECRET, project) == 200
    assert robot_reads(api, full_name, SECRET, project) == 401

    update = dict(name=name, disable=True, description='changed by the live suite')
    would = run(robot_account.main, update, check=True)
    assert changed(would) is True
    updated = run(robot_account.main, update)
    assert changed(updated) is True
    assert updated['robot_account']['disable'] is True
    assert would['robot_account'] == updated['robot_account']
    assert changed(run(robot_account.main, update)) is False
    assert robot_reads(api, full_name, OTHER_SECRET, project) == 401

    gone = dict(name=name, state='absent')
    assert changed(run(robot_account.main, gone, check=True)) is True
    assert changed(run(robot_account.main, gone)) is True
    assert run(robot_account_info.main, dict(name=name))['robot_accounts'] == []
    assert changed(run(robot_account.main, gone)) is False


def test_project_robot_with_a_generated_secret(api, run, project):
    name = PREFIX + 'ci'
    wanted = dict(name=name, level='project', project=project, duration=30, permissions=[
        dict(access=[dict(resource='repository', action='pull'), dict(resource='repository', action='list')])])

    created = run(robot_account.main, wanted)
    assert changed(created) is True
    assert created['robot_account']['level'] == 'project'
    assert created['robot_account']['project'] == project
    assert created['robot_account']['duration'] == 30
    generated = created['secret']
    assert generated
    assert robot_reads(api, created['robot_account']['full_name'], generated, project) == 200

    # The generated secret is returned that one time only.
    again = run(robot_account.main, wanted)
    assert changed(again) is False
    assert 'secret' not in again
    assert again['robot_account'] == created['robot_account']
    listed = run(robot_account_info.main, dict(project=project))
    assert listed['robot_accounts'] == [created['robot_account']]

    assert changed(run(robot_account.main, dict(name=name, level='project', project=project, state='absent'))) is True
    assert run(robot_account_info.main, dict(project=project))['robot_accounts'] == []


def test_webhook(run, project):
    name = PREFIX + 'hook'
    wanted = dict(project=project, name=name, description='made by the live suite', notify_type='http',
                  event_types=['PUSH_ARTIFACT', 'DELETE_ARTIFACT'], address='http://live-suite.invalid/hook',
                  auth_header='Bearer live-suite-token', skip_cert_verify=True)

    predicted = run(webhook.main, wanted, check=True)
    assert changed(predicted) is True
    assert run(webhook_info.main, dict(project=project))['webhooks'] == []

    created = run(webhook.main, wanted)
    assert changed(created) is True
    assert created['webhook']['event_types'] == ['DELETE_ARTIFACT', 'PUSH_ARTIFACT']
    assert created['webhook']['auth_header_set'] is True
    assert 'live-suite-token' not in str(created)

    again = run(webhook.main, wanted)
    assert changed(again) is False
    assert again['webhook'] == created['webhook']
    # webhook_info adds one documented key, the number of endpoints; the rest is the manage module's shape.
    assert run(webhook_info.main, dict(project=project, name=name))['webhooks'] == [dict(created['webhook'], endpoints=1)]

    update = dict(project=project, name=name, enabled=False, event_types=['PUSH_ARTIFACT'], auth_header='')
    would = run(webhook.main, update, check=True)
    assert changed(would) is True
    updated = run(webhook.main, update)
    assert changed(updated) is True
    assert updated['webhook']['enabled'] is False
    assert updated['webhook']['event_types'] == ['PUSH_ARTIFACT']
    assert updated['webhook']['auth_header_set'] is False
    assert would['webhook'] == updated['webhook']
    assert changed(run(webhook.main, update)) is False

    gone = dict(project=project, name=name, state='absent')
    assert changed(run(webhook.main, gone, check=True)) is True
    assert changed(run(webhook.main, gone)) is True
    assert run(webhook_info.main, dict(project=project))['webhooks'] == []
    assert changed(run(webhook.main, gone)) is False


def test_webhook_event_the_server_does_not_offer(run, project):
    """An event outside the known ten is checked against the server's own list."""
    refused = run(webhook.main, dict(project=project, name=PREFIX + 'hook', address='http://live-suite.invalid/hook',
                                     event_types=['LIVE_SUITE_NO_SUCH_EVENT']))
    assert refused.get('failed') is True
    assert 'LIVE_SUITE_NO_SUCH_EVENT' in refused['msg']
    assert run(webhook_info.main, dict(project=project))['webhooks'] == []


def test_tag_retention(run, project):
    wanted = dict(project=project, rules=[dict(template='latestPushedK', value=3),
                                          dict(template='nDaysSinceLastPull', value=90, tags='v*', untagged=True)])

    predicted = run(tag_retention.main, wanted, check=True)
    assert changed(predicted) is True
    assert not run(tag_retention_info.main, dict(project=project))['tag_retention']

    created = run(tag_retention.main, wanted)
    assert changed(created) is True
    assert created['tag_retention']['id']
    assert created['tag_retention']['schedule'] == ''
    assert [rule['template'] for rule in created['tag_retention']['rules']] == ['latestPushedK', 'nDaysSinceLastPull']

    again = run(tag_retention.main, wanted)
    assert changed(again) is False
    assert again['tag_retention'] == created['tag_retention']
    assert run(tag_retention_info.main, dict(project=project))['tag_retention'] == created['tag_retention']

    update = dict(project=project, schedule='0 0 3 29 2 *', rules=[dict(template='always')])
    would = run(tag_retention.main, update, check=True)
    assert changed(would) is True
    updated = run(tag_retention.main, update)
    assert changed(updated) is True
    assert updated['tag_retention']['schedule'] == '0 0 3 29 2 *'
    assert [rule['template'] for rule in updated['tag_retention']['rules']] == ['always']
    assert would['tag_retention'] == updated['tag_retention']
    assert changed(run(tag_retention.main, update)) is False

    gone = dict(project=project, state='absent')
    assert changed(run(tag_retention.main, gone, check=True)) is True
    assert changed(run(tag_retention.main, gone)) is True
    assert not run(tag_retention_info.main, dict(project=project))['tag_retention']
    assert changed(run(tag_retention.main, gone)) is False


def test_tag_immutability(run, project):
    wanted = dict(project=project, tags='v*', repositories='apps/**')

    predicted = run(tag_immutability.main, wanted, check=True)
    assert changed(predicted) is True
    assert run(tag_immutability_info.main, dict(project=project))['tag_immutability'] == []

    created = run(tag_immutability.main, wanted)
    assert changed(created) is True
    assert created['tag_immutability']['disabled'] is False

    again = run(tag_immutability.main, wanted)
    assert changed(again) is False
    assert again['tag_immutability'] == created['tag_immutability']
    assert run(tag_immutability_info.main, dict(project=project))['tag_immutability'] == [created['tag_immutability']]

    # A rule with other patterns is another rule.
    other = run(tag_immutability.main, dict(project=project, tags='release-*'))
    assert changed(other) is True
    assert other['tag_immutability']['id'] != created['tag_immutability']['id']

    off = dict(wanted, disabled=True)
    would = run(tag_immutability.main, off, check=True)
    assert changed(would) is True
    updated = run(tag_immutability.main, off)
    assert changed(updated) is True
    assert updated['tag_immutability']['disabled'] is True
    assert would['tag_immutability'] == updated['tag_immutability']
    assert changed(run(tag_immutability.main, off)) is False

    gone = dict(wanted, state='absent')
    assert changed(run(tag_immutability.main, gone, check=True)) is True
    assert changed(run(tag_immutability.main, gone)) is True
    assert changed(run(tag_immutability.main, gone)) is False
    assert len(run(tag_immutability_info.main, dict(project=project))['tag_immutability']) == 1
