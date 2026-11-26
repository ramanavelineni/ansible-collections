# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""The ansible-core versions of CI: .github/ci-versions.json, and what the jobs get from it.

The versions live outside .github/workflows/ (see .github/scripts/ci-versions.py).
These tests hold the file to the rest of the repository: one sanity ignore
file per version in each collection, requires_ansible no newer than the oldest,
and the release workflow's pin on the newest. Run them with `make tools-test`.
"""

import importlib.util
import json
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(ROOT, '.github', 'scripts', 'ci-versions.py')
CONFIG = os.path.join(ROOT, '.github', 'ci-versions.json')
COLLECTIONS = os.path.join(ROOT, 'ansible_collections', 'ramanavelineni')


def load_script():
    spec = importlib.util.spec_from_file_location('ci_versions', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read(path):
    with open(path) as f:
        return f.read()


def entry(version, oldest='3.9', newest='3.14'):
    return dict(version=version, python_oldest=oldest, python_newest=newest)


class TestOutputs(unittest.TestCase):
    def setUp(self):
        self.script = load_script()

    def test_what_each_job_gets(self):
        found = self.script.outputs([entry('2.20'), entry('2.21'), entry('2.22', newest='3.15')], 'push')
        self.assertEqual(found, dict(
            ansible_all=['2.20', '2.21', '2.22'],
            ansible_units=['2.20', '2.21'],
            ansible_units_python=[dict(ansible='2.20', oldest='3.9', newest='3.14'),
                                  dict(ansible='2.21', oldest='3.9', newest='3.14')],
            ansible_newest='2.22',
            ansible_install=['2.20', '2.22'],
        ))

    def test_a_pull_request_installs_on_the_oldest_only(self):
        found = self.script.outputs([entry('2.20'), entry('2.21'), entry('2.22')], 'pull_request')
        self.assertEqual(found['ansible_install'], ['2.20'])

    def test_one_version_is_oldest_and_newest(self):
        found = self.script.outputs([entry('2.22')], 'push')
        self.assertEqual((found['ansible_units'], found['ansible_install']), ([], ['2.22']))

    def test_bad_files_fail(self):
        for entries in ([], [entry('2.21'), entry('2.20')], [entry('2.20'), entry('2.20')],
                        [entry('2.20', oldest='three')], [dict(version='2.20')]):
            with self.assertRaises(ValueError, msg=entries):
                self.script.outputs(entries, 'push')

    def test_the_real_file(self):
        found = self.script.outputs(self.script.load(), 'push')
        self.assertEqual(found['ansible_newest'], found['ansible_all'][-1])


class TestTheFileAgainstTheRepository(unittest.TestCase):
    def setUp(self):
        self.versions = [e['version'] for e in json.loads(read(CONFIG))['ansible']]

    def test_every_collection_has_one_sanity_ignore_file_per_version(self):
        for name in sorted(os.listdir(COLLECTIONS)):
            sanity = os.path.join(COLLECTIONS, name, 'tests', 'sanity')
            found = sorted(f[len('ignore-'):-len('.txt')] for f in os.listdir(sanity) if f.startswith('ignore-'))
            self.assertEqual(found, sorted(self.versions), name)

    def test_requires_ansible_is_the_oldest_version(self):
        for name in sorted(os.listdir(COLLECTIONS)):
            runtime = read(os.path.join(COLLECTIONS, name, 'meta', 'runtime.yml'))
            self.assertIn('requires_ansible: ">=%s.0"' % self.versions[0], runtime, name)

    def test_the_release_workflow_pins_the_newest(self):
        release = read(os.path.join(ROOT, '.github', 'workflows', 'release.yml'))
        pins = re.findall(r'ansible-core==(\d+\.\d+)\.\d+', release)
        self.assertEqual(pins, [self.versions[-1]])

    def test_no_workflow_names_a_version_itself(self):
        ci = read(os.path.join(ROOT, '.github', 'workflows', 'ci.yml'))
        self.assertEqual(re.findall(r'ansible-core~=\d', ci), [])
        self.assertEqual(re.findall(r'ansible: \[', ci), [])
