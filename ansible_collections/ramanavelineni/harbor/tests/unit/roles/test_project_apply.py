# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""The role project_apply must pass on exactly the options the modules have.

The role keeps a list of the options an entry may use, and a task that hands
every one of them to the module. Both are checked here against the module's
real argument spec, so a module that gains or loses an option fails this test
until the role follows. The role itself runs in CI against a Harbor server
(tests/roles); this is what can be checked without one.

The tests check the text of the role's files, not what the tasks do. That is
deliberate: rendering a task needs ansible-core's templating, which is GPL-3.0
and may not be imported into this Apache-2.0 repository (CONTRIBUTING.md, "No
GPL code"). The behaviour runs in tests/roles.
"""

import importlib
import os

import pytest
import yaml

from ansible_collections.ramanavelineni.harbor.plugins import modules as modules_package
from ansible_collections.ramanavelineni.harbor.plugins.module_utils.harbor import harbor_argument_spec

COLLECTION = 'ramanavelineni.harbor'
ROLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'roles', 'project_apply')

# What the role fills in itself for each module: the project, the name a keyed
# entry is keyed by, and a robot account's level.
FILLED_IN = dict(
    project=(),
    robot_account=('project', 'name', 'level'),
    project_member=('project',),
    tag_retention=('project',),
    tag_immutability=('project',),
    webhook=('project', 'name'),
)
# The options a delete task sends: what finds the object, and state.
DELETE_ARGUMENTS = dict(
    robot_account={'project', 'level', 'name', 'state'},
    project_member={'project', 'user', 'group', 'group_type', 'state'},
    tag_retention={'project', 'state'},
    tag_immutability={'project', 'repositories', 'repositories_decoration', 'tags', 'tags_decoration', 'state'},
    webhook={'project', 'name', 'state'},
)


class SpecCaptured(Exception):
    """Stops main() once AnsibleModule has been given the argument spec."""


def module_options(name):
    """The options of module `name` that are its own, without the connection options."""
    module = importlib.import_module('%s.%s' % (modules_package.__name__, name))
    captured = {}

    def stand_in(**kwargs):
        captured.update(kwargs)
        raise SpecCaptured()

    real = module.AnsibleModule
    module.AnsibleModule = stand_in
    try:
        with pytest.raises(SpecCaptured):
            module.main()
    finally:
        module.AnsibleModule = real
    return set(captured['argument_spec']) - set(harbor_argument_spec())


def load(*path):
    with open(os.path.join(ROLE, *path)) as f:
        return yaml.safe_load(f)


def module_tasks(tasks):
    """(module name, the task's arguments, the task) for every task that calls a module of the collection."""
    found = []
    for task in tasks:
        for key, value in task.items():
            if key.startswith(COLLECTION + '.'):
                found.append((key[len(COLLECTION) + 1:], value or {}, task))
    return found


ROLE_VARS = load('vars', 'main.yml')
SECTIONS = ROLE_VARS['__project_apply_sections']
KINDS = ROLE_VARS['__project_apply_section_kinds']
LISTS = ROLE_VARS['__project_apply_options']


def create_and_delete_tasks():
    tasks = module_tasks(load('tasks', 'project.yml'))
    return ([t for t in tasks if t[1].get('state') != 'absent'], [t for t in tasks if t[1].get('state') == 'absent'])


def test_the_sections_are_the_lists_and_the_kinds():
    assert sorted(SECTIONS + ['project']) == sorted(LISTS)
    assert len(set(SECTIONS)) == len(SECTIONS)
    assert sorted(KINDS) == sorted(SECTIONS)
    assert set(KINDS.values()) <= {'keyed', 'list', 'single'}


@pytest.mark.parametrize('module', sorted(LISTS))
def test_a_list_holds_the_options_of_its_module(module):
    options = LISTS[module]
    assert len(set(options)) == len(options)
    assert set(options) == module_options(module) - set(FILLED_IN[module])


def test_sections_are_created_in_order_and_deleted_in_reverse():
    # The order the user agreed: project, robot accounts, members, retention,
    # immutability, webhooks.
    assert SECTIONS == ['robot_account', 'project_member', 'tag_retention', 'tag_immutability', 'webhook']
    creates, deletes = create_and_delete_tasks()
    assert [name for name, dummy, dummy in creates] == ['project'] + SECTIONS
    assert [name for name, dummy, dummy in deletes] == list(reversed(SECTIONS))


def test_a_create_task_hands_every_option_to_the_module():
    for module, arguments, dummy in create_and_delete_tasks()[0]:
        assert set(arguments) == set(LISTS[module]) | set(FILLED_IN[module]), module
        for option in LISTS[module]:
            if option in ('name', 'update_secret'):
                continue
            assert '.%s | default(omit)' % option in arguments[option], (module, option)


def test_a_robot_account_is_a_project_robot_account():
    for module, arguments, dummy in module_tasks(load('tasks', 'project.yml')):
        if module == 'robot_account':
            assert arguments['level'] == 'project'
            assert arguments['project'] == '{{ __project_apply_project.name }}'


def test_a_delete_task_names_the_entry_and_nothing_else():
    for module, arguments, task in create_and_delete_tasks()[1]:
        assert set(arguments) == DELETE_ARGUMENTS[module], module
        assert "'absent'" in task.get('when', task.get('loop', '')), module


def test_deleting_entries_that_hold_secrets_loops_over_their_names_only():
    # A loop item is printed in full with -v, skipped or not, so an item with the
    # entry's value in it prints a robot secret or a webhook's auth header.
    checked = []
    for module, arguments, task in create_and_delete_tasks()[1]:
        if module in ('robot_account', 'webhook'):
            checked.append(module)
            assert arguments['name'] == '{{ item }}', module
            assert task['loop'].endswith("| map(attribute='key') | list }}"), module
            assert 'when' not in task, module
    assert sorted(checked) == ['robot_account', 'webhook']


def test_create_tasks_skip_what_is_to_be_deleted():
    for module, dummy, task in create_and_delete_tasks()[0]:
        if module != 'project':
            whens = task['when'] if isinstance(task['when'], list) else [task['when']]
            assert any("!= 'absent'" in when for when in whens), module


def test_a_drift_check_sends_robot_secrets_only_on_create():
    seen = []
    for module, arguments, dummy in module_tasks(load('tasks', 'project.yml')):
        if 'update_secret' in arguments:
            seen.append(module)
            assert arguments['update_secret'].startswith("{{ 'on_create' if project_apply_drift_check | bool else "), module
    assert seen == ['robot_account']


def test_tasks_that_carry_secrets_can_be_hidden():
    for module, arguments, task in create_and_delete_tasks()[0]:
        if module in ('robot_account', 'webhook'):
            assert task['no_log'] == '{{ project_apply_no_log | bool }}', module
    for name in ('load.yml', 'project.yml'):
        for task in load('tasks', name):
            facts = task.get('ansible.builtin.set_fact') or {}
            if '__project_apply_loaded' in facts or '__project_apply_project' in facts:
                assert task['no_log'] == '{{ project_apply_no_log | bool }}', task['name']


def test_every_variable_is_documented_with_its_default():
    defaults = load('defaults', 'main.yml') or {}
    options = load('meta', 'argument_specs.yml')['argument_specs']['main']['options']
    assert set(defaults) == set(name for name, option in options.items() if not option.get('required'))
    for name, value in defaults.items():
        assert options[name]['default'] == value, name
    for name in options:
        assert name.startswith('project_apply_'), name


def test_every_project_is_checked_before_the_first_is_applied():
    # A mistake in a later project must stop the role before an earlier one
    # changes Harbor (tests/roles/project_duplicate.yml runs it).
    tasks = load('tasks', 'main.yml')
    names = [task['name'] for task in tasks]
    apply = names.index('Apply each project')
    assert names.index('Read each project') < apply
    for index, task in enumerate(tasks):
        if 'ansible.builtin.assert' in task:
            assert index < apply, task['name']


def test_the_drift_check_sees_every_task_that_changes_something():
    # project_apply_drift_check fails the play when project_apply_changed is
    # true, and that is computed from a hand-kept list of registered results.
    # A module task missing from it changes Harbor unseen, so the check passes
    # on drift.
    tasks = load('tasks', 'project.yml')
    registers = sorted(task.get('register', 'no register: %s' % task['name']) for dummy, dummy, task in module_tasks(tasks))
    noted = [t for t in tasks if 'project_apply_changed' in (t.get('ansible.builtin.set_fact') or {})]
    assert len(noted) == 1
    listed = sorted(entry.strip('{} ') for entry in noted[0]['vars']['__project_apply_results'])
    assert listed == registers
