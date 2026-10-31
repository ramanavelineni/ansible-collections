# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""The roles project_apply and server_apply must pass on exactly the options the modules have.

Each role keeps a list of the options an entry may use, and a task that hands
every one of them to the module. Both are checked here against the module's
real argument spec, so a module that gains or loses an option fails this test
until the role follows. The roles themselves run in CI against a Semaphore
server (tests/roles); this is what can be checked without one.

Most tests here check the text of the role's tasks, not what the tasks do.
That is deliberate: rendering a task needs ansible-core's templating, which is
GPL-3.0 and may not be imported into this Apache-2.0 repository
(CONTRIBUTING.md, "No GPL code"). The behaviour runs in tests/roles.
"""

import importlib
import os

import pytest
import yaml

from ansible_collections.ramanavelineni.semaphoreui.plugins import modules as modules_package
from ansible_collections.ramanavelineni.semaphoreui.plugins.filter import project_export
from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils.semaphore import semaphore_argument_spec

COLLECTION = 'ramanavelineni.semaphoreui'
ROLES = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'roles')

# What the role fills in itself for each module: the project, and the name the entry is keyed by.
PROJECT_SCOPE = ('project', 'project_id')
FILLED_IN = dict(
    project=(),
    key_store=PROJECT_SCOPE + ('name',),
    repository=PROJECT_SCOPE + ('name',),
    inventory=PROJECT_SCOPE + ('name',),
    variable_group=PROJECT_SCOPE + ('name',),
    view=PROJECT_SCOPE + ('name',),
    template=PROJECT_SCOPE + ('name',),
    schedule=PROJECT_SCOPE + ('name',),
    integration=PROJECT_SCOPE + ('name',),
    team_member=PROJECT_SCOPE + ('user',),
    user=('login',),
    runner=('name',),
)
# The option a task of the role sets for the entry's key, next to the options of the entry.
KEYED_BY = dict(team_member='user', user='login')


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
    return set(captured['argument_spec']) - set(semaphore_argument_spec())


def load(role, *path):
    with open(os.path.join(ROLES, role, *path)) as f:
        return yaml.safe_load(f)


def module_tasks(tasks):
    """(module name, the task's arguments, the task) for every task that calls a module of the collection."""
    found = []
    for task in tasks:
        for key, value in task.items():
            if key.startswith(COLLECTION + '.'):
                found.append((key[len(COLLECTION) + 1:], value or {}, task))
    return found


PROJECT_LISTS = load('project_apply', 'vars', 'main.yml')['__project_apply_options']
SERVER_LISTS = load('server_apply', 'vars', 'main.yml')['__server_apply_options']
ALL_LISTS = sorted(list(PROJECT_LISTS.items()) + list(SERVER_LISTS.items()))


def test_the_sections_are_the_lists():
    sections = load('project_apply', 'vars', 'main.yml')['__project_apply_sections']
    assert sorted(sections + ['project']) == sorted(PROJECT_LISTS)
    assert len(set(sections)) == len(sections)


@pytest.mark.parametrize('module, options', ALL_LISTS, ids=[name for name, dummy in ALL_LISTS])
def test_a_list_holds_the_options_of_its_module(module, options):
    assert len(set(options)) == len(options)
    assert set(options) == module_options(module) - set(FILLED_IN[module])


def create_and_delete_tasks():
    tasks = module_tasks(load('project_apply', 'tasks', 'project.yml'))
    return ([t for t in tasks if t[1].get('state') != 'absent'], [t for t in tasks if t[1].get('state') == 'absent'])


def test_every_section_is_created_and_deleted_in_opposite_orders():
    sections = load('project_apply', 'vars', 'main.yml')['__project_apply_sections']
    creates, deletes = create_and_delete_tasks()
    assert [name for name, dummy, dummy in creates] == ['project'] + sections
    assert [name for name, dummy, dummy in deletes] == list(reversed(sections))


def test_a_create_task_hands_every_option_to_the_module():
    for module, arguments, dummy in create_and_delete_tasks()[0]:
        keyed_by = KEYED_BY.get(module, 'name')
        expected = set(PROJECT_LISTS[module]) | {keyed_by}
        if module != 'project':
            expected.update(PROJECT_SCOPE)
        assert set(arguments) == expected, module
        for option in PROJECT_LISTS[module]:
            if option in ('name', 'update_secret'):
                continue
            assert '.%s | default(omit)' % option in arguments[option], (module, option)


def test_a_delete_task_names_the_entry_and_nothing_else():
    for module, arguments, task in create_and_delete_tasks()[1]:
        assert set(arguments) == set(PROJECT_SCOPE) | {KEYED_BY.get(module, 'name'), 'state'}, module
        assert "'absent'" in task.get('when', task['loop']), module


def test_deleting_entries_that_hold_secrets_loops_over_their_names_only():
    # A loop item is printed in full with -v, skipped or not, so an item with the
    # entry's value in it prints the entry's secrets. Text check, for the reason in
    # the module docstring; tests/roles/tasks/apply_output.yml checks the printed output.
    checked = []
    for module, arguments, task in create_and_delete_tasks()[1]:
        if module in ('key_store', 'variable_group'):
            checked.append(module)
            assert arguments['name'] == '{{ item }}', module
            assert task['loop'].endswith("| map(attribute='key') | list }}"), module
    assert sorted(checked) == ['key_store', 'variable_group']


def test_entries_name_their_project_by_the_id_the_project_task_returned():
    # Semaphore lists at most 200 projects, so a lookup by name fails on a
    # larger server. With the id only that project is read. The name is the
    # fallback for check mode on a project that doesn't exist yet: the project
    # task returns no id then, and each entry reports a change without comparing.
    # Text checks, for the reason in the module docstring. tests/roles/apply.yml runs them.
    tasks = module_tasks(load('project_apply', 'tasks', 'project.yml'))
    assert tasks[0][0] == 'project'
    assert tasks[0][1]['id'] == '{{ __project_apply_project.id | default(omit) }}'
    for module, arguments, dummy in tasks[1:]:
        assert arguments['project_id'] == '{{ __project_apply_done_project.project.id | default(omit) }}', module
        assert arguments['project'] == ('{{ omit if __project_apply_done_project.project.id is defined '
                                        'else __project_apply_project.name }}'), module


def test_create_tasks_skip_what_is_to_be_deleted():
    for module, dummy, task in create_and_delete_tasks()[0]:
        if module != 'project':
            assert "!= 'absent'" in task['when'], module


@pytest.mark.parametrize('module', sorted(SERVER_LISTS))
def test_a_server_task_hands_every_option_to_the_module(module):
    tasks = dict((name, arguments) for name, arguments, dummy in module_tasks(load('server_apply', 'tasks', 'main.yml')))
    arguments = tasks[module]
    assert set(arguments) == set(SERVER_LISTS[module]) | {KEYED_BY.get(module, 'name')}
    for option in SERVER_LISTS[module]:
        if option != 'update_secret':
            assert '.%s | default(omit)' % option in arguments[option], (module, option)


@pytest.mark.parametrize('role, switch, modules', [
    ('project_apply', 'project_apply_drift_check', ('key_store', 'variable_group')),
    ('server_apply', 'server_apply_drift_check', ('user',)),
])
def test_a_drift_check_sends_secrets_only_on_create(role, switch, modules):
    tasks = module_tasks(load(role, 'tasks', 'project.yml' if role == 'project_apply' else 'main.yml'))
    seen = []
    for module, arguments, dummy in tasks:
        if 'update_secret' in arguments:
            seen.append(module)
            assert arguments['update_secret'].startswith("{{ 'on_create' if %s | bool else " % switch), module
    assert sorted(seen) == sorted(modules)


@pytest.mark.parametrize('role, modules', [
    ('project_apply', ('key_store', 'variable_group', 'integration')),
    ('server_apply', ('user', 'runner')),
])
def test_tasks_that_carry_secrets_can_be_hidden(role, modules):
    tasks = module_tasks(load(role, 'tasks', 'project.yml' if role == 'project_apply' else 'main.yml'))
    for module, arguments, task in tasks:
        if module in modules and arguments.get('state') != 'absent':
            assert task['no_log'] == '{{ %s_no_log | bool }}' % role, module


@pytest.mark.parametrize('role', ['project_apply', 'server_apply'])
def test_every_variable_is_documented_with_its_default(role):
    defaults = load(role, 'defaults', 'main.yml') or {}
    options = load(role, 'meta', 'argument_specs.yml')['argument_specs']['main']['options']
    assert set(defaults) == set(name for name, option in options.items() if not option.get('required'))
    for name, value in defaults.items():
        assert options[name]['default'] == value, name
    for name in options:
        assert name.startswith(role + '_'), name


@pytest.mark.parametrize('role, shown', [('project_apply', 'webhook_urls'), ('server_apply', 'registration_token')])
def test_webhook_urls_and_registration_tokens_are_shown_only_without_no_log(role, shown):
    # A webhook URL can start a task, and a registration token can register a runner.
    tasks = load(role, 'tasks', 'project.yml' if role == 'project_apply' else 'main.yml')
    shows = [t for t in tasks if 'ansible.builtin.debug' in t and shown in t['ansible.builtin.debug']['msg']]
    assert shows, role
    for task in shows:
        # No `when`: a skipped item is printed in full with -v. The loop itself is
        # empty when no_log is on (tests/roles checks the printed output).
        assert 'when' not in task, task['name']
        assert task['loop'].startswith("{{ [] if %s_no_log | bool else" % role), task['name']


def test_the_export_writes_the_sections_apply_reads_in_its_order():
    # A section the export writes and apply doesn't know fails the apply with
    # "unknown option", and one apply knows but the export leaves out is lost
    # on a round trip. Both are lists kept by hand in two files.
    sections = load('project_apply', 'vars', 'main.yml')['__project_apply_sections']
    assert list(project_export.SECTIONS) == sections


def test_the_drift_check_sees_every_task_that_changes_something():
    # project_apply_drift_check fails the play when project_apply_changed is
    # true, and that is computed from a hand-kept list of registered results.
    # A module task missing from it changes Semaphore unseen, so the check
    # passes on drift. Read from the file: rendering the task needs GPL
    # ansible-core (module docstring), and tests/roles runs the drift check.
    tasks = load('project_apply', 'tasks', 'project.yml')
    registers = sorted(task.get('register', 'no register: %s' % task['name']) for dummy, dummy, task in module_tasks(tasks))
    noted = [t for t in tasks if 'project_apply_changed' in (t.get('ansible.builtin.set_fact') or {})]
    assert len(noted) == 1
    listed = sorted(entry.strip('{} ') for entry in noted[0]['vars']['__project_apply_results'])
    assert listed == registers
