# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""The keys each module documents under RETURN are the keys it returns.

Top level only. Every module is run through the cases of test_check_mode.py
(the modules that write) or test_info_modules.py (the ones that read): no
result may carry a key the documentation doesn't name, and every documented
key has to turn up in at least one of the module's results.
"""

import copy

import pytest
import yaml

from ansible_collections.ramanavelineni.harbor.tests.unit.plugins.modules.test_check_mode import CASES
from ansible_collections.ramanavelineni.harbor.tests.unit.plugins.modules.test_info_modules import INFO_CASES

# What Ansible and run_module() add to every result.
COMMON = set(['changed', 'diff', 'invocation', 'warnings', 'deprecations', 'failed', 'msg'])


def runs_by_module():
    """module -> [(routes, arguments)], from both case tables."""
    runs = {}
    for dummy_name, module, dummy_key, routes, args, dummy_writes, dummy_assigned in CASES:
        runs.setdefault(module, []).append((lambda server, routes=routes: routes(server, real=True), args))
    for module, dummy_key, routes, args in INFO_CASES:
        runs.setdefault(module, []).append((routes, args))
    return runs


RUNS = sorted(runs_by_module().items(), key=lambda item: item[0].__name__)


def documented_keys(module):
    return set(yaml.safe_load(module.RETURN))


def test_every_module_is_covered():
    # 23 modules: 11 that write, 12 that read.
    assert len(RUNS) == 23


@pytest.mark.parametrize('module, runs', RUNS, ids=[m.__name__.rsplit('.', 1)[-1] for m, dummy in RUNS])
def test_returned_keys_are_the_documented_ones(server, run_module, module, runs):
    documented = documented_keys(module)
    assert documented, 'no RETURN documentation'
    returned = set()
    for routes, args in runs:
        routes(server)
        result = run_module(module.main, copy.deepcopy(args))
        assert result.get('failed') is not True, result.get('msg')
        keys = set(result) - COMMON
        assert keys <= documented, 'returned but not documented: %s' % ', '.join(sorted(keys - documented))
        returned |= keys
    assert documented <= returned, 'documented but never returned: %s' % ', '.join(sorted(documented - returned))


@pytest.mark.parametrize('module, runs', RUNS, ids=[m.__name__.rsplit('.', 1)[-1] for m, dummy in RUNS])
def test_check_mode_returns_the_documented_keys_too(server, run_module, module, runs):
    documented = documented_keys(module)
    for routes, args in runs:
        routes(server)
        result = run_module(module.main, copy.deepcopy(args), check_mode=True)
        keys = set(result) - COMMON
        assert keys <= documented, 'returned in check mode but not documented: %s' % ', '.join(sorted(keys - documented))
