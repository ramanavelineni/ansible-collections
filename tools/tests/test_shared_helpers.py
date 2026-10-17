# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""The collections' shared code has not drifted apart.

Each collection is built and tested alone, so each carries its own copy of
tests/unit/plugins/utils.py (the test helpers) and of
plugins/module_utils/transport.py (the HTTP transport of its client), and no test
inside a collection can see the other one. This one can. Run it with
`make tools-test`.
"""

import glob
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
COLLECTIONS = os.path.join(ROOT, 'ansible_collections', 'ramanavelineni')
COPIES = sorted(glob.glob(os.path.join(COLLECTIONS, '*', 'tests', 'unit', 'plugins', 'utils.py')))
TRANSPORTS = sorted(glob.glob(os.path.join(COLLECTIONS, '*', 'plugins', 'module_utils', 'transport.py')))
# What a conftest.py has to provide under the same name in every collection,
# because the tests of all of them are written against these.
SHARED_NAMES = ('FIXTURES_DIR', 'VERSIONS', 'PATCH_TARGET', 'CONNECTION', 'load_fixtures', 'FakeServer', 'FakeResponse',
                'patch_module_args', 'transport_error', 'server', 'run_module')


def read(path):
    with open(path, 'rb') as f:
        return f.read()


def collection(path):
    return os.path.relpath(path, ROOT).split(os.sep)[2]


def collection_count():
    return len(glob.glob(os.path.join(COLLECTIONS, '*', 'galaxy.yml')))


class SharedCopies(object):
    """Checks for a file that every collection carries, byte for byte the same. Set `copies`."""

    copies = ()

    def test_every_collection_has_a_copy(self):
        self.assertGreaterEqual(len(self.copies), 2)
        self.assertEqual(len(self.copies), collection_count())

    def test_the_copies_are_identical(self):
        first = read(self.copies[0])
        for other in self.copies[1:]:
            self.assertEqual(first, read(other), '%s and %s differ: change both' % (
                os.path.relpath(self.copies[0], ROOT), os.path.relpath(other, ROOT)))

    def test_a_copy_names_no_collection(self):
        # What depends on the server belongs in the collection's own files; a
        # name in here would be wrong in the other copy.
        for path in self.copies:
            text = read(path).decode()
            for name in sorted(set(collection(p) for p in self.copies)):
                self.assertNotIn(name, text.lower(), '%s mentions %s' % (os.path.relpath(path, ROOT), name))


class SharedHelpers(SharedCopies, unittest.TestCase):
    copies = COPIES

    def test_every_conftest_offers_the_same_names(self):
        for path in COPIES:
            conftest = read(os.path.join(os.path.dirname(path), 'conftest.py')).decode()
            for name in SHARED_NAMES:
                self.assertRegex(conftest, r'(?m)^(def |class |    |)%s\b' % name,
                                 '%s has no %s' % (os.path.relpath(os.path.dirname(path), ROOT), name))


class SharedTransport(SharedCopies, unittest.TestCase):
    """plugins/module_utils/transport.py: a fix to the transport reaches every client."""

    copies = TRANSPORTS


if __name__ == '__main__':
    unittest.main()
