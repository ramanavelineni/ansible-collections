# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""Every module that works in a project takes project and project_id the same way.

The docs come from the doc fragment project (or project.optional), and the
argument spec and its rules from project_argument_spec() and
semaphore_module_kwargs(project=...). A module that goes back to its own copy
of the options, or whose rules differ from what its docs say, fails here.
ansible-test sanity (validate-modules) then checks the merged docs against
the spec.
"""

import importlib

import pytest
import yaml

from ansible.module_utils.common.arg_spec import ArgumentSpecValidator

from ansible_collections.ramanavelineni.semaphoreui.plugins import modules as modules_package
from ansible_collections.ramanavelineni.semaphoreui.tests.unit.plugins.modules.test_examples import MODULES, module_spec

REQUIRED = 'ramanavelineni.semaphoreui.project'
OPTIONAL = 'ramanavelineni.semaphoreui.project.optional'

# module: (its fragment, the release that added project_id to it). project_id
# came in 0.3.0, except in the modules that are new in 0.4.0 and had it from
# the start (changelogs/changelog.yaml).
TAKES_A_PROJECT = dict(
    event_info=(OPTIONAL, '0.4.0'),
    integration=(REQUIRED, '0.3.0'),
    integration_info=(REQUIRED, '0.3.0'),
    inventory=(REQUIRED, '0.3.0'),
    inventory_info=(REQUIRED, '0.3.0'),
    key_store=(REQUIRED, '0.3.0'),
    key_store_info=(REQUIRED, '0.3.0'),
    project_backup=(REQUIRED, '0.4.0'),
    repository=(REQUIRED, '0.3.0'),
    repository_info=(REQUIRED, '0.3.0'),
    runner=(OPTIONAL, '0.3.0'),
    runner_info=(OPTIONAL, '0.3.0'),
    schedule=(REQUIRED, '0.3.0'),
    schedule_info=(REQUIRED, '0.3.0'),
    task=(REQUIRED, '0.4.0'),
    task_info=(REQUIRED, '0.4.0'),
    team_member=(REQUIRED, '0.3.0'),
    team_member_info=(REQUIRED, '0.3.0'),
    template=(REQUIRED, '0.3.0'),
    template_info=(REQUIRED, '0.3.0'),
    variable_group=(REQUIRED, '0.3.0'),
    variable_group_info=(REQUIRED, '0.3.0'),
    view=(REQUIRED, '0.3.0'),
    view_info=(REQUIRED, '0.3.0'),
)
NAMES = sorted(TAKES_A_PROJECT)


def documentation(name):
    module = importlib.import_module('%s.%s' % (modules_package.__name__, name))
    return yaml.safe_load(module.DOCUMENTATION)


def errors(name, args):
    """What argument validation says about `args` (the connection options set) for module `name`."""
    kwargs = module_spec(name)
    rules = dict((rule, kwargs[rule]) for rule in ('mutually_exclusive', 'required_one_of') if kwargs.get(rule))
    args = dict(dict(url='https://semaphore.example.com', api_token='t'), **args)
    # Only the project rules: what else a module requires is not the point here.
    spec = dict((key, dict(value, required=False)) for key, value in kwargs['argument_spec'].items())
    return ArgumentSpecValidator(spec, **rules).validate(args).error_messages


def test_every_module_that_takes_a_project_is_in_the_table():
    """A new module with project or project_id must be added above, with its fragment and release."""
    found = [name for name in MODULES if set(module_spec(name)['argument_spec']) & {'project', 'project_id'}]
    assert found == NAMES


@pytest.mark.parametrize('name', NAMES)
def test_docs_come_from_the_fragment_and_keep_the_release_of_project_id(name):
    """Breaks when a module documents project or project_id itself again, or names the wrong release."""
    fragment, release = TAKES_A_PROJECT[name]
    doc = documentation(name)
    assert fragment in doc['extends_documentation_fragment']
    other = ({REQUIRED, OPTIONAL} - {fragment}).pop()
    assert other not in doc['extends_documentation_fragment']
    assert 'project' not in doc['options']
    # Only the release: the description and type come from the fragment.
    assert doc['options']['project_id'] == dict(version_added=release)


@pytest.mark.parametrize('name', NAMES)
def test_the_argument_spec_is_the_shared_one(name):
    spec = module_spec(name)['argument_spec']
    assert spec['project'] == dict(type='str')
    assert spec['project_id'] == dict(type='int')


@pytest.mark.parametrize('name', NAMES)
def test_project_and_project_id_exclude_each_other(name):
    assert errors(name, dict(project='homelab', project_id=1)) == [
        'parameters are mutually exclusive: project|project_id']


@pytest.mark.parametrize('name', NAMES)
def test_a_project_is_required_where_the_docs_say_so(name):
    """The fragment project says one of the two is required, project.optional says both are optional."""
    fragment = TAKES_A_PROJECT[name][0]
    expected = ['one of the following is required: project, project_id'] if fragment == REQUIRED else []
    assert errors(name, {}) == expected
    assert errors(name, dict(project='homelab')) == []
    assert errors(name, dict(project_id=1)) == []
