# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""The role-test matrix: .github/role-tests.json, and what CI makes of it.

The server versions the role tests run against live in .github/role-tests.json
instead of the workflow file (see .github/scripts/role-test-matrix.py). These
tests hold that file to the rest of the repository: a version CI tests is one
the collection says it is tested with, every Harbor version has a pinned
installer, and every ansible-core named is one CI tests. Run them with
`make tools-test`.
"""

import importlib.util
import json
import os
import re
import shutil
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(ROOT, '.github', 'scripts', 'role-test-matrix.py')
CONFIG = os.path.join(ROOT, '.github', 'role-tests.json')
COLLECTIONS = os.path.join(ROOT, 'ansible_collections', 'ramanavelineni')
# The module that names a collection's tested versions, and the key of its
# server in role-tests.json.
SERVERS = dict(semaphoreui=('semaphore', 'semaphore.py'), harbor=('harbor', 'harbor.py'))


def load_script():
    spec = importlib.util.spec_from_file_location('role_test_matrix', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read(path):
    with open(path) as f:
        return f.read()


def minor(version):
    return tuple(int(part) for part in re.match(r'^v?(\d+)\.(\d+)', version).groups())


def tested_versions(collection):
    """TESTED_VERSIONS of the collection's module_utils, read as text (no ansible-core needed)."""
    source = read(os.path.join(COLLECTIONS, collection, 'plugins', 'module_utils', SERVERS[collection][1]))
    line = re.search(r"^TESTED_VERSIONS = \(([^)]*)\)", source, re.M)
    return re.findall(r"'(\d+\.\d+)'", line.group(1))


def ci_ansible_versions():
    """The ansible-core versions the sanity job goes through."""
    job = read(os.path.join(ROOT, '.github', 'workflows', 'ci.yml')).split('\n  sanity:\n', 1)[1]
    line = re.search(r'^\s+ansible: \[([^\]]*)\]\s*$', job, re.M)
    return re.findall(r'"([0-9]+\.[0-9]+)"', line.group(1))


class TestRoleTestVersions(unittest.TestCase):
    def setUp(self):
        self.config = json.loads(read(CONFIG))

    def test_every_collection_with_role_tests_is_listed(self):
        with_role_tests = sorted(name for name in os.listdir(COLLECTIONS)
                                 if os.path.isdir(os.path.join(COLLECTIONS, name, 'tests', 'roles')))
        self.assertEqual(sorted(self.config), with_role_tests)

    def test_versions_are_oldest_first_and_tested(self):
        for collection, entry in self.config.items():
            server = SERVERS[collection][0]
            versions = [v[server] for v in entry['versions']]
            self.assertEqual(versions, sorted(versions, key=minor), collection)
            minors = ['%d.%d' % minor(v) for v in versions]
            self.assertEqual(len(minors), len(set(minors)), '%s: one release per major.minor' % collection)
            # CI tests what the collection says it is tested with, and the other way round.
            self.assertEqual(sorted(minors), sorted(tested_versions(collection)), collection)

    def test_ansible_core_versions_are_ones_ci_tests(self):
        supported = ci_ansible_versions()
        for collection, entry in self.config.items():
            for version in entry['versions']:
                self.assertIn(version['ansible'], supported, collection)

    def test_every_harbor_version_has_a_pinned_installer(self):
        script = read(os.path.join(ROOT, '.github', 'scripts', 'harbor-ci-up.sh'))
        for version in self.config['harbor']['versions']:
            self.assertRegex(script, r'\n  %s\) sha256=[0-9a-f]{64}' % re.escape(version['harbor']))


class TestMatrix(unittest.TestCase):
    def setUp(self):
        self.script = load_script()
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        roles = os.path.join(self.root, 'ansible_collections', 'ramanavelineni', 'demo', 'tests', 'roles')
        os.makedirs(os.path.join(roles, 'tasks'))
        for name in ('apply.yml', 'export.yml', 'tasks/cleanup.yml', 'notes.md'):
            with open(os.path.join(roles, name), 'w') as f:
                f.write('---\n')
        self.config = dict(demo=dict(versions=[dict(server='v1.0.1', ansible='2.20'),
                                               dict(server='v1.1.0', ansible='2.22')]))

    def test_pull_request_runs_the_newest_version_only(self):
        self.assertEqual(self.script.matrix('demo', 'pull_request', self.config, self.root), [
            dict(server='v1.1.0', ansible='2.22', playbook='apply'),
            dict(server='v1.1.0', ansible='2.22', playbook='export')])

    def test_anything_else_runs_every_version(self):
        for event in ('push', 'schedule', 'workflow_call'):
            jobs = self.script.matrix('demo', event, self.config, self.root)
            self.assertEqual([(j['server'], j['playbook']) for j in jobs], [
                ('v1.0.1', 'apply'), ('v1.0.1', 'export'), ('v1.1.0', 'apply'), ('v1.1.0', 'export')])

    def test_playbooks_are_the_yml_files_of_tests_roles_only(self):
        self.assertEqual(self.script.playbooks('demo', self.root), ['apply', 'export'])

    def test_unknown_collection_and_no_versions_fail(self):
        with self.assertRaises(ValueError):
            self.script.matrix('other', 'push', self.config, self.root)
        with self.assertRaises(ValueError):
            self.script.matrix('demo', 'push', dict(demo=dict(versions=[])), self.root)

    def test_the_real_matrices(self):
        for collection in SERVERS:
            jobs = self.script.matrix(collection, 'push')
            playbooks = self.script.playbooks(collection)
            self.assertTrue(playbooks, collection)
            self.assertEqual(len(jobs), len(playbooks) * len(json.loads(read(CONFIG))[collection]['versions']))
