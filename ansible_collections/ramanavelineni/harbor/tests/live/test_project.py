# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""project and project_info against a real Harbor."""

from ansible_collections.ramanavelineni.harbor.plugins.modules import project, project_info
from ansible_collections.ramanavelineni.harbor.tests.live.conftest import PREFIX, changed

NAME = PREFIX + 'lifecycle'


def shown(run, name=NAME):
    """The project as project_info shows it, or None."""
    found = run(project_info.main, dict(name=name))
    assert not found.get('failed'), found.get('msg')
    return found['projects'][0] if found['projects'] else None


def test_project_lifecycle(api, run):
    wanted = dict(name=NAME, public=False, metadata=dict(auto_scan=True, severity='high'), quota_gb=2)

    # Check mode says what would happen and creates nothing.
    predicted = run(project.main, wanted, check=True)
    assert changed(predicted) is True
    assert shown(run) is None

    created = run(project.main, wanted)
    assert changed(created) is True
    assert created['project']['name'] == NAME
    assert created['project']['public'] is False
    assert created['project']['quota_gb'] == 2
    # Metadata comes back as Harbor stores it: strings.
    assert created['project']['metadata']['auto_scan'] == 'true'
    assert created['project']['metadata']['severity'] == 'high'
    # What check mode predicted is what the real run returned, apart from the id only Harbor can give.
    assert dict(predicted['project'], project_id=None) == dict(created['project'], project_id=None)

    # The real proof of idempotence: Harbor stored what was sent, so a second run has nothing to do.
    again = run(project.main, wanted)
    assert changed(again) is False
    assert again['project'] == created['project']

    # project_info returns the same shape and the same values.
    assert shown(run) == created['project']

    update = dict(name=NAME, public=True, metadata=dict(auto_scan=False), quota_gb=3)
    would = run(project.main, update, check=True)
    assert changed(would) is True
    assert shown(run) == created['project']

    updated = run(project.main, update)
    assert changed(updated) is True
    assert would['project'] == updated['project']
    assert updated['project']['public'] is True
    assert updated['project']['quota_gb'] == 3
    assert updated['project']['metadata']['auto_scan'] == 'false'
    assert updated['project']['metadata']['severity'] == 'high'
    assert updated['diff']['before']['public'] is False
    assert updated['diff']['after']['public'] is True
    assert changed(run(project.main, update)) is False
    assert shown(run) == updated['project']

    # Deleting needs confirm_delete; without it nothing is deleted.
    refused = run(project.main, dict(name=NAME, state='absent'))
    assert refused.get('failed') is True
    assert shown(run) is not None

    gone = dict(name=NAME, state='absent', confirm_delete=True)
    assert changed(run(project.main, gone, check=True)) is True
    assert shown(run) is not None
    assert changed(run(project.main, gone)) is True
    assert shown(run) is None
    assert changed(run(project.main, gone)) is False
    assert api.projects(NAME) == []


def test_project_info_lists_the_built_in_project(run):
    """Without a name every project is returned; `library` is always there."""
    found = run(project_info.main, dict())
    assert not found.get('failed'), found.get('msg')
    assert 'library' in [p['name'] for p in found['projects']]
