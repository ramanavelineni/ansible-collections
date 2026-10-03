# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""Recorded answers that no other test routed.

The recorder saved these from throwaway servers for a reason each: a create
that another client got in first, an object that vanished before it was
deleted, a value Harbor refuses. They are what Harbor really says, so the
tests show what a task reports when it gets them.
"""

import json

import pytest

from ansible_collections.ramanavelineni.harbor.plugins.module_utils.harbor import (
    REPO_DECORATIONS,
    RETENTION_TEMPLATES,
    TAG_DECORATIONS,
)
from ansible_collections.ramanavelineni.harbor.plugins.modules import (
    configuration,
    project,
    registry,
    replication,
    robot_account,
    tag_immutability,
    tag_retention,
    webhook,
)

PULL_ALL = [dict(namespace='*', access=[dict(resource='repository', action='pull')])]
HOOK = dict(project='fixtures-webhook', name='ci-notify', description='recorded',
            event_types=['PUSH_ARTIFACT', 'DELETE_ARTIFACT'], address='http://127.0.0.1:9/hook',
            auth_header='Bearer not-a-real-token')
PULL = dict(name='rr-fixtures-pull', src_registry='rr-fixtures-self', dest_namespace='library', enabled=False,
            override=True, trigger=dict(type='manual'),
            filters=[dict(type='name', value='library/**'), dict(type='tag', value='v*', decoration='excludes')])
RULES = [dict(template='latestPushedK', value=10)]


def location_id(server, fixture):
    return int(server.fixtures[fixture]['headers']['location'].rsplit('/', 1)[-1])


def said(server, fixture):
    """The message Harbor gave in a recorded refusal."""
    return server.fixtures[fixture]['body']['errors'][0]['message']


def webhook_base(server):
    server.route('GET', '/projects', 'webhook_projects')
    return '/projects/%d/webhook/policies' % server.fixtures['webhook_projects']['body'][0]['project_id']


def tag_project(server, answer='tag_project_get'):
    pid = location_id(server, 'tag_project_create')
    server.route('GET', '/projects', 'tag_projects_list')
    server.route('GET', '/projects/%d' % pid, answer)
    return pid


def assert_reported(server, result, fixture):
    """The task failed with Harbor's recorded answer, as a message and not a traceback."""
    assert result['failed'] is True
    assert result.get('changed') is not True
    assert 'HTTP %d' % server.fixtures[fixture]['status'] in result['msg']
    assert said(server, fixture).split('\n')[0] in result['msg']
    assert result['request_details']['status'] == server.fixtures[fixture]['status']
    assert 'Unexpected' not in result['msg'] and 'Traceback' not in json.dumps(result)


# -- a project-level robot account ---------------------------------------------

def test_project_robot_is_created_in_its_project(server, run_module):
    rid = server.fixtures['robot_create_project']['body']['id']
    server.route('GET', '/projects', 'robot_projects_by_name')
    server.route('GET', '/robots', 'robot_list_system_empty')
    server.route('POST', '/robots', 'robot_create_project')
    server.route('GET', '/robots/%d' % rid, 'robot_get_project')
    result = run_module(robot_account.main, dict(
        name='ci', level='project', project='fixtures-robot', duration=30,
        permissions=[dict(access=[dict(resource='repository', action='pull')])]))
    assert result['changed'] is True
    assert server.calls('POST', '/robots')[0]['body'] == dict(
        name='ci', level='project', description='', duration=30, disable=False,
        # A permission without a namespace is one on the robot's own project.
        permissions=[dict(kind='project', namespace='fixtures-robot', access=[dict(resource='repository', action='pull')])])
    robot = result['robot_account']
    assert (robot['id'], robot['name'], robot['level'], robot['project']) == (rid, 'ci', 'project', 'fixtures-robot')
    assert robot['full_name'] == server.fixtures['robot_get_project']['body']['name']
    assert robot['duration'] == 30
    assert result['secret'] == server.fixtures['robot_create_project']['body']['secret']
    assert result['diff']['before'] == {} and result['diff']['after'] == robot


# -- a proxy-cache project --------------------------------------------------------

def test_proxy_cache_project_is_created_with_its_registry(server, run_module):
    pid = location_id(server, 'project_create_proxy')
    registry_entry = server.fixtures['registries_one']['body'][0]
    # Hand-edited: the quota of this project was not recorded; this is the
    # recorded quota of the other new project, under this project's id.
    quota = server.response('quotas_created')
    quota['body'][0]['ref']['id'] = pid
    quota['body'][0]['hard']['storage'] = -1
    server.route('GET', '/projects', 'projects_before')
    server.route('GET', '/registries', 'registries_one')
    server.route('POST', '/projects', 'project_create_proxy')
    server.route('GET', '/projects/%d' % pid, 'project_get_proxy')
    server.route('GET', '/quotas', quota)
    result = run_module(project.main, dict(name='fixtures-core-proxy', public=True, proxy_registry=registry_entry['name']))
    assert result['changed'] is True
    assert server.calls('POST', '/projects')[0]['body'] == dict(
        project_name='fixtures-core-proxy', metadata=dict(public='true'), registry_id=registry_entry['id'])
    created = result['project']
    assert (created['project_id'], created['registry_id'], created['proxy_registry']) == (
        pid, registry_entry['id'], registry_entry['name'])
    assert created['public'] is True
    assert server.calls('GET', '/quotas')[0]['query']['reference_id'] == [str(pid)]


def test_proxy_cache_project_needs_a_registry_that_exists(server, run_module):
    server.route('GET', '/projects', 'projects_before')
    server.route('GET', '/registries', 'registries_one')
    result = run_module(project.main, dict(name='fixtures-core-proxy', proxy_registry='no-such-registry'))
    assert result['failed'] is True
    assert "Registry 'no-such-registry' does not exist" in result['msg']
    assert server.calls('POST') == []


# -- another client created it first: HTTP 409 on a create ----------------------------

def conflict_registry(server):
    server.route('GET', '/registries', 'registry_list_before')
    server.route('POST', '/registries', 'registry_create_conflict')
    return registry.main, dict(name='rr-fixtures-self', type='harbor', endpoint_url='http://proxy:8080/', insecure=True)


def conflict_replication(server):
    server.route('GET', '/replication/policies', 'registry_replication_list_before')
    server.route('GET', '/registries', 'registry_list')
    server.route('POST', '/replication/policies', 'registry_replication_create_conflict')
    return replication.main, PULL


def conflict_robot(server):
    server.route('GET', '/robots', 'robot_list_system_empty')
    server.route('POST', '/robots', 'robot_create_conflict')
    return robot_account.main, dict(name='fixtures-robot-sys', permissions=PULL_ALL, secret='DeclaredSecret9')


def conflict_webhook(server):
    base = webhook_base(server)
    server.route('GET', base, 'webhook_list_empty')
    server.route('POST', base, 'webhook_create_conflict')
    return webhook.main, HOOK


CONFLICTS = [
    (conflict_registry, 'registry_create_conflict'),
    (conflict_replication, 'registry_replication_create_conflict'),
    (conflict_robot, 'robot_create_conflict'),
    (conflict_webhook, 'webhook_create_conflict'),
]


@pytest.mark.parametrize('routes, fixture', CONFLICTS, ids=['registry', 'replication', 'robot_account', 'webhook'])
def test_create_that_another_client_got_in_first_is_reported(server, run_module, routes, fixture):
    main, args = routes(server)
    result = run_module(main, args)
    assert_reported(server, result, fixture)
    # Nothing is written after the refusal, and a create is not sent twice.
    assert [r['method'] for r in server.requests if r['method'] != 'GET'] == ['POST']
    assert 'DeclaredSecret9' not in json.dumps(result) and 'not-a-real-token' not in json.dumps(result)


# -- the object vanished before it was deleted: HTTP 404 on a delete -------------------

def vanished_project(server):
    server.route('GET', '/projects', 'projects_with_created')
    server.route('DELETE', '/projects/%d' % location_id(server, 'project_create'), 'project_delete_missing')
    return project.main, dict(name='fixtures-core', state='absent', confirm_delete=True)


def vanished_webhook(server):
    base = webhook_base(server)
    server.route('GET', base, 'webhook_list_one')
    server.route('DELETE', '%s/%d' % (base, server.fixtures['webhook_get']['body']['id']), 'webhook_delete_missing')
    return webhook.main, dict(project='fixtures-webhook', name='ci-notify', state='absent')


def vanished_immutability_rule(server):
    base = '/projects/%d/immutabletagrules' % tag_project(server)
    server.route('GET', base, 'tag_immutability_list_one')
    server.route('DELETE', '%s/%d' % (base, location_id(server, 'tag_immutability_create')),
                 'tag_immutability_delete_missing')
    return tag_immutability.main, dict(project='fixtures-tag-policy', tags='v*', state='absent')


VANISHED = [
    (vanished_project, 'project_delete_missing'),
    (vanished_webhook, 'webhook_delete_missing'),
    (vanished_immutability_rule, 'tag_immutability_delete_missing'),
]


@pytest.mark.parametrize('routes, fixture', VANISHED, ids=['project', 'webhook', 'tag_immutability'])
def test_delete_of_an_object_that_vanished_is_reported(server, run_module, routes, fixture):
    # The object was listed and is gone when the delete arrives. The modules
    # report Harbor's answer; they don't turn it into "no change".
    main, args = routes(server)
    result = run_module(main, args)
    assert_reported(server, result, fixture)
    # A delete is not repeated.
    assert len(server.calls('DELETE')) == 1


def test_robot_that_vanished_after_its_update_is_reported(server, run_module):
    rid = server.fixtures['robot_create']['body']['id']
    server.route('GET', '/robots', 'robot_list_system')
    server.route('PUT', '/robots/%d' % rid, 'robot_update')
    server.route('GET', '/robots/%d' % rid, 'robot_get_deleted')
    result = run_module(robot_account.main, dict(name='fixtures-robot-sys', description='pulls everything'))
    assert_reported(server, result, 'robot_get_deleted')
    assert len(server.calls('PUT')) == 1


# -- values Harbor refuses ---------------------------------------------------------------

def test_configuration_value_of_the_wrong_type_is_reported(server, run_module):
    # The module converts the types it knows, so Harbor's own refusal only
    # shows when the two disagree about a setting's type.
    server.route('GET', '/configurations', 'system_configurations')
    server.route('PUT', '/configurations', 'system_configurations_bad_type')
    result = run_module(configuration.main, dict(settings=dict(session_timeout=45)))
    assert_reported(server, result, 'system_configurations_bad_type')
    assert len(server.calls('PUT')) == 1


def test_robot_name_harbor_refuses_is_reported(server, run_module):
    server.route('GET', '/robots', 'robot_list_system_empty')
    server.route('POST', '/robots', 'robot_create_bad_name')
    result = run_module(robot_account.main, dict(name='fixtures-robot-sys', permissions=PULL_ALL))
    assert_reported(server, result, 'robot_create_bad_name')


def test_robot_secret_harbor_refuses_is_reported_and_not_shown(server, run_module):
    rid = server.fixtures['robot_create']['body']['id']
    server.route('GET', '/robots', 'robot_list_system')
    server.route('PATCH', '/robots/%d' % rid, 'robot_secret_weak')
    result = run_module(robot_account.main, dict(name='fixtures-robot-sys', secret='DeclaredSecret9'))
    assert_reported(server, result, 'robot_secret_weak')
    assert 'DeclaredSecret9' not in json.dumps(result)
    # A refusal is not a passing failure: the secret is sent once.
    assert len(server.calls('PATCH')) == 1


def test_new_robot_is_removed_when_harbor_refuses_its_secret(server, run_module):
    rid = server.fixtures['robot_create']['body']['id']
    server.route('GET', '/robots', 'robot_list_system_empty')
    server.route('POST', '/robots', 'robot_create')
    server.route('PATCH', '/robots/%d' % rid, 'robot_secret_weak')
    server.route('DELETE', '/robots/%d' % rid, 'robot_delete')
    result = run_module(robot_account.main, dict(name='fixtures-robot-sys', permissions=PULL_ALL, secret='DeclaredSecret9'))
    assert result['failed'] is True
    assert said(server, 'robot_secret_weak') in result['msg'] and 'removed again' in result['msg']
    assert len(server.calls('DELETE', '/robots/%d' % rid)) == 1
    assert 'DeclaredSecret9' not in json.dumps(result) and 'RecordedSecret0' not in json.dumps(result)


def test_replication_schedule_harbor_refuses_is_reported(server, run_module):
    rule = location_id(server, 'registry_replication_create')
    server.route('GET', '/replication/policies', 'registry_replication_list')
    server.route('GET', '/registries', 'registry_list')
    server.route('PUT', '/replication/policies/%d' % rule, 'registry_replication_update_bad_cron')
    # A cron the module accepts; the recorded refusal stands for whatever rule Harbor has that the module doesn't.
    result = run_module(replication.main, dict(name='rr-fixtures-pull', trigger=dict(type='scheduled', cron='0 0 3 * * *')))
    assert_reported(server, result, 'registry_replication_update_bad_cron')
    assert server.calls('GET', '/replication/policies/%d' % rule) == []


def test_second_retention_policy_harbor_refuses_is_reported(server, run_module):
    tag_project(server)
    server.route('POST', '/retentions', 'tag_retention_create_again')
    result = run_module(tag_retention.main, dict(project='fixtures-tag-policy', rules=RULES))
    assert_reported(server, result, 'tag_retention_create_again')
    assert len(server.calls('POST')) == 1


def test_conflicting_retention_rules_harbor_refuses_are_reported(server, run_module):
    pid = tag_project(server, 'tag_project_get_with_retention')
    rid = location_id(server, 'tag_retention_create')
    server.route('GET', '/retentions/%d' % rid, 'tag_retention_get_updated')
    server.route('PUT', '/retentions/%d' % rid, 'tag_retention_update_duplicate')
    result = run_module(tag_retention.main, dict(project='fixtures-tag-policy', rules=RULES))
    assert_reported(server, result, 'tag_retention_update_duplicate')
    assert len(server.calls('GET', '/projects/%d' % pid)) == 1


# -- what Harbor shows after a change ------------------------------------------------

def test_registry_no_change_after_update(server, run_module):
    server.route('GET', '/registries', 'registry_list_updated')
    result = run_module(registry.main, dict(name='rr-fixtures-self', type='harbor', endpoint_url='http://proxy:8080/',
                                            insecure=True, description='updated'))
    assert result['changed'] is False
    assert result['registry']['description'] == 'updated'
    assert server.calls('PUT') == []


def test_project_without_its_retention_policy_has_none(server, run_module):
    # The project as Harbor shows it once its policy is deleted: the id is gone from its metadata.
    pid = tag_project(server, 'tag_project_get_after_retention_delete')
    result = run_module(tag_retention.main, dict(project='fixtures-tag-policy', state='absent'))
    assert result['changed'] is False
    assert result['tag_retention'] == {}
    assert [r['path'] for r in server.requests] == ['/systeminfo', '/projects', '/projects/%d' % pid]


def test_project_without_its_retention_policy_gets_a_new_one(server, run_module):
    tag_project(server, 'tag_project_get_after_retention_delete')
    rid = location_id(server, 'tag_retention_create')
    server.route('POST', '/retentions', 'tag_retention_create')
    server.route('GET', '/retentions/%d' % rid, 'tag_retention_get')
    result = run_module(tag_retention.main, dict(project='fixtures-tag-policy', rules=RULES))
    assert result['changed'] is True
    assert result['tag_retention']['id'] == rid
    assert server.calls('PUT') == []


# -- what Harbor says it knows ---------------------------------------------------------

def test_retention_templates_are_the_ones_harbor_lists(server):
    listed = server.fixtures['tag_retention_metadatas']['body']
    units = dict((t['rule_template'], t['params'][0]['unit'].lower().rstrip('s') if t['params'] else None)
                 for t in listed['templates'])
    known = dict((name, None if unit is None else unit.rstrip('s')) for name, unit in RETENTION_TEMPLATES.items())
    assert known == units


def test_selector_decorations_are_the_ones_harbor_lists(server):
    listed = server.fixtures['tag_retention_metadatas']['body']
    assert sorted(TAG_DECORATIONS.values()) == sorted(listed['tag_selectors'][0]['decorations'])
    assert sorted(REPO_DECORATIONS.values()) == sorted(listed['scope_selectors'][0]['decorations'])
    assert [s['kind'] for s in listed['tag_selectors'] + listed['scope_selectors']] == ['doublestar', 'doublestar']
