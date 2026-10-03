# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""Check mode, for every operation of every module that writes.

Each case is run twice against the fake server. In check mode only the reads
are routed: the fake server refuses any other request, so a write would fail
the task. Then the same task runs for real, with the writes routed, and the
two results are compared: check mode has to report what the real run reports.

Only what Harbor assigns itself (an id, a status, the next run of a schedule)
may differ; each case names those fields.
"""

import copy
import json

import pytest

from ansible_collections.ramanavelineni.harbor.plugins.modules import (
    configuration,
    garbage_collection,
    log_rotation,
    project,
    registry,
    replication,
    robot_account,
    scan_all,
    tag_immutability,
    tag_retention,
    webhook,
)

GC = '/system/gc/schedule'
PURGE = '/system/purgeaudit/schedule'
SCAN_ALL = '/system/scanAll/schedule'
WRITES = ('POST', 'PUT', 'PATCH', 'DELETE')


def location_id(server, fixture):
    return int(server.fixtures[fixture]['headers']['location'].rsplit('/', 1)[-1])


def ok(body=None):
    return dict(status=200, body=body, headers={})


def with_job_parameters(server, name, **changes):
    """Hand-edited: a recorded schedule with some of its job parameters replaced.

    No schedule was recorded after a change of one parameter.
    """
    answer = server.response(name)
    parameters = json.loads(answer['body']['job_parameters'])
    parameters.update(changes)
    answer['body']['job_parameters'] = json.dumps(parameters)
    return answer


def scan_all_schedule(cron, kind):
    """Hand-written after Harbor's swagger model: Scan All can't be recorded without a vulnerability scanner."""
    return ok(dict(id=3, status='Scheduled', schedule=dict(type=kind, cron=cron), parameters={},
                   creation_time='2026-09-27T20:00:00.000Z', update_time='2026-09-27T20:00:00.000Z'))


# -- routes ----------------------------------------------------------------------
# Each function routes the reads of one operation, and with real=True also its
# writes and the reads that follow them.

def configuration_change(server, real):
    server.route('GET', '/configurations', 'system_configurations')
    if real:
        server.route('GET', '/configurations', 'system_configurations', 'system_configurations_updated')
        server.route('PUT', '/configurations', 'system_configurations_update')


def gc_create(server, real):
    server.route('GET', GC, 'system_gc_schedule_none')
    if real:
        server.route('GET', GC, 'system_gc_schedule_none', 'system_gc_schedule_custom')
        server.route('PUT', GC, 'system_gc_schedule_update')


def gc_change(server, real):
    server.route('GET', GC, 'system_gc_schedule_custom')
    if real:
        server.route('GET', GC, 'system_gc_schedule_custom', with_job_parameters(server, 'system_gc_schedule_custom', workers=4))
        server.route('PUT', GC, 'system_gc_schedule_update')


def gc_remove(server, real):
    server.route('GET', GC, 'system_gc_schedule_custom')
    if real:
        server.route('GET', GC, 'system_gc_schedule_custom', 'system_gc_schedule_none')
        server.route('PUT', GC, 'system_gc_schedule_update')


def lr_create(server, real):
    server.route('GET', '/auditlog-exts/events', 'system_event_types')
    server.route('GET', PURGE, 'system_purge_schedule_none')
    if real:
        server.route('GET', PURGE, 'system_purge_schedule_none', 'system_purge_schedule_custom')
        server.route('PUT', PURGE, 'system_purge_schedule_update')


def lr_change(server, real):
    server.route('GET', PURGE, 'system_purge_schedule_custom')
    if real:
        server.route('GET', PURGE, 'system_purge_schedule_custom',
                     with_job_parameters(server, 'system_purge_schedule_custom', audit_retention_hour=168))
        server.route('PUT', PURGE, 'system_purge_schedule_update')


def lr_remove(server, real):
    server.route('GET', PURGE, 'system_purge_schedule_custom')
    if real:
        server.route('GET', PURGE, 'system_purge_schedule_custom', 'system_purge_schedule_none')
        server.route('PUT', PURGE, 'system_purge_schedule_update')


def scan_all_create(server, real):
    server.route('GET', SCAN_ALL, ok(None))
    if real:
        server.route('GET', SCAN_ALL, ok(None), scan_all_schedule('0 0 5 * * 0', 'Custom'))
        server.route('PUT', SCAN_ALL, ok(None))


def scan_all_change(server, real):
    server.route('GET', SCAN_ALL, scan_all_schedule('0 0 5 * * 0', 'Custom'))
    if real:
        server.route('GET', SCAN_ALL, scan_all_schedule('0 0 5 * * 0', 'Custom'), scan_all_schedule('0 0 0 * * *', 'Daily'))
        server.route('PUT', SCAN_ALL, ok(None))


def scan_all_remove(server, real):
    server.route('GET', SCAN_ALL, scan_all_schedule('0 0 5 * * 0', 'Custom'))
    if real:
        server.route('GET', SCAN_ALL, scan_all_schedule('0 0 5 * * 0', 'Custom'), ok(None))
        server.route('PUT', SCAN_ALL, ok(None))


def project_create(server, real):
    server.route('GET', '/projects', 'projects_before')
    if real:
        pid = location_id(server, 'project_create')
        server.route('POST', '/projects', 'project_create')
        server.route('GET', '/projects/%d' % pid, 'project_get')
        server.route('GET', '/quotas', 'quotas_created')


def project_update(server, real):
    pid = location_id(server, 'project_create')
    server.route('GET', '/projects', 'projects_with_created')
    server.route('GET', '/quotas', 'quotas_created')
    if real:
        server.route('GET', '/quotas', 'quotas_created', 'quotas_created_updated')
        server.route('PUT', '/projects/%d' % pid, 'project_update')
        server.route('PUT', '/quotas/%d' % server.fixtures['quotas_created']['body'][0]['id'], 'quota_update')
        server.route('GET', '/projects/%d' % pid, 'project_get_updated')


def project_delete(server, real):
    server.route('GET', '/projects', 'projects_with_created')
    if real:
        server.route('DELETE', '/projects/%d' % location_id(server, 'project_create'), 'project_delete')


def registry_create(server, real):
    server.route('GET', '/registries', 'registry_list_before')
    if real:
        rid = location_id(server, 'registry_create')
        server.route('POST', '/registries', 'registry_create')
        server.route('GET', '/registries/%d' % rid, 'registry_get')


def registry_update(server, real):
    server.route('GET', '/registries', 'registry_list')
    if real:
        rid = location_id(server, 'registry_create')
        server.route('PUT', '/registries/%d' % rid, 'registry_update')
        server.route('GET', '/registries/%d' % rid, 'registry_get_updated')


def registry_secret(server, real):
    server.route('GET', '/registries', 'registry_list')
    if real:
        rid = server.fixtures['registry_get_with_credential']['body']['id']
        server.route('PUT', '/registries/%d' % rid, 'registry_update')
        server.route('GET', '/registries/%d' % rid, 'registry_get_with_credential')


def registry_delete(server, real):
    server.route('GET', '/registries', 'registry_list')
    if real:
        server.route('DELETE', '/registries/%d' % location_id(server, 'registry_create'), 'registry_delete')


def replication_create(server, real):
    server.route('GET', '/replication/policies', 'registry_replication_list_before')
    server.route('GET', '/registries', 'registry_list')
    if real:
        rule = location_id(server, 'registry_replication_create')
        server.route('POST', '/replication/policies', 'registry_replication_create')
        server.route('GET', '/replication/policies/%d' % rule, 'registry_replication_get')


def replication_update(server, real):
    server.route('GET', '/replication/policies', 'registry_replication_list')
    server.route('GET', '/registries', 'registry_list')
    if real:
        rule = location_id(server, 'registry_replication_create')
        server.route('PUT', '/replication/policies/%d' % rule, 'registry_replication_update')
        server.route('GET', '/replication/policies/%d' % rule, 'registry_replication_get_updated')


def replication_delete(server, real):
    server.route('GET', '/replication/policies', 'registry_replication_list')
    if real:
        server.route('DELETE', '/replication/policies/%d' % location_id(server, 'registry_replication_create'),
                     'registry_replication_delete')


def robot_create(server, real):
    server.route('GET', '/robots', 'robot_list_system_empty')
    if real:
        rid = server.fixtures['robot_create']['body']['id']
        server.route('POST', '/robots', 'robot_create')
        server.route('PATCH', '/robots/%d' % rid, 'robot_secret_set')
        server.route('GET', '/robots/%d' % rid, 'robot_get')


def robot_create_in_project(server, real):
    server.route('GET', '/projects', 'robot_projects_by_name')
    server.route('GET', '/robots', 'robot_list_system_empty')
    if real:
        rid = server.fixtures['robot_create_project']['body']['id']
        server.route('POST', '/robots', 'robot_create_project')
        server.route('GET', '/robots/%d' % rid, 'robot_get_project')


def robot_update(server, real):
    server.route('GET', '/robots', 'robot_list_system')
    if real:
        rid = server.fixtures['robot_create']['body']['id']
        server.route('PUT', '/robots/%d' % rid, 'robot_update')
        server.route('PATCH', '/robots/%d' % rid, 'robot_secret_set')
        server.route('GET', '/robots/%d' % rid, 'robot_get_updated')


def robot_delete(server, real):
    server.route('GET', '/robots', 'robot_list_system')
    if real:
        server.route('DELETE', '/robots/%d' % server.fixtures['robot_create']['body']['id'], 'robot_delete')


def tag_project(server):
    pid = location_id(server, 'tag_project_create')
    server.route('GET', '/projects', 'tag_projects_list')
    server.route('GET', '/projects/%d' % pid, 'tag_project_get')
    return pid


def immutability_create(server, real):
    base = '/projects/%d/immutabletagrules' % tag_project(server)
    server.route('GET', base, 'tag_immutability_list_empty')
    if real:
        server.route('POST', base, 'tag_immutability_create')
        server.route('PUT', '%s/%d' % (base, location_id(server, 'tag_immutability_create')), 'tag_immutability_toggle')


def immutability_toggle(server, real):
    base = '/projects/%d/immutabletagrules' % tag_project(server)
    server.route('GET', base, 'tag_immutability_list_one')
    if real:
        server.route('PUT', '%s/%d' % (base, location_id(server, 'tag_immutability_create')), 'tag_immutability_toggle')


def immutability_delete(server, real):
    base = '/projects/%d/immutabletagrules' % tag_project(server)
    server.route('GET', base, 'tag_immutability_list_one')
    if real:
        server.route('DELETE', '%s/%d' % (base, location_id(server, 'tag_immutability_create')), 'tag_immutability_delete')


def retention_create(server, real):
    tag_project(server)
    if real:
        server.route('POST', '/retentions', 'tag_retention_create')
        server.route('GET', '/retentions/%d' % location_id(server, 'tag_retention_create'), 'tag_retention_get')


def retention_update(server, real):
    pid = tag_project(server)
    rid = location_id(server, 'tag_retention_create')
    server.route('GET', '/projects/%d' % pid, 'tag_project_get_with_retention')
    server.route('GET', '/retentions/%d' % rid, 'tag_retention_get')
    if real:
        server.route('GET', '/retentions/%d' % rid, 'tag_retention_get', 'tag_retention_get_updated')
        server.route('PUT', '/retentions/%d' % rid, 'tag_retention_update')


def retention_delete(server, real):
    pid = tag_project(server)
    rid = location_id(server, 'tag_retention_create')
    server.route('GET', '/projects/%d' % pid, 'tag_project_get_with_retention')
    server.route('GET', '/retentions/%d' % rid, 'tag_retention_get_updated')
    if real:
        server.route('DELETE', '/retentions/%d' % rid, 'tag_retention_delete')


def webhook_base(server):
    server.route('GET', '/projects', 'webhook_projects')
    return '/projects/%d/webhook/policies' % server.fixtures['webhook_projects']['body'][0]['project_id']


def webhook_create(server, real):
    base = webhook_base(server)
    server.route('GET', base, 'webhook_list_empty')
    if real:
        server.route('POST', base, 'webhook_create')
        server.route('GET', '%s/%d' % (base, server.fixtures['webhook_get']['body']['id']), 'webhook_get')


def webhook_update(server, real):
    base = webhook_base(server)
    server.route('GET', base, 'webhook_list_one')
    if real:
        path = '%s/%d' % (base, server.fixtures['webhook_get']['body']['id'])
        server.route('PUT', path, 'webhook_update')
        server.route('GET', path, 'webhook_get_updated')


def webhook_delete(server, real):
    base = webhook_base(server)
    server.route('GET', base, 'webhook_list_one')
    if real:
        server.route('DELETE', '%s/%d' % (base, server.fixtures['webhook_get']['body']['id']), 'webhook_delete')


# -- the cases -----------------------------------------------------------------

PULL_ALL = [dict(namespace='*', access=[dict(resource='repository', action='pull')])]
SECRET = 'DeclaredSecret9'
LR = dict(schedule='custom', cron='0 0 6 * * *', audit_retention_hour=720,
          include_event_types=['delete_artifact', 'create_artifact'])
HOOK = dict(project='fixtures-webhook', name='ci-notify', description='recorded',
            event_types=['PUSH_ARTIFACT', 'DELETE_ARTIFACT'], address='http://127.0.0.1:9/hook',
            auth_header='Bearer not-a-real-token')
RULES = [dict(template='latestPushedK', value=10),
         dict(template='nDaysSinceLastPull', value=180, repositories='app/**', tags='v*', untagged=True),
         dict(template='always', tags='tmp-*', tags_decoration='excludes', repositories_decoration='excludes',
              disabled=True)]
PULL = dict(name='rr-fixtures-pull', src_registry='rr-fixtures-self', dest_namespace='library', enabled=False,
            override=True, trigger=dict(type='manual'),
            filters=[dict(type='name', value='library/**'), dict(type='tag', value='v*', decoration='excludes')])

# A schedule's next run is Harbor's to work out.
NEXT_RUN = ('next_scheduled_time',)

# (id, module, the returned object's key, routes, arguments, the writes of a real run,
#  fields only Harbor can fill in)
CASES = [
    ('configuration-change', configuration, 'configuration', configuration_change,
     dict(settings=dict(banner_message='fixtures-system', session_timeout=45)), ['PUT'], ()),

    ('garbage_collection-create', garbage_collection, 'garbage_collection', gc_create,
     dict(schedule='custom', cron='0 0 4 * * 0', delete_untagged=True, workers=2), ['PUT'],
     # delete_tag was not declared; Harbor stores its own default for it.
     NEXT_RUN + ('delete_tag',)),
    # Check mode shows no next run for a schedule it would write, although only a setting changes.
    ('garbage_collection-change', garbage_collection, 'garbage_collection', gc_change, dict(workers=4), ['PUT'], NEXT_RUN),
    ('garbage_collection-remove', garbage_collection, 'garbage_collection', gc_remove, dict(schedule='none'), ['PUT'], ()),

    ('log_rotation-create', log_rotation, 'log_rotation', lr_create, LR, ['PUT'], NEXT_RUN),
    ('log_rotation-change', log_rotation, 'log_rotation', lr_change, dict(audit_retention_hour=168), ['PUT'], NEXT_RUN),
    ('log_rotation-remove', log_rotation, 'log_rotation', lr_remove, dict(schedule='none'), ['PUT'], ()),

    ('scan_all-create', scan_all, 'scan_all', scan_all_create, dict(schedule='custom', cron='0 0 5 * * 0'), ['PUT'], ()),
    ('scan_all-change', scan_all, 'scan_all', scan_all_change, dict(schedule='daily'), ['PUT'], ()),
    ('scan_all-remove', scan_all, 'scan_all', scan_all_remove, dict(schedule='none'), ['PUT'], ()),

    ('project-create', project, 'project', project_create,
     dict(name='fixtures-core', metadata=dict(auto_scan=True), quota_gb=5), ['POST'], ('project_id',)),
    ('project-update', project, 'project', project_update,
     dict(name='fixtures-core', public=True, metadata=dict(severity='high', auto_scan=True), quota_gb=-1),
     ['PUT', 'PUT'], ()),
    ('project-delete', project, 'project', project_delete,
     dict(name='fixtures-core', state='absent', confirm_delete=True), ['DELETE'], ()),

    ('registry-create', registry, 'registry', registry_create,
     dict(name='rr-fixtures-self', type='harbor', endpoint_url='http://proxy:8080/', insecure=True), ['POST'],
     # Harbor checks the endpoint when it stores it.
     ('id', 'status')),
    ('registry-update', registry, 'registry', registry_update,
     dict(name='rr-fixtures-self', description='updated'), ['PUT'], ()),
    ('registry-secret', registry, 'registry', registry_secret,
     dict(name='rr-fixtures-auth', access_secret='t0p-secret'), ['PUT'], ()),
    ('registry-delete', registry, 'registry', registry_delete,
     dict(name='rr-fixtures-self', state='absent'), ['DELETE'], ()),

    ('replication-create', replication, 'replication', replication_create, PULL, ['POST'], ('id',)),
    ('replication-update', replication, 'replication', replication_update,
     # The recorded rule after the update also carries the scheduled trigger of a later recorded step.
     dict(name='rr-fixtures-pull', speed=256, trigger=dict(type='scheduled', cron='0 0 3 * * *')), ['PUT'], ()),
    ('replication-delete', replication, 'replication', replication_delete,
     dict(name='rr-fixtures-pull', state='absent'), ['DELETE'], ()),

    ('robot_account-create', robot_account, 'robot_account', robot_create,
     dict(name='fixtures-robot-sys', description='pulls', permissions=PULL_ALL), ['POST'],
     # The full name carries the server's prefix; the expiry is worked out by Harbor.
     ('id', 'full_name', 'expires_at')),
    ('robot_account-create-with-secret', robot_account, 'robot_account', robot_create,
     dict(name='fixtures-robot-sys', description='pulls', permissions=PULL_ALL, secret=SECRET), ['POST', 'PATCH'],
     ('id', 'full_name', 'expires_at')),
    ('robot_account-create-in-project', robot_account, 'robot_account', robot_create_in_project,
     dict(name='ci', level='project', project='fixtures-robot', duration=30,
          permissions=[dict(access=[dict(resource='repository', action='pull')])]), ['POST'],
     ('id', 'full_name', 'expires_at')),
    ('robot_account-update', robot_account, 'robot_account', robot_update,
     dict(name='fixtures-robot-sys', description='pulls everything', update_secret='on_create', secret=SECRET,
          permissions=[dict(namespace='fixtures-robot', access=[dict(resource='repository', action='pull'),
                                                                dict(resource='repository', action='push')])]),
     ['PUT'], ()),
    ('robot_account-secret', robot_account, 'robot_account', robot_update,
     dict(name='fixtures-robot-sys', secret=SECRET), ['PATCH'], ()),
    ('robot_account-delete', robot_account, 'robot_account', robot_delete,
     dict(name='fixtures-robot-sys', state='absent'), ['DELETE'], ()),

    ('tag_immutability-create', tag_immutability, 'tag_immutability', immutability_create,
     dict(project='fixtures-tag-policy', tags='v*'), ['POST'], ('id',)),
    ('tag_immutability-create-disabled', tag_immutability, 'tag_immutability', immutability_create,
     dict(project='fixtures-tag-policy', tags='v*', disabled=True), ['POST', 'PUT'], ('id',)),
    ('tag_immutability-disable', tag_immutability, 'tag_immutability', immutability_toggle,
     dict(project='fixtures-tag-policy', tags='v*', disabled=True), ['PUT'], ()),
    ('tag_immutability-delete', tag_immutability, 'tag_immutability', immutability_delete,
     dict(project='fixtures-tag-policy', tags='v*', state='absent'), ['DELETE'], ()),

    ('tag_retention-create', tag_retention, 'tag_retention', retention_create,
     dict(project='fixtures-tag-policy', rules=RULES[:1]), ['POST'], ('id',)),
    ('tag_retention-update', tag_retention, 'tag_retention', retention_update,
     dict(project='fixtures-tag-policy', schedule='0 0 3 * * *', rules=RULES), ['PUT'], ()),
    ('tag_retention-delete', tag_retention, 'tag_retention', retention_delete,
     dict(project='fixtures-tag-policy', state='absent'), ['DELETE'], ()),

    ('webhook-create', webhook, 'webhook', webhook_create, HOOK, ['POST'], ('id',)),
    ('webhook-update', webhook, 'webhook', webhook_update,
     dict(project='fixtures-webhook', name='ci-notify', enabled=False), ['PUT'], ()),
    ('webhook-delete', webhook, 'webhook', webhook_delete,
     dict(project='fixtures-webhook', name='ci-notify', state='absent'), ['DELETE'], ()),
]

# Every module that writes has to be in the table.
MANAGE_MODULES = (configuration, garbage_collection, log_rotation, project, registry, replication, robot_account,
                  scan_all, tag_immutability, tag_retention, webhook)


def without(value, fields):
    return dict((k, v) for k, v in value.items() if k not in fields)


def test_every_manage_module_has_a_create_or_set_and_a_remove_case():
    covered = dict((module, set()) for module in MANAGE_MODULES)
    for name, module, dummy_key, dummy_routes, dummy_args, writes, dummy_assigned in CASES:
        assert name.startswith(module.__name__.rsplit('.', 1)[-1] + '-')
        covered[module].update(writes)
    for module, methods in covered.items():
        short = module.__name__.rsplit('.', 1)[-1]
        assert methods, '%s has no check-mode case' % short
        if short != 'configuration':
            # Schedules are removed with a PUT; everything else with a DELETE.
            assert 'DELETE' in methods or short in ('garbage_collection', 'log_rotation', 'scan_all'), short


@pytest.mark.parametrize('name, module, key, routes, args, writes, assigned', CASES, ids=[c[0] for c in CASES])
def test_check_mode_sends_no_write_and_reports_what_a_real_run_does(server, run_module, name, module, key, routes,
                                                                    args, writes, assigned):
    routes(server, real=False)
    check = run_module(module.main, copy.deepcopy(args), check_mode=True)
    # A write would have met no route and failed the task.
    assert check.get('failed') is not True, check.get('msg')
    assert check['changed'] is True
    assert [r['method'] for r in server.requests if r['method'] in WRITES] == []
    sent_in_check_mode = len(server.requests)

    routes(server, real=True)
    real = run_module(module.main, copy.deepcopy(args))
    assert real.get('failed') is not True, real.get('msg')
    assert [r['method'] for r in server.requests[sent_in_check_mode:] if r['method'] in WRITES] == writes

    assert real['changed'] is True
    assert without(check[key], assigned) == without(real[key], assigned)
    assert check['diff']['before'] == real['diff']['before']
    assert without(check['diff']['after'], assigned) == without(real['diff']['after'], assigned)
    for flag in ('secret_updated', 'changed_settings'):
        assert check.get(flag) == real.get(flag)
    assert not real.get('warnings') and not check.get('warnings')
    assert SECRET not in json.dumps(check) and 't0p-secret' not in json.dumps(check)
