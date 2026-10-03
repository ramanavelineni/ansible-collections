# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""The tasks in every module's EXAMPLES must be tasks the modules accept.

Sanity only parses EXAMPLES as YAML. Here every task that calls a module of
this collection is checked against that module's real argument spec and its
rules between options: an unknown option, a wrong type, a value outside the
choices, a missing required option or a broken rule fails the test.

The argument spec is taken from the module itself: main() is called with
AnsibleModule replaced by a stand-in that keeps what it was given and stops.
"""

import copy
import importlib
import os
import re

import pytest
import yaml

from ansible.module_utils.common.arg_spec import ArgumentSpecValidator

from ansible_collections.ramanavelineni.semaphoreui.plugins import modules as modules_package

COLLECTION = 'ramanavelineni.semaphoreui'
MODULES = sorted(name[:-3] for name in os.listdir(list(modules_package.__path__)[0])
                 if name.endswith('.py') and name != '__init__.py')

# The EXAMPLES say that the connection options come from module_defaults or
# the environment. A task that leaves these out is given a stand-in value, so
# "required" still holds for every other option.
CONNECTION_FROM_DEFAULTS = dict(url='https://semaphore.example.com')
ENVIRONMENT_PREFIX = 'SEMAPHORE_'

# What a task may hold next to the module it calls.
TASK_KEYWORDS = frozenset((
    'name', 'register', 'when', 'loop', 'loop_control', 'vars', 'no_log', 'args', 'delegate_to', 'run_once',
    'check_mode', 'diff', 'environment', 'changed_when', 'failed_when', 'ignore_errors', 'tags', 'notify',
    'become', 'until', 'retries', 'delay', 'module_defaults',
))
BLOCK_KEYWORDS = ('block', 'rescue', 'always')

JINJA = re.compile(r'\{\{.*\}\}', re.S)
PLACEHOLDER = re.compile(r'^<[^<>]+>$')
# What a templated value is replaced by before the types are checked.
STAND_INS = dict(int=0, float=0.0, bool=True, list=[], dict={})
SPEC_RULES = ('mutually_exclusive', 'required_together', 'required_one_of', 'required_if', 'required_by')


class SpecCaptured(Exception):
    """Stops main() once AnsibleModule has been given the argument spec."""


def module_spec(name):
    """The keyword arguments module `name` builds its AnsibleModule with."""
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
    return captured


def flatten(tasks):
    for task in tasks:
        nested = [key for key in BLOCK_KEYWORDS if key in task]
        if nested:
            for key in nested:
                for inner in flatten(task[key]):
                    yield inner
        else:
            yield task


def example_tasks(name):
    module = importlib.import_module('%s.%s' % (modules_package.__name__, name))
    examples = yaml.safe_load(module.EXAMPLES)
    assert isinstance(examples, list), 'EXAMPLES of %s is not a list of tasks' % name
    return list(flatten(examples))


def actions(task):
    return [key for key in task if key not in TASK_KEYWORDS]


def collection_tasks(name):
    """(task name, called module, its arguments) for every task that calls this collection."""
    found = []
    for task in example_tasks(name):
        for action in actions(task):
            if action.startswith(COLLECTION + '.'):
                found.append((task.get('name'), action[len(COLLECTION) + 1:], task[action] or {}))
    return found


def templated(value):
    return isinstance(value, str) and bool(JINJA.search(value))


def without_templates(args, spec, skipped):
    """`args` with every templated value replaced by one the option's type takes.

    A template has no type until it is rendered, so its type and choices can't
    be checked. Each replacement is added to `skipped`. Text options keep
    their value: a template is text.
    """
    out = {}
    for key, value in args.items():
        option = spec.get(key) or {}
        kind = option.get('type', 'str')
        if templated(value) and (kind not in ('str', 'raw', 'path') or option.get('choices')):
            skipped.append(key)
            if option.get('choices'):
                value = option['choices'][0]
            elif option.get('options'):
                # Suboptions can't be made up. Take the option out of the
                # check and of "required", and leave the rest of the task in.
                spec[key] = dict(type='raw', required=option.get('required', False))
            else:
                value = copy.deepcopy(STAND_INS.get(kind, value))
        elif isinstance(value, dict) and option.get('options'):
            value = without_templates(value, option['options'], skipped)
        elif isinstance(value, list):
            items = []
            for item in value:
                if isinstance(item, dict) and option.get('options'):
                    item = without_templates(item, option['options'], skipped)
                elif templated(item) and option.get('elements', 'str') not in ('str', 'raw', 'path'):
                    skipped.append(key)
                    item = copy.deepcopy(STAND_INS.get(option['elements'], item))
                items.append(item)
            value = items
        out[key] = value
    return out


def problems(called, args, skipped=None):
    """What AnsibleModule would refuse in `args` for module `called`."""
    kwargs = module_spec(called)
    spec = copy.deepcopy(kwargs['argument_spec'])
    args = without_templates(args, spec, [] if skipped is None else skipped)
    for option, value in CONNECTION_FROM_DEFAULTS.items():
        if option in spec:
            args.setdefault(option, value)
    rules = dict((rule, kwargs[rule]) for rule in SPEC_RULES if kwargs.get(rule))
    return ArgumentSpecValidator(spec, **rules).validate(args).error_messages


def secret_literals(args, spec, path=''):
    """Options marked no_log whose value is written out instead of templated."""
    found = []
    for key, value in args.items():
        option = spec.get(key) or {}
        if option.get('no_log') is True and isinstance(value, str) and not (templated(value) or PLACEHOLDER.match(value)):
            found.append(path + key)
        if option.get('options'):
            for item in value if isinstance(value, list) else [value]:
                if isinstance(item, dict):
                    found.extend(secret_literals(item, option['options'], path + key + '.'))
    return found


@pytest.fixture(autouse=True)
def no_connection_environment(monkeypatch):
    """The spec's environment fallbacks must not let the machine's settings in."""
    for variable in list(os.environ):
        if variable.startswith(ENVIRONMENT_PREFIX):
            monkeypatch.delenv(variable)


@pytest.mark.parametrize('name', MODULES)
def test_examples_are_named_tasks_that_call_modules_by_fqcn(name):
    for task in example_tasks(name):
        assert isinstance(task.get('name'), str) and task['name'].strip(), 'a task without a name: %r' % (task,)
        called = actions(task)
        assert len(called) == 1, 'task %r should call one module, found %s' % (task['name'], called)
        assert called[0].count('.') == 2, 'task %r calls %r, not a fully qualified name' % (task['name'], called[0])
        if called[0].startswith(COLLECTION + '.'):
            assert called[0][len(COLLECTION) + 1:] in MODULES, 'task %r calls %r, which does not exist' % (
                task['name'], called[0])


@pytest.mark.parametrize('name', MODULES)
def test_examples_show_the_module_itself(name):
    assert name in [called for dummy, called, dummy_args in collection_tasks(name)]


@pytest.mark.parametrize('name', MODULES)
def test_example_arguments_fit_the_argument_spec(name):
    wrong = []
    for task_name, called, args in collection_tasks(name):
        for problem in problems(called, args):
            wrong.append('%s, task %r (%s): %s' % (name, task_name, called, problem))
    assert not wrong, '\n'.join(wrong)


@pytest.mark.parametrize('name', MODULES)
def test_example_secrets_are_templated(name):
    """A secret in an example is a variable ("{{ ... }}") or a placeholder ("<...>"), never a value."""
    written_out = []
    for task_name, called, args in collection_tasks(name):
        for option in secret_literals(args, module_spec(called)['argument_spec']):
            written_out.append('%s, task %r: %s' % (name, task_name, option))
    assert not written_out, '\n'.join(written_out)


def test_the_check_itself_refuses_what_ansible_refuses():
    """The helpers above, on arguments that are wrong in each way they look for."""
    good = dict(project='homelab', name='infra')
    assert problems('view', dict(good)) == []
    assert 'no_such_option' in problems('view', dict(good, no_such_option=1))[0]
    assert 'name' in problems('view', dict((k, v) for k, v in good.items() if k != 'name'))[0]
    assert 'state' in problems('view', dict(good, state='gone'))[0]
    assert 'position' in problems('view', dict(good, position='first'))[0]
    assert 'mutually exclusive' in problems('view', dict(good, project_id=1))[0]
    # A template stands for a value of any type, and each one is counted.
    skipped = []
    assert problems('view', dict(good, state='{{ wanted_state }}', position='{{ value }}'), skipped) == []
    assert sorted(skipped) == sorted(['state', 'position'])
    # Only the connection options named above are taken as given.
    assert set(CONNECTION_FROM_DEFAULTS) <= set(module_spec('view')['argument_spec'])
