# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""The collections' shared test helpers have not drifted apart.

Each collection is built and tested alone, so each carries its own copy of
tests/unit/plugins/utils.py, and no test inside a collection can see the
other one. This one can. Run it with `make tools-test`.
"""

import glob
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
COPIES = sorted(glob.glob(os.path.join(ROOT, 'ansible_collections', 'ramanavelineni', '*', 'tests', 'unit', 'plugins', 'utils.py')))
# What a conftest.py has to provide under the same name in every collection,
# because the tests of all of them are written against these.
SHARED_NAMES = ('FIXTURES_DIR', 'VERSIONS', 'PATCH_TARGET', 'CONNECTION', 'load_fixtures', 'FakeServer', 'FakeResponse',
                'patch_module_args', 'transport_error', 'server', 'run_module')


def read(path):
    with open(path, 'rb') as f:
        return f.read()


def collection(path):
    return os.path.relpath(path, ROOT).split(os.sep)[2]


class SharedHelpers(unittest.TestCase):
    def test_every_collection_has_a_copy(self):
        collections = sorted(glob.glob(os.path.join(ROOT, 'ansible_collections', 'ramanavelineni', '*', 'galaxy.yml')))
        self.assertGreaterEqual(len(COPIES), 2)
        self.assertEqual(len(COPIES), len(collections))

    def test_the_copies_are_identical(self):
        first = read(COPIES[0])
        for other in COPIES[1:]:
            self.assertEqual(first, read(other), '%s and %s differ: change both' % (
                os.path.relpath(COPIES[0], ROOT), os.path.relpath(other, ROOT)))

    def test_a_copy_names_no_collection(self):
        # What depends on the server belongs in conftest.py; a name in here
        # would be wrong in the other copy.
        for path in COPIES:
            text = read(path).decode()
            for name in sorted(set(collection(p) for p in COPIES)):
                self.assertNotIn(name, text.lower(), '%s mentions %s' % (os.path.relpath(path, ROOT), name))

    def test_every_conftest_offers_the_same_names(self):
        for path in COPIES:
            conftest = read(os.path.join(os.path.dirname(path), 'conftest.py')).decode()
            for name in SHARED_NAMES:
                self.assertRegex(conftest, r'(?m)^(def |class |    |)%s\b' % name,
                                 '%s has no %s' % (os.path.relpath(os.path.dirname(path), ROOT), name))


if __name__ == '__main__':
    unittest.main()
