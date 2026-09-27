# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

import pytest

from ansible_collections.ramanavelineni.harbor.plugins.modules import tag_retention, tag_retention_info

PROJECT = 'fixtures-tag-policy'
RULES = [dict(template='latestPushedK', value=10),
         dict(template='nDaysSinceLastPull', value=180, repositories='app/**', tags='v*', untagged=True),
         dict(template='always', tags='tmp-*', tags_decoration='excludes', repositories_decoration='excludes',
              disabled=True)]


def pid(server):
    return int(server.fixtures['tag_project_create']['headers']['location'].rsplit('/', 1)[-1])


def rid(server):
    return int(server.fixtures['tag_retention_create']['headers']['location'].rsplit('/', 1)[-1])


@pytest.fixture
def without_policy(server):
    server.route('GET', '/projects', 'tag_projects_list')
    server.route('GET', '/projects/%d' % pid(server), 'tag_project_get')
    return server


@pytest.fixture
def with_policy(server):
    server.route('GET', '/projects', 'tag_projects_list')
    server.route('GET', '/projects/%d' % pid(server), 'tag_project_get_with_retention')
    server.route('GET', '/retentions/%d' % rid(server), 'tag_retention_get_updated')
    return server


def test_create(without_policy, run_module):
    server = without_policy
    server.route('POST', '/retentions', 'tag_retention_create')
    result = run_module(tag_retention.main, dict(project=PROJECT, rules=RULES[:1]))
    assert result['changed'] is True
    assert result['tag_retention']['id'] == rid(server)
    body = server.calls('POST', '/retentions')[0]['body']
    assert body['scope'] == dict(level='project', ref=pid(server))
    assert body['trigger'] == dict(kind='Schedule', settings=dict(cron=''))
    assert body['algorithm'] == 'or'
    assert body['rules'] == [dict(
        disabled=False, action='retain', template='latestPushedK', params=dict(latestPushedK=10),
        tag_selectors=[dict(kind='doublestar', decoration='matches', pattern='**', extras='{"untagged": false}')],
        scope_selectors=dict(repository=[dict(kind='doublestar', decoration='repoMatches', pattern='**')]))]


def test_create_check_mode(without_policy, run_module):
    result = run_module(tag_retention.main, dict(project=PROJECT, rules=RULES[:1]), check_mode=True)
    assert result['changed'] is True
    assert without_policy.calls('POST') == []


def test_no_change(with_policy, run_module):
    result = run_module(tag_retention.main, dict(project=PROJECT, schedule='0 0 3 * * *', rules=RULES))
    assert result['changed'] is False
    assert with_policy.calls('PUT') == []
    rules = result['tag_retention']['rules']
    assert rules[1]['untagged'] is True and rules[1]['repositories'] == 'app/**'
    assert rules[2]['disabled'] is True and rules[2]['tags_decoration'] == 'excludes'
    assert rules[2]['value'] is None


def test_schedule_only_keeps_rules(with_policy, run_module):
    server = with_policy
    server.route('PUT', '/retentions/%d' % rid(server), 'tag_retention_update')
    result = run_module(tag_retention.main, dict(project=PROJECT, schedule=''))
    assert result['changed'] is True
    body = server.calls('PUT')[0]['body']
    assert body['trigger']['settings']['cron'] == ''
    assert [r['template'] for r in body['rules']] == ['latestPushedK', 'nDaysSinceLastPull', 'always']
    assert body['rules'][2]['params'] == {}


def test_rules_replace_the_list(with_policy, run_module):
    server = with_policy
    server.route('PUT', '/retentions/%d' % rid(server), 'tag_retention_update')
    result = run_module(tag_retention.main, dict(project=PROJECT, rules=RULES[:1]))
    assert result['changed'] is True
    assert len(server.calls('PUT')[0]['body']['rules']) == 1
    assert result['diff']['before']['rules'] != result['diff']['after']['rules']


@pytest.mark.parametrize('rules, message', [
    ([dict(template='latestPushedK')], 'needs value'),
    ([dict(template='latestPushedK', value=0)], 'needs value'),
    ([dict(template='always', value=1)], 'takes no value'),
    ([dict(template='latestPushedK', value=1)] * 2, 'identical'),
    ([dict(template='latestPushedK', value=n + 1) for n in range(16)], 'at most 15'),
])
def test_rules_checked_before_sending(without_policy, run_module, rules, message):
    result = run_module(tag_retention.main, dict(project=PROJECT, rules=rules))
    assert result['failed'] is True
    assert message in result['msg']
    assert without_policy.calls('POST') == [] and without_policy.calls('PUT') == []


def test_bad_cron_reported(with_policy, run_module):
    server = with_policy
    server.route('PUT', '/retentions/%d' % rid(server), 'tag_retention_update_bad_cron')
    result = run_module(tag_retention.main, dict(project=PROJECT, schedule='nope'))
    assert result['failed'] is True
    assert 'invalid cron string' in result['msg']


def test_delete(with_policy, run_module):
    server = with_policy
    server.route('DELETE', '/retentions/%d' % rid(server), 'tag_retention_delete')
    result = run_module(tag_retention.main, dict(project=PROJECT, state='absent'))
    assert result['changed'] is True
    assert result['tag_retention'] == {}


def test_delete_check_mode(with_policy, run_module):
    result = run_module(tag_retention.main, dict(project=PROJECT, state='absent'), check_mode=True)
    assert result['changed'] is True
    assert with_policy.calls('DELETE') == []


def test_delete_missing(without_policy, run_module):
    result = run_module(tag_retention.main, dict(project=PROJECT, state='absent'))
    assert result['changed'] is False


def test_unknown_project(without_policy, run_module):
    result = run_module(tag_retention.main, dict(project='no-such-project', rules=[]))
    assert result['failed'] is True
    assert "'no-such-project' does not exist" in result['msg']


def test_info(with_policy, run_module):
    result = run_module(tag_retention_info.main, dict(project=PROJECT))
    policy = result['tag_retention']
    assert policy['schedule'] == '0 0 3 * * *'
    assert [r['template'] for r in policy['rules']] == ['latestPushedK', 'nDaysSinceLastPull', 'always']


def test_info_without_policy(without_policy, run_module):
    assert run_module(tag_retention_info.main, dict(project=PROJECT))['tag_retention'] == {}
