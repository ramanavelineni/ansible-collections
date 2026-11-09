# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""The role server_apply must pass on exactly the options the modules have.

The role keeps a list of the options each variable may use, and a task that
hands every one of them to the module. Both are checked here against the
module's real argument spec, so a module that gains or loses an option fails
this test until the role follows. The role itself runs in CI against a Harbor
server (tests/roles/server_apply.yml); this is what can be checked without one.

Most tests here check the text of the role's tasks, not what the tasks do.
That is deliberate: rendering a task needs ansible-core's templating, which is
GPL-3.0 and may not be imported into this Apache-2.0 repository
(CONTRIBUTING.md, "No GPL code"). The behaviour runs in tests/roles.
"""

import importlib
import os

import pytest
import yaml

from ansible_collections.ramanavelineni.harbor.plugins import modules as modules_package
from ansible_collections.ramanavelineni.harbor.plugins.module_utils.harbor import harbor_argument_spec

COLLECTION = 'ramanavelineni.harbor'
ROLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'roles', 'server_apply')

# What the role fills in itself for each module: the name an entry is keyed
# by, and a robot account's level (always system) and project (none).
FILLED_IN = dict(
    configuration=(),
    garbage_collection=(),
    scan_all=(),
    log_rotation=(),
    registry=('name',),
    replication=('name',),
    robot_account=('name', 'level', 'project'),
)
# The modules that take one dictionary, and the variable that holds it.
SINGLE = dict(
    configuration='server_apply_configuration',
    garbage_collection='server_apply_garbage_collection',
    scan_all='server_apply_scan_all',
    log_rotation='server_apply_log_rotation',
)
# The modules whose entries are keyed by name, in the order they are created.
KEYED = ['registry', 'replication', 'robot_account']
# The modules whose options hold secrets.
WITH_SECRETS = ['configuration', 'registry', 'robot_account']


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


def module_tasks():
    """(module name, the task's arguments, the task) for every task that calls a module of the collection."""
    found = []
    for task in load('tasks', 'main.yml'):
        for key, value in task.items():
            if key.startswith(COLLECTION + '.'):
                found.append((key[len(COLLECTION) + 1:], value or {}, task))
    return found


LISTS = load('vars', 'main.yml')['__server_apply_options']


def creates():
    return [t for t in module_tasks() if t[0] != 'info' and t[1].get('state') != 'absent']


def deletes():
    return [t for t in module_tasks() if t[1].get('state') == 'absent']


def test_every_module_has_a_list():
    assert sorted(LISTS) == sorted(FILLED_IN)


@pytest.mark.parametrize('module', sorted(FILLED_IN))
def test_a_list_holds_the_options_of_its_module(module):
    options = LISTS[module]
    assert len(set(options)) == len(options)
    assert set(options) == module_options(module) - set(FILLED_IN[module])


def test_objects_are_created_in_dependency_order_and_deleted_in_reverse():
    # A replication names registries, so a registry is created before it and
    # deleted after it; Harbor refuses to delete a registry a rule uses.
    assert [name for name, dummy, dummy in creates()] == list(SINGLE) + KEYED
    assert [name for name, dummy, dummy in deletes()] == list(reversed(KEYED))


def test_a_create_task_hands_every_option_to_the_module():
    for module, arguments, task in creates():
        expected = set(LISTS[module]) | set(FILLED_IN[module]) - {'project'}
        assert set(arguments) == expected, module
        source = '%s.' % SINGLE[module] if module in SINGLE else ').'
        for option in LISTS[module]:
            if option == 'update_secret':
                continue
            assert '%s%s | default(omit)' % (source, option) in arguments[option], (module, option)


def test_robot_accounts_are_system_robot_accounts():
    # A project robot account belongs to project_apply's side; this role makes system ones only.
    robots = [arguments for module, arguments, dummy in module_tasks() if module == 'robot_account']
    assert len(robots) == 2
    for arguments in robots:
        assert arguments['level'] == 'system'
        assert 'project' not in arguments


def test_an_empty_single_variable_is_not_managed():
    # scan_all in particular: without a scanner Harbor refuses even the read.
    for module, dummy, task in creates():
        if module in SINGLE:
            assert task['when'] == '%s | default({}, true) | length > 0' % SINGLE[module], module


def test_create_tasks_skip_what_is_to_be_deleted():
    for module, dummy, task in creates():
        if module in KEYED:
            assert "!= 'absent'" in task['when'], module


def test_a_delete_task_names_the_entry_and_loops_over_names_only():
    # A loop item is printed in full with -v, skipped or not, so an item with
    # the entry's value in it would print the entry's secrets.
    for module, arguments, task in deletes():
        assert arguments['name'] == '{{ item }}', module
        assert set(arguments) == {'name', 'state'} | ({'level'} if module == 'robot_account' else set()), module
        assert "selectattr('value.state', 'equalto', 'absent')" in task['loop'], module
        assert task['loop'].endswith("| map(attribute='key') | list }}"), module
        assert 'no_log' not in task, module


def test_a_drift_check_sends_secrets_only_on_create():
    seen = []
    for module, arguments, dummy in creates():
        if 'update_secret' in arguments:
            seen.append(module)
            assert arguments['update_secret'].startswith("{{ 'on_create' if server_apply_drift_check | bool else "), module
    assert sorted(seen) == sorted(WITH_SECRETS)


def test_tasks_that_carry_secrets_can_be_hidden():
    seen = []
    for module, dummy, task in creates():
        if module in WITH_SECRETS:
            seen.append(module)
            assert task['no_log'] == '{{ server_apply_no_log | bool }}', module
    assert sorted(seen) == sorted(WITH_SECRETS)


def test_generated_robot_secrets_are_shown_only_without_no_log():
    # A robot secret logs in to Harbor.
    tasks = load('tasks', 'main.yml')
    shows = [t for t in tasks if 'ansible.builtin.debug' in t and 'item.secret' in t['ansible.builtin.debug']['msg']]
    assert len(shows) == 1
    # No `when`: a skipped item is printed in full with -v. The loop itself is empty when no_log is on.
    assert 'when' not in shows[0]
    assert shows[0]['loop'].startswith('{{ [] if server_apply_no_log | bool else')


def test_every_variable_is_documented_with_its_default():
    defaults = load('defaults', 'main.yml')
    options = load('meta', 'argument_specs.yml')['argument_specs']['main']['options']
    assert set(defaults) == set(options)
    for name, value in defaults.items():
        assert options[name]['default'] == value, name
        assert name.startswith('server_apply_'), name


def test_the_unknown_option_check_covers_every_variable():
    # A variable missing from the check passes misspelled options to nothing:
    # its task reads only the options it knows, so a typo is silently dropped.
    check = [t for t in load('tasks', 'main.yml') if t['name'] == 'Check the option names'][0]
    single = check['vars']['__server_apply_single']
    keyed = check['vars']['__server_apply_keyed']
    assert sorted(single) == sorted(SINGLE)
    for module, variable in SINGLE.items():
        assert single[module] == '{{ %s | default({}, true) }}' % variable
    assert sorted(keyed) == sorted(KEYED)
    checked = [value.strip('{} ').split(' |')[0] for value in list(single.values()) + list(keyed.values())]
    variables = [n for n in load('defaults', 'main.yml') if n not in ('server_apply_drift_check', 'server_apply_no_log')]
    assert sorted(checked) == sorted(variables)


def test_the_drift_check_sees_every_task_that_changes_something():
    # server_apply_drift_check fails the play when server_apply_changed is
    # true, and that is computed from a hand-kept list of registered results.
    # A module task missing from it changes Harbor unseen.
    tasks = load('tasks', 'main.yml')
    registers = sorted(task['register'] for module, dummy, task in module_tasks() if module != 'info')
    noted = [t for t in tasks if 'server_apply_changed' in (t.get('ansible.builtin.set_fact') or {})]
    assert len(noted) == 1
    listed = sorted(entry.strip('{} ') for entry in noted[0]['vars']['__server_apply_results'])
    assert listed == registers
