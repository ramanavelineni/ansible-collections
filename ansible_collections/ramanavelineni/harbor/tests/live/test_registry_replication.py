# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""registry, replication and a proxy-cache project against a real Harbor.

Harbor pings an endpoint whenever it is created or changed, so the endpoints
point at the Harbor itself, by the name its proxy has inside the compose
network (http://proxy:8080). Rules are manual and disabled: nothing runs.
"""

import os

import pytest

from ansible_collections.ramanavelineni.harbor.plugins.module_utils import replication as replication_utils
from ansible_collections.ramanavelineni.harbor.plugins.modules import (
    project, project_info, registry, registry_info, replication, replication_info,
)
from ansible_collections.ramanavelineni.harbor.tests.live.conftest import PREFIX, changed

# Where Harbor reaches a registry it can ping: itself. HARBOR_LIVE_SELF_URL overrides it for a server
# that is not built from Harbor's own compose file.
SELF = os.environ.get('HARBOR_LIVE_SELF_URL') or 'http://proxy:8080'


def one(run, main, key, name):
    found = run(main, dict(name=name))
    assert not found.get('failed'), found.get('msg')
    return found[key][0] if found[key] else None


def test_registry_lifecycle(run):
    name = PREFIX + 'registry'
    wanted = dict(name=name, type='harbor', endpoint_url=SELF, insecure=True, description='made by the live suite')

    predicted = run(registry.main, wanted, check=True)
    assert changed(predicted) is True
    assert one(run, registry_info.main, 'registries', name) is None

    created = run(registry.main, wanted)
    assert changed(created) is True
    assert created['registry']['name'] == name
    assert created['registry']['url'] == SELF
    assert created['registry']['status'] == 'healthy'
    assert created['registry']['has_secret'] is False

    again = run(registry.main, wanted)
    assert changed(again) is False
    assert again['registry'] == created['registry']
    assert one(run, registry_info.main, 'registries', name) == created['registry']

    update = dict(name=name, description='changed by the live suite')
    would = run(registry.main, update, check=True)
    assert changed(would) is True
    assert one(run, registry_info.main, 'registries', name) == created['registry']
    updated = run(registry.main, update)
    assert changed(updated) is True
    assert updated['registry']['description'] == 'changed by the live suite'
    assert updated['diff']['before']['description'] == 'made by the live suite'
    assert changed(run(registry.main, update)) is False

    gone = dict(name=name, state='absent')
    assert changed(run(registry.main, gone, check=True)) is True
    assert one(run, registry_info.main, 'registries', name) is not None
    assert changed(run(registry.main, gone)) is True
    assert one(run, registry_info.main, 'registries', name) is None
    assert changed(run(registry.main, gone)) is False


def test_registry_credential(api, run):
    """A declared secret: sent once with on_create, on every run with always; never returned."""
    name = PREFIX + 'registry-auth'
    wanted = dict(name=name, type='harbor', endpoint_url=SELF, insecure=True,
                  access_key=api.username, access_secret=api.password)

    created = run(registry.main, dict(wanted, update_secret='on_create'))
    assert changed(created) is True
    assert created['secret_updated'] is True
    assert created['registry']['credential_type'] == 'basic'
    assert created['registry']['access_key'] == api.username
    assert created['registry']['has_secret'] is True
    assert created['registry']['status'] == 'healthy'
    assert api.password not in str(created)

    kept = run(registry.main, dict(wanted, update_secret='on_create'))
    assert changed(kept) is False
    assert kept['secret_updated'] is False

    resent = run(registry.main, wanted)
    assert changed(resent) is True
    assert resent['secret_updated'] is True
    assert resent['registry'] == created['registry']
    assert api.password not in str(resent)

    # Harbor checks the endpoint on every change: a wrong secret is refused, and the task says so.
    refused = run(registry.main, dict(wanted, access_secret='Not-The-Secret-1'))
    assert refused.get('failed') is True
    assert 'Not-The-Secret-1' not in str(refused)

    assert changed(run(registry.main, dict(name=name, state='absent'))) is True


def test_replication_lifecycle(run):
    source = PREFIX + 'replication-source'
    name = PREFIX + 'rule'
    assert changed(run(registry.main, dict(name=source, type='harbor', endpoint_url=SELF, insecure=True))) is True

    # The tag filter has no decoration: Harbor's own UI stores such a filter as "matches".
    wanted = dict(name=name, src_registry=source, dest_namespace='library', enabled=False, override=True,
                  trigger=dict(type='manual'),
                  filters=[dict(type='name', value='library/**'), dict(type='tag', value='v*')])
    predicted = run(replication.main, wanted, check=True)
    assert changed(predicted) is True
    assert one(run, replication_info.main, 'replications', name) is None

    created = run(replication.main, wanted)
    assert changed(created) is True
    assert created['replication']['src_registry'] == source
    assert created['replication']['dest_registry'] is None
    assert created['replication']['enabled'] is False
    assert created['replication']['trigger']['type'] == 'manual'

    again = run(replication.main, wanted)
    assert changed(again) is False
    assert again['replication'] == created['replication']
    assert one(run, replication_info.main, 'replications', name) == created['replication']

    update = dict(name=name, speed=256, trigger=dict(type='scheduled', cron='0 0 3 29 2 *'),
                  filters=[dict(type='name', value='library/**'), dict(type='tag', value='v*', decoration='excludes')])
    would = run(replication.main, update, check=True)
    assert changed(would) is True
    assert one(run, replication_info.main, 'replications', name) == created['replication']
    updated = run(replication.main, update)
    assert changed(updated) is True
    assert updated['replication']['speed'] == 256
    assert updated['replication']['trigger'] == dict(type='scheduled', cron='0 0 3 29 2 *')
    assert would['replication'] == updated['replication']
    assert changed(run(replication.main, update)) is False

    # A registry a rule uses cannot be deleted; Harbor says so and the task fails with its message.
    in_use = run(registry.main, dict(name=source, state='absent'))
    assert in_use.get('failed') is True

    gone = dict(name=name, state='absent')
    assert changed(run(replication.main, gone, check=True)) is True
    assert changed(run(replication.main, gone)) is True
    assert one(run, replication_info.main, 'replications', name) is None
    assert changed(run(replication.main, gone)) is False
    assert changed(run(registry.main, dict(name=source, state='absent'))) is True


def test_push_rule(run):
    """The other direction: from this Harbor to an endpoint."""
    target = PREFIX + 'replication-target'
    name = PREFIX + 'push-rule'
    assert changed(run(registry.main, dict(name=target, type='harbor', endpoint_url=SELF, insecure=True))) is True
    wanted = dict(name=name, dest_registry=target, dest_namespace='', enabled=False, trigger=dict(type='manual'),
                  filters=[dict(type='name', value=PREFIX + 'nothing/**')])
    created = run(replication.main, wanted)
    assert changed(created) is True
    assert created['replication']['dest_registry'] == target
    assert created['replication']['src_registry'] is None
    assert changed(run(replication.main, wanted)) is False
    assert changed(run(replication.main, dict(name=name, state='absent'))) is True
    assert changed(run(registry.main, dict(name=target, state='absent'))) is True


def test_proxy_cache_project(run):
    endpoint = PREFIX + 'proxy-endpoint'
    name = PREFIX + 'proxy-cache'
    assert changed(run(registry.main, dict(name=endpoint, type='harbor', endpoint_url=SELF, insecure=True))) is True
    wanted = dict(name=name, public=True, proxy_registry=endpoint)

    created = run(project.main, wanted)
    assert changed(created) is True
    assert created['project']['proxy_registry'] == endpoint
    assert created['project']['registry_id'] is not None
    assert changed(run(project.main, wanted)) is False
    found = run(project_info.main, dict(name=name))
    assert found['projects'] == [created['project']]

    assert changed(run(project.main, dict(name=name, state='absent', confirm_delete=True))) is True
    assert changed(run(registry.main, dict(name=endpoint, state='absent'))) is True


def test_registry_types_come_from_the_server(api):
    """GET /replication/adapters lists the registry types this Harbor replicates with."""
    offered, dummy = api.ok('GET', '/replication/adapters')
    assert isinstance(offered, list) and offered
    assert all(isinstance(kind, str) for kind in offered)
    assert 'harbor' in offered and 'docker-hub' in offered
    accepted = getattr(replication_utils, 'REGISTRY_TYPES', None)
    if accepted is None:
        pytest.skip('the module no longer keeps a list of its own to compare with')
    assert set(accepted) <= set(offered)
