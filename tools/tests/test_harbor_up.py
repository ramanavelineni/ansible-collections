# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""Tests for the two edits tools/harbor_up.sh makes itself: Harbor's harbor.yml.tmpl
into a harbor.yml, and the docker-compose.yml that Harbor's prepare writes into
the one that is started.

The second is checked against the compose files of the servers the unit-test
fixtures were recorded from (see fixtures/harbor_up/README.md): adjusting what
prepare writes has to give exactly what runs there.

No server and no container engine is needed. Starting and stopping a Harbor
with the script is not tested here. Run them with `make tools-test`.
"""

import os
import shutil
import socket
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), 'harbor_up.sh')
# For tests that run the script with a PATH of their own.
BASH = shutil.which('bash')
FIXTURES = os.path.join(HERE, 'fixtures', 'harbor_up')
# Version and the port its working server is published on.
VERSIONS = (('v2.14.4', '8014'), ('v2.15.2', '8015'))


def fixture(name):
    with open(os.path.join(FIXTURES, name)) as f:
        return f.read()


def run(args, text):
    return subprocess.run(['bash', SCRIPT] + list(args), input=text, capture_output=True, text=True, check=False)


def scalar(text):
    text = text.strip()
    if text in ('', 'null'):
        return None
    if len(text) > 1 and text[0] == text[-1] and text[0] in '\'"':
        return text[1:-1]
    return text


def parse(text):
    """The block-style YAML of a compose file as dicts, lists and strings.

    Enough for the two styles at hand: Harbor's template, and the same file
    written back by a YAML library, which puts a list at the indentation of its
    key and writes an empty value as null.
    """
    lines = []
    for line in text.splitlines():
        if line.strip() and not line.lstrip().startswith('#'):
            lines.append((len(line) - len(line.lstrip(' ')), line.strip()))
    value, end = block(lines, 0, lines[0][0])
    assert end == len(lines), 'stopped at line %d of %d' % (end, len(lines))
    return value


def block(lines, i, indent):
    if lines[i][1].startswith('- '):
        return sequence(lines, i, indent)
    return mapping(lines, i, indent)


def sequence(lines, i, indent):
    out = []
    while i < len(lines) and lines[i][0] == indent and lines[i][1].startswith('- '):
        item = lines[i][1][2:]
        if item.endswith(':') or ': ' in item:
            # A mapping as list item: its first key sits behind the dash.
            lines[i] = (indent + 2, item)
            value, i = mapping(lines, i, indent + 2)
        else:
            value, i = scalar(item), i + 1
        out.append(value)
    return out, i


def mapping(lines, i, indent):
    out = {}
    while i < len(lines) and lines[i][0] == indent and not lines[i][1].startswith('- '):
        key, _colon, rest = lines[i][1].partition(':')
        i += 1
        if rest.strip():
            out[key] = scalar(rest)
        elif i < len(lines) and (lines[i][0] > indent or (lines[i][0] == indent and lines[i][1].startswith('- '))):
            out[key], i = block(lines, i, lines[i][0])
        else:
            out[key] = None
    return out, i


class Parser(unittest.TestCase):
    """The comparison below is worth what this parser is worth."""

    def test_both_styles_give_the_same(self):
        template_style = (
            'services:\n'
            '  core:\n'
            '    image: goharbor/harbor-core:v1\n'
            '    cap_drop:\n'
            '      - ALL\n'
            '    volumes:\n'
            '      - /data/:/data/:z\n'
            '      - type: bind\n'
            '        source: ./app.conf\n'
            '        target: /etc/core/app.conf\n'
            '    networks:\n'
            '      harbor:\n'
            "    shm_size: '1gb'\n"
            'networks:\n'
            '  harbor:\n'
            '    external: false\n')
        library_style = (
            'services:\n'
            '  core:\n'
            '    image: goharbor/harbor-core:v1\n'
            '    cap_drop:\n'
            '    - ALL\n'
            '    volumes:\n'
            '    - /data/:/data/:z\n'
            '    - type: bind\n'
            '      source: ./app.conf\n'
            '      target: /etc/core/app.conf\n'
            '    networks:\n'
            '      harbor: null\n'
            '    shm_size: 1gb\n'
            'networks:\n'
            '  harbor:\n'
            '    external: false\n')
        expected = dict(
            services=dict(core=dict(
                image='goharbor/harbor-core:v1', cap_drop=['ALL'],
                volumes=['/data/:/data/:z', dict(type='bind', source='./app.conf', target='/etc/core/app.conf')],
                networks=dict(harbor=None), shm_size='1gb')),
            networks=dict(harbor=dict(external='false')))
        self.assertEqual(parse(template_style), expected)
        self.assertEqual(parse(library_style), expected)

    def test_a_difference_is_seen(self):
        self.assertNotEqual(parse('a:\n  - b\n  - c\n'), parse('a:\n  - b\n'))
        self.assertNotEqual(parse('a:\n  b: c\n'), parse('a:\n  b: d\n'))


class AdjustCompose(unittest.TestCase):

    def adjusted(self, version, port):
        result = run(['adjust-compose', port], fixture('compose-%s.prepare.yml' % version))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        return parse(result.stdout)

    def test_gives_the_compose_file_of_the_working_server(self):
        for version, port in VERSIONS:
            with self.subTest(version=version):
                self.assertEqual(self.adjusted(version, port), parse(fixture('compose-%s.working.yml' % version)))

    def test_what_prepare_writes_differs_from_what_runs(self):
        # Otherwise the test above would pass with an adjustment that does nothing.
        for version, _port in VERSIONS:
            with self.subTest(version=version):
                self.assertNotEqual(parse(fixture('compose-%s.prepare.yml' % version)),
                                    parse(fixture('compose-%s.working.yml' % version)))

    def test_each_adjustment(self):
        for version, port in VERSIONS:
            with self.subTest(version=version):
                before = parse(fixture('compose-%s.prepare.yml' % version))['services']
                after = self.adjusted(version, port)['services']
                self.assertIn('log', before)
                self.assertEqual(sorted(after), sorted(name for name in before if name != 'log'))
                for name, service in after.items():
                    self.assertNotIn('container_name', service, name)
                    self.assertNotIn('logging', service, name)
                    self.assertNotIn('log', service.get('depends_on') or [], name)
                    self.assertEqual(service['security_opt'], ['label=disable'], name)
                    if name != 'redis':
                        # Nothing else about the service changes.
                        expected = dict(before[name], security_opt=['label=disable'])
                        del expected['container_name'], expected['logging']
                        expected['depends_on'] = [dep for dep in expected['depends_on'] if dep != 'log']
                        if not expected['depends_on']:
                            del expected['depends_on']
                        if name == 'proxy':
                            expected['ports'] = ['127.0.0.1:%s:8080' % port]
                        self.assertEqual(service, expected, name)
                self.assertEqual(before['proxy']['ports'], ['8080:8080'])
                self.assertEqual(after['redis'], dict(
                    image='docker.io/valkey/valkey:8-alpine', restart='always',
                    volumes=before['redis']['volumes'], networks=before['redis']['networks'],
                    security_opt=['label=disable'], command=['valkey-server', '--dir', '/var/lib/redis']))

    def test_the_recorder_reaches_harbor_as_proxy_8080(self):
        # record_harbor_fixtures.py makes Harbor ping itself as http://proxy:8080.
        for version, port in VERSIONS:
            with self.subTest(version=version):
                proxy = self.adjusted(version, port)['services']['proxy']
                self.assertEqual(proxy['ports'], ['127.0.0.1:%s:8080' % port])
                self.assertIn('harbor', proxy['networks'])

    def test_the_port_is_the_one_asked_for(self):
        proxy = self.adjusted('v2.15.2', '8099')['services']['proxy']
        self.assertEqual(proxy['ports'], ['127.0.0.1:8099:8080'])

    def test_an_unexpected_file_is_refused(self):
        whole = fixture('compose-v2.15.2.prepare.yml')
        cases = dict(
            log=whole.replace('  log:\n', '  logs:\n'),
            logging=whole.replace('    logging:\n', '    loging:\n'),
            redis=whole.replace('  redis:\n', '  cache:\n'),
            port=whole.replace('      - 8080:8080\n', '      - 8080:80\n'),
            empty='')
        for name, text in cases.items():
            with self.subTest(missing=name):
                self.assertNotEqual(text, whole)
                result = run(['adjust-compose', '8015'], text)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('harbor_up: no ', result.stderr)


class EditConfig(unittest.TestCase):

    ARGS = ['edit-config', 'harbor-v2152.lab', '/lab/v2.15.2/data', 'Hb1admin', 'dbpw']

    def test_edits(self):
        template = fixture('harbor.yml.tmpl')
        result = run(self.ARGS, template)
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = template
        for old, new in (
                ('hostname: reg.mydomain.com\n', 'hostname: harbor-v2152.lab\n'),
                ('http:\n  # port for http, default is 80. If https enabled, this port will redirect to https port\n'
                 '  port: 80\n',
                 'http:\n  # port for http, default is 80. If https enabled, this port will redirect to https port\n'
                 '  port: 8080\n'),
                ('harbor_admin_password: Harbor12345\n', 'harbor_admin_password: Hb1admin\n'),
                ('  password: root123\n', '  password: dbpw\n'),
                ('data_volume: /data\n', 'data_volume: /lab/v2.15.2/data\n')):
            self.assertEqual(expected.count(old), 1, old)
            expected = expected.replace(old, new)
        start = expected.index('https:\n')
        end = expected.index('# The initial password')
        expected = expected[:start] + expected[end:]
        self.assertEqual(result.stdout, expected)
        # The other port: 80 in the file, and the https block's own port, are not the http port.
        self.assertIn('metric:\n  # port: 9090\n  port: 80\n', result.stdout)
        self.assertNotIn('443', result.stdout)

    def test_a_changed_template_is_refused(self):
        template = fixture('harbor.yml.tmpl')
        cases = dict(
            hostname=template.replace('hostname: reg', 'host: reg'),
            port=template.replace('  port: 80\n\n# https', '  port: 8000\n\n# https'),
            admin=template.replace('harbor_admin_password:', 'admin_password:'),
            database=template.replace('  password: root123', '  pass: root123'),
            data=template.replace('data_volume:', 'data_dir:'),
            https=template.replace('  # strong_ssl_ciphers: false\n\n', '  # strong_ssl_ciphers: false\n')
                          .replace('# The initial password of Harbor admin\n', '\nhttps:\n  port: 8443\n'))
        for name, text in cases.items():
            with self.subTest(changed=name):
                self.assertNotEqual(text, template)
                result = run(self.ARGS, text)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn('harbor.yml.tmpl has changed', result.stderr)
                self.assertEqual(result.stdout, '')

    def test_passwords_are_not_in_the_error(self):
        result = run(self.ARGS, 'hostname: x\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('Hb1admin', result.stderr)
        self.assertNotIn('dbpw', result.stderr)


class Arguments(unittest.TestCase):

    def test_usage(self):
        for args in ([], ['up'], ['sideways', 'v2.15.2'], ['adjust-compose'], ['edit-config', 'a']):
            with self.subTest(args=args):
                result = run(args, '')
                self.assertEqual(result.returncode, 2)
                self.assertIn('usage: harbor_up.sh up <version> [port]', result.stderr)

    def test_version_and_port_are_checked_before_anything_is_done(self):
        for args, message in ((['up', '2.15.2'], 'version must look like v2.15.2'),
                              (['down', 'latest'], 'version must look like v2.15.2'),
                              (['up', 'v2.15.2', 'http'], 'port must be a number')):
            with self.subTest(args=args):
                result = run(args, '')
                self.assertEqual(result.returncode, 1)
                self.assertIn(message, result.stderr)

    def test_down_only_removes_what_up_made(self):
        with tempfile.TemporaryDirectory() as base:
            lab = os.path.join(base, 'v2.15.2')
            os.mkdir(lab)
            keep = os.path.join(lab, 'something.txt')
            with open(keep, 'w') as f:
                f.write('not ours\n')
            # A PATH with a container engine that must never be called.
            bin_dir = os.path.join(base, 'bin')
            os.mkdir(bin_dir)
            called = os.path.join(base, 'called')
            for name in ('podman', 'docker'):
                path = os.path.join(bin_dir, name)
                with open(path, 'w') as f:
                    f.write('#!/bin/sh\necho "$0 $*" >> "%s"\n' % called)
                os.chmod(path, 0o755)
            env = dict(os.environ, HARBOR_UP_DIR=base, PATH=bin_dir + os.pathsep + os.environ['PATH'])
            result = subprocess.run(['bash', SCRIPT, 'down', 'v2.15.2'], capture_output=True, text=True,
                                    check=False, env=env)
            self.assertEqual(result.returncode, 1)
            self.assertIn('was not made by this script', result.stderr)
            self.assertTrue(os.path.exists(keep))
            self.assertFalse(os.path.exists(called))

            result = subprocess.run(['bash', SCRIPT, 'down', 'v2.14.4'], capture_output=True, text=True,
                                    check=False, env=env)
            self.assertEqual(result.returncode, 1)
            self.assertIn('does not exist', result.stderr)

    def test_up_refuses_an_existing_directory(self):
        with tempfile.TemporaryDirectory() as base:
            os.mkdir(os.path.join(base, 'v2.15.2'))
            bin_dir = os.path.join(base, 'bin')
            os.mkdir(bin_dir)
            called = os.path.join(base, 'called')
            # "podman compose version" has to succeed for the script to get this far.
            path = os.path.join(bin_dir, 'podman')
            with open(path, 'w') as f:
                f.write('#!/bin/sh\n[ "$1 $2" = "compose version" ] && exit 0\necho "$*" >> "%s"\n' % called)
            os.chmod(path, 0o755)
            env = dict(os.environ, HARBOR_UP_DIR=base, PATH=bin_dir + os.pathsep + os.environ['PATH'])
            result = subprocess.run(['bash', SCRIPT, 'up', 'v2.15.2', '8015'], capture_output=True, text=True,
                                    check=False, env=env)
            self.assertEqual(result.returncode, 1)
            self.assertIn('exists already', result.stderr)
            self.assertFalse(os.path.exists(called))

    def test_up_refuses_a_version_that_runs_from_another_directory(self):
        with tempfile.TemporaryDirectory() as base:
            bin_dir = os.path.join(base, 'bin')
            os.mkdir(bin_dir)
            called = os.path.join(base, 'called')
            # A podman that has a compose provider and lists a container of the project harborv2152.
            path = os.path.join(bin_dir, 'podman')
            with open(path, 'w') as f:
                f.write('#!/bin/sh\n'
                        '[ "$1 $2" = "compose version" ] && exit 0\n'
                        'if [ "$1" = ps ]; then\n'
                        '  case "$*" in *com.docker.compose.project=harborv2152*) echo 7328b8a3d9cb;; esac\n'
                        '  exit 0\n'
                        'fi\n'
                        'echo "$*" >> "%s"\n' % called)
            os.chmod(path, 0o755)
            env = dict(os.environ, HARBOR_UP_DIR=os.path.join(base, 'lab'), PATH=bin_dir + os.pathsep + os.environ['PATH'])
            result = subprocess.run(['bash', SCRIPT, 'up', 'v2.15.2', '8016'], capture_output=True, text=True,
                                    check=False, env=env)
            self.assertEqual(result.returncode, 1)
            self.assertIn('containers of a compose project harborv2152 exist already', result.stderr)
            # Nothing was made and nothing but the two questions was asked of podman.
            self.assertFalse(os.path.exists(os.path.join(base, 'lab')))
            self.assertFalse(os.path.exists(called))

    def stub_podman(self, base, socket_path):
        """An environment whose PATH has a podman without a compose provider, a curl that gets nothing, and no more
        than the plain tools the script calls: whatever docker or compose the machine has is out of reach."""
        bin_dir = os.path.join(base, 'bin')
        os.mkdir(bin_dir)
        called = os.path.join(base, 'called')
        with open(os.path.join(bin_dir, 'podman'), 'w') as f:
            f.write('#!/bin/sh\n'
                    '[ "$1 $2" = "compose version" ] && exit 125\n'
                    '[ "$1" = info ] && { echo "%s"; exit 0; }\n'
                    '[ "$1" = ps ] && exit 0\n'
                    'echo "$*" >> "%s"\n' % (socket_path, called))
        with open(os.path.join(bin_dir, 'curl'), 'w') as f:
            f.write('#!/bin/sh\nexit 22\n')
        for name in ('podman', 'curl'):
            os.chmod(os.path.join(bin_dir, name), 0o755)
        for tool in ('sh', 'cat', 'mkdir', 'head', 'od', 'tr', 'sed', 'awk', 'seq', 'sleep', 'rm', 'chmod'):
            found = shutil.which(tool)
            if found:
                os.symlink(found, os.path.join(bin_dir, tool))
        return dict(os.environ, HARBOR_UP_DIR=os.path.join(base, 'lab'), PATH=bin_dir)

    def test_without_a_compose_command_podmans_socket_is_used(self):
        # A short path: a unix socket's path has a length limit.
        with tempfile.TemporaryDirectory(dir='/tmp') as base:
            socket_path = os.path.join(base, 's')
            listener = socket.socket(socket.AF_UNIX)
            listener.bind(socket_path)
            try:
                result = subprocess.run([BASH, SCRIPT, 'up', 'v2.15.2', '8016'], capture_output=True, text=True,
                                        check=False, env=self.stub_podman(base, socket_path))
            finally:
                listener.close()
            # It got past the search for a compose command, as far as fetching Harbor's template.
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('no compose command found', result.stderr)
            self.assertTrue(os.path.exists(os.path.join(base, 'lab', 'v2.15.2', '.harbor_up')))

    def test_without_a_compose_command_and_without_a_socket_it_stops(self):
        with tempfile.TemporaryDirectory() as base:
            result = subprocess.run([BASH, SCRIPT, 'up', 'v2.15.2', '8016'], capture_output=True, text=True,
                                    check=False, env=self.stub_podman(base, os.path.join(base, 'nothing-here')))
            self.assertEqual(result.returncode, 1)
            self.assertIn('no compose command found, and no podman API socket', result.stderr)
            self.assertFalse(os.path.exists(os.path.join(base, 'lab')))


if __name__ == '__main__':
    unittest.main()
