# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""Every `_info` module, with and without check mode.

They only read, so check mode must change nothing about them: the same
requests, the same result.
"""

import copy

import pytest

from ansible_collections.ramanavelineni.harbor.plugins.modules import (
    configuration_info,
    garbage_collection_info,
    info,
    log_rotation_info,
    project_info,
    registry_info,
    replication_info,
    robot_account_info,
    scan_all_info,
    tag_immutability_info,
    tag_retention_info,
    webhook_info,
)


def location_id(server, fixture):
    return int(server.fixtures[fixture]['headers']['location'].rsplit('/', 1)[-1])


def ok(body=None):
    return dict(status=200, body=body, headers={})


def no_routes(server):
    """`info` reads /systeminfo, which the fake server always answers."""


def configuration_routes(server):
    server.route('GET', '/configurations', 'system_configurations')


def gc_routes(server):
    server.route('GET', '/system/gc/schedule', 'system_gc_schedule_custom')
    server.route('GET', '/system/gc', 'system_gc_history')


def log_rotation_routes(server):
    server.route('GET', '/system/purgeaudit/schedule', 'system_purge_schedule_custom')
    server.route('GET', '/system/purgeaudit', 'system_purge_history')


def project_routes(server):
    server.route('GET', '/projects', 'projects_with_created')
    server.route('GET', '/quotas', 'quotas_all')


def registry_routes(server):
    server.route('GET', '/registries', 'registry_list')


def replication_routes(server):
    server.route('GET', '/replication/policies', 'registry_replication_list_updated')


def robot_routes(server):
    server.route('GET', '/robots', 'robot_list_system_all')
    server.route('GET', '/configurations', 'robot_configurations')


def scan_all_routes(server):
    # Hand-written after Harbor's swagger model: Scan All can't be recorded without a vulnerability scanner.
    server.route('GET', '/system/scanAll/schedule', ok(dict(
        id=3, status='Scheduled', schedule=dict(type='Daily', cron='0 0 0 * * *'), parameters={},
        creation_time='2026-09-27T20:00:00.000Z', update_time='2026-09-27T20:00:00.000Z')))
    server.route('GET', '/scans/all/metrics', ok(dict(total=4, completed=4, metrics=dict(Success=4), ongoing=False,
                                                      trigger='Schedule')))


def immutability_routes(server):
    pid = location_id(server, 'tag_project_create')
    server.route('GET', '/projects', 'tag_projects_list')
    server.route('GET', '/projects/%d' % pid, 'tag_project_get')
    server.route('GET', '/projects/%d/immutabletagrules' % pid, 'tag_immutability_list_one')


def retention_routes(server):
    pid = location_id(server, 'tag_project_create')
    server.route('GET', '/projects', 'tag_projects_list')
    server.route('GET', '/projects/%d' % pid, 'tag_project_get_with_retention')
    server.route('GET', '/retentions/%d' % location_id(server, 'tag_retention_create'), 'tag_retention_get_updated')


def webhook_routes(server):
    server.route('GET', '/projects', 'webhook_projects')
    server.route('GET', '/projects/%d/webhook/policies' % server.fixtures['webhook_projects']['body'][0]['project_id'],
                 'webhook_list_one')


# (module, the key of what it returns, routes, arguments)
INFO_CASES = [
    (info, 'info', no_routes, {}),
    (configuration_info, 'configuration', configuration_routes, {}),
    (garbage_collection_info, 'garbage_collection', gc_routes, {}),
    (log_rotation_info, 'log_rotation', log_rotation_routes, {}),
    (project_info, 'projects', project_routes, {}),
    (registry_info, 'registries', registry_routes, {}),
    (replication_info, 'replications', replication_routes, {}),
    (robot_account_info, 'robot_accounts', robot_routes, {}),
    (scan_all_info, 'scan_all', scan_all_routes, {}),
    (tag_immutability_info, 'tag_immutability', immutability_routes, dict(project='fixtures-tag-policy')),
    (tag_retention_info, 'tag_retention', retention_routes, dict(project='fixtures-tag-policy')),
    (webhook_info, 'webhooks', webhook_routes, dict(project='fixtures-webhook')),
]
INFO_IDS = [case[0].__name__.rsplit('.', 1)[-1] for case in INFO_CASES]


@pytest.mark.parametrize('module, key, routes, args', INFO_CASES, ids=INFO_IDS)
def test_info_module_is_the_same_in_check_mode(server, run_module, module, key, routes, args):
    routes(server)
    real = run_module(module.main, copy.deepcopy(args))
    asked = [(r['method'], r['path'], r['query']) for r in server.requests]
    del server.requests[:]
    check = run_module(module.main, copy.deepcopy(args), check_mode=True)
    asked_in_check_mode = [(r['method'], r['path'], r['query']) for r in server.requests]

    assert real.get('failed') is not True, real.get('msg')
    assert check.get('failed') is not True, check.get('msg')
    assert real['changed'] is False and check['changed'] is False
    # Something was read, and it is the same thing both times.
    assert real[key]
    assert check == real
    assert asked_in_check_mode == asked
    assert set(method for method, dummy_path, dummy_query in asked) == set(['GET'])


def test_log_rotation_info_without_a_schedule(server, run_module):
    server.route('GET', '/system/purgeaudit/schedule', 'system_purge_schedule_none')
    server.route('GET', '/system/purgeaudit', 'system_purge_history')
    result = run_module(log_rotation_info.main, {})
    assert result['log_rotation'] == dict(schedule='none', cron='', next_scheduled_time=None,
                                          audit_retention_hour=None, include_event_types=None, dry_run=None)
    assert result['runs'] == []
