# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""The project_export role, as far as it can be checked without running it.

Running a role takes ansible-playbook and a server; that is the role test in
tests/roles/export.yml. Here the files of the role are held against the
modules and against each other: every task that calls a module of this
collection gives it arguments the module accepts, every variable has a
default or is required, and the documentation names the variables there are.
"""

import os
import re

import pytest
import yaml

from ansible_collections.ramanavelineni.semaphoreui.plugins.filter import project_export as plugin
from ansible_collections.ramanavelineni.semaphoreui.tests.unit.plugins.modules.test_examples import (
    COLLECTION,
    ENVIRONMENT_PREFIX,
    MODULES,
    TASK_KEYWORDS,
    flatten,
    problems,
)

COLLECTION_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
ROLE = os.path.join(COLLECTION_ROOT, 'roles', 'project_export')
ROLE_TEST = os.path.join(COLLECTION_ROOT, 'tests', 'roles', 'export.yml')
# What a task of a role or of a play may hold next to the module it calls.
KEYWORDS = TASK_KEYWORDS | frozenset(('block', 'rescue', 'always'))


class Loader(yaml.SafeLoader):
    """Reads !unsafe the way Ansible does: the text, as it is."""


Loader.add_constructor('!unsafe', lambda loader, node: loader.construct_scalar(node))


def read(*path):
    with open(os.path.join(*path), encoding='utf-8') as f:
        return yaml.load(f, Loader=Loader)  # nosec B506 - a SafeLoader with one more tag


def role_tasks():
    return list(flatten(read(ROLE, 'tasks', 'main.yml')))


def play_tasks():
    plays = read(ROLE_TEST)
    assert len(plays) == 1
    return list(flatten(plays[0]['tasks']))


def calls(tasks):
    """(task name, module, arguments) for every task that calls a module of this collection."""
    found = []
    for task in tasks:
        for action in task:
            if action.startswith(COLLECTION + '.'):
                found.append((task['name'], action[len(COLLECTION) + 1:], task[action] or {}))
    return found


@pytest.fixture(autouse=True)
def no_connection_environment(monkeypatch):
    """The specs fall back to the environment; the machine's settings must not satisfy a missing option."""
    for variable in list(os.environ):
        if variable.startswith(ENVIRONMENT_PREFIX):
            monkeypatch.delenv(variable)


@pytest.mark.parametrize('tasks', [role_tasks, play_tasks], ids=['role', 'role test'])
def test_every_task_is_named_and_calls_one_thing_by_its_full_name(tasks):
    for task in tasks():
        assert isinstance(task.get('name'), str) and task['name'].strip(), 'a task without a name: %r' % (task,)
        called = [key for key in task if key not in KEYWORDS]
        assert len(called) == 1, 'task %r should call one module, found %s' % (task['name'], called)
        assert called[0].count('.') == 2, 'task %r calls %r, not a fully qualified name' % (task['name'], called[0])
        if called[0].startswith(COLLECTION + '.'):
            assert called[0][len(COLLECTION) + 1:] in MODULES + ['project_export'], called[0]


@pytest.mark.parametrize('tasks', [role_tasks, play_tasks], ids=['role', 'role test'])
def test_the_modules_accept_what_the_tasks_give_them(tasks):
    wrong = []
    for name, called, args in calls(tasks()):
        for problem in problems(called, args):
            wrong.append('task %r (%s): %s' % (name, called, problem))
    assert not wrong, '\n'.join(wrong)


def test_the_role_reads_every_section_and_writes_none():
    called = [module for dummy, module, dummy_args in calls(role_tasks())]
    assert sorted(called) == sorted(['project_info'] + ['%s_info' % section for section in plugin.SECTIONS])
    # By its id, so that a project past the cap of the project list can be exported too.
    for name, module, args in calls(role_tasks()):
        if module != 'project_info':
            assert list(args) == ['project_id'], name


def test_the_role_test_makes_one_object_of_every_kind():
    called = set(module for dummy, module, dummy_args in calls(play_tasks()))
    assert set(plugin.SECTIONS) | set(['project']) <= called | set(['team_member'])


def test_every_variable_is_documented_and_has_a_default_or_is_required():
    defaults = read(ROLE, 'defaults', 'main.yml')
    spec = read(ROLE, 'meta', 'argument_specs.yml')['argument_specs']['main']
    options = spec['options']
    assert all(name.startswith('project_export_') for name in options)
    required = sorted(name for name, option in options.items() if option.get('required'))
    assert required == ['project_export_dest']
    assert sorted(defaults) == sorted(name for name in options if name not in required)
    for name, value in defaults.items():
        assert options[name]['default'] == value, name
        assert options[name]['description']
    assert options['project_export_layout']['choices'] == ['file', 'directory']
    assert spec['version_added'] and spec['short_description'] and spec['author']


def test_the_readme_names_the_variables_there_are():
    options = read(ROLE, 'meta', 'argument_specs.yml')['argument_specs']['main']['options']
    with open(os.path.join(ROLE, 'README.md'), encoding='utf-8') as f:
        readme = f.read()
    for name in options:
        assert '`%s`' % name in readme, name


def test_the_tasks_use_only_variables_the_role_has():
    """A variable named project_export_… in a task is one of the documented ones, or the role's own (two underscores)."""
    options = set(read(ROLE, 'meta', 'argument_specs.yml')['argument_specs']['main']['options'])
    with open(os.path.join(ROLE, 'tasks', 'main.yml'), encoding='utf-8') as f:
        text = f.read()
    used = set(re.findall(r'(?<![A-Za-z0-9_.])(project_export_[a-z_]+)', text))
    filters = set(plugin.FilterModule().filters())
    assert used - filters <= options, sorted(used - filters - options)


def test_the_filters_the_role_uses_exist_and_have_documentation():
    filters = plugin.FilterModule().filters()
    assert sorted(filters) == ['project_export_config', 'project_export_vault', 'project_export_vault_variables',
                               'project_export_yaml']
    with open(os.path.join(ROLE, 'tasks', 'main.yml'), encoding='utf-8') as f:
        text = f.read()
    for name in filters:
        documented = read(COLLECTION_ROOT, 'plugins', 'filter', name + '.yml')
        assert documented['DOCUMENTATION']['name'] == name
        assert sorted(documented) == ['DOCUMENTATION', 'EXAMPLES', 'RETURN']
        assert '_input' in documented['DOCUMENTATION']['options']
    for used in ('project_export_yaml', 'project_export_vault', 'project_export_vault_variables'):
        assert 'ramanavelineni.semaphoreui.%s' % used in text
    parts = read(COLLECTION_ROOT, 'plugins', 'filter', 'project_export_yaml.yml')['DOCUMENTATION']['options']['part']
    assert parts['choices'] == ['project'] + list(plugin.SECTIONS)
