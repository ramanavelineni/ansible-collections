# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""Filters of the project_export role: what the _info modules return, as the project file project_apply reads.

A project file holds the project's own options (those of the project module)
and one section per kind of object, named after the module that manages it:

  robot_account     keyed by robot name (project robots)
  project_member    a list of project_member options
  tag_retention     one mapping (the project's single policy)
  tag_immutability  a list of tag_immutability options
  webhook           keyed by webhook name

The _info modules return each object close to the shape of its module (plus
ids and what only the server knows), so turning one into the other is mostly
a matter of leaving things out:

  - ids, and fields Harbor fills in (a robot's full name and expiry time, a
    project's repository count and retention id, a webhook's endpoint count);
  - options at what an object gets when it is created without them, so the
    file shows what was chosen;
  - secrets: a robot account's secret, which Harbor never returns, a
    webhook's auth header, which the _info module does not return, and a
    Slack webhook's URL, which is enough to post to the channel. Each
    becomes a reference to a variable ("{{ vault_... }}"), and the variables
    are listed for a vault.

What can't be written as a file project_apply would apply stops the export
with the reason, before anything is written.

Only the Python standard library is used: no YAML library, no ansible import.
The YAML writer is the semaphoreui collection's, copied: the collections don't
depend on each other.
"""

import math
import re

# In the order project_apply applies them.
SECTIONS = ('robot_account', 'project_member', 'tag_retention', 'tag_immutability', 'webhook')
# Sections that are mappings keyed by object name; the others are lists, and
# tag_retention is one mapping.
KEYED = ('robot_account', 'webhook')

KEEP = object()

# The project's own options, each with what a new project has (KEEP: always written).
PROJECT_OPTIONS = (('public', KEEP), ('metadata', {}), ('proxy_registry', None), ('quota_gb', None))

# Project metadata as the project module takes it (plugins/modules/project.py
# checks the same lists; a unit test holds the two together). Harbor stores
# every value as a string.
METADATA_BOOL = ('auto_scan', 'auto_sbom_generation', 'prevent_vul', 'reuse_sys_cve_allowlist',
                 'enable_content_trust', 'enable_content_trust_cosign', 'proxy_cache_local_on_not_found')
METADATA_INT = ('proxy_speed_kb', 'max_upstream_conn')
METADATA_TEXT = ('severity',)
# Kept by Harbor, managed elsewhere: the project's retention policy id.
METADATA_SKIPPED = ('public', 'retention_id')

# Per section: the options to write, in the order the modules document them,
# each with what an object created without that option has. Options that are
# not here are either never returned (secrets, see below) or mean something
# for a run only (state, update_secret, confirm_delete).
OPTIONS = dict(
    robot_account=(('description', ''), ('duration', KEEP), ('disable', False), ('permissions', KEEP)),
    project_member=(('user', None), ('group', None), ('group_type', None), ('role', KEEP)),
    tag_retention=(('schedule', ''), ('rules', KEEP)),
    tag_immutability=(('repositories', '**'), ('repositories_decoration', 'matches'), ('tags', KEEP),
                      ('tags_decoration', 'matches'), ('disabled', False)),
    webhook=(('description', ''), ('enabled', True), ('event_types', KEEP), ('notify_type', 'http'),
             ('address', KEEP), ('skip_cert_verify', False), ('payload_format', None)),
)

# The keys of a retention rule, with the default the tag_retention module gives each.
RULE_OPTIONS = (('template', KEEP), ('value', None), ('repositories', '**'), ('repositories_decoration', 'matches'),
                ('tags', '**'), ('tags_decoration', 'matches'), ('untagged', False), ('disabled', False))

# The options the modules mark no_log, as section -> option. A unit test
# holds this against the modules' argument specs.
SECRETS = dict(robot_account=('secret',), webhook=('auth_header',))

# What a robot account with a vault secret is written with. Harbor never
# returns a secret, so it can't be compared with the vault value; with the
# module's default (always) every apply would send it again and report a
# change. With on_create an apply sends it only for a new robot account. Set
# always on the entry to push a changed vault value. A webhook's auth header
# needs nothing like this: the webhook module compares it with what Harbor
# stores.
ON_CREATE = dict(update_secret='on_create')

SECTION_WORD = dict(robot_account='robot', webhook='webhook')

JINJA = ('{{', '{%', '{#')
PLAIN = re.compile(r'^[A-Za-z][A-Za-z0-9_./@-]*( [A-Za-z0-9_./@-]+)*\Z')
# What YAML 1.1 reads as something other than a string.
NOT_PLAIN = frozenset(('y', 'n', 'yes', 'no', 'on', 'off', 'true', 'false', 'null', 'none'))
IDENTIFIER = re.compile(r'^[a-z_][a-z0-9_]*\Z')
ESCAPES = {'"': '\\"', '\\': '\\\\', '\n': '\\n', '\t': '\\t', '\r': '\\r', '\b': '\\b', '\f': '\\f', '\0': '\\0'}
# Characters YAML treats as line breaks or marks, besides the control characters.
UNPRINTABLE = frozenset(u'\x7f\x85\xa0  ﻿')


class VaultReference(object):
    """A secret the server keeps to itself: the variable it is to come from, and what it is the secret of."""

    def __init__(self, variable, what):
        self.variable = variable
        self.what = what

    def text(self):
        return '{{ %s }}' % self.variable


def slug(text):
    """`text` as part of a variable name: lower case, as ansible-lint wants variables."""
    return re.sub(r'[^a-z0-9]+', '_', ('%s' % (text,)).lower()).strip('_') or 'x'


class Vault(object):
    """Hands out one variable name per secret, never the same one twice."""

    def __init__(self, prefix, project):
        if not IDENTIFIER.match(prefix or ''):
            raise ValueError("the vault variable prefix %r is not a variable name: lower-case letters, digits and _ "
                             "only, not starting with a digit" % (prefix,))
        self.stem = '%s_%s' % (prefix, slug(project))
        self.references = []
        self.taken = set()

    def reference(self, section, name, field, what):
        base = '_'.join((self.stem, SECTION_WORD.get(section, section), slug(name), slug(field)))
        variable, n = base, 1
        # Two names that differ only in punctuation or case give the same variable.
        while variable in self.taken:
            n += 1
            variable = '%s_%d' % (base, n)
        self.taken.add(variable)
        found = VaultReference(variable, what)
        self.references.append(found)
        return found


def kept(options, found):
    """The options of `found` that are there and not at their default, in table order."""
    out = {}
    for option, default in options:
        if option not in found:
            continue
        value = found[option]
        if default is KEEP or value != default:
            out[option] = value
    return out


def metadata(project, found):
    """A project's metadata as the project module takes it: typed values, only the keys Harbor stores."""
    out = {}
    for key in sorted(found or {}):
        value = found[key]
        if key in METADATA_SKIPPED:
            continue
        if key in METADATA_BOOL:
            out[key] = '%s' % (value,) == 'true' if not isinstance(value, bool) else value
        elif key in METADATA_INT:
            try:
                out[key] = int(value)
            except (TypeError, ValueError):
                raise ValueError('project_export: project %s has metadata.%s = %r, which is not a whole number'
                                 % (project, key, value))
        elif key in METADATA_TEXT:
            out[key] = value
        else:
            raise ValueError('project_export: project %s has the metadata key %s, which this collection does not '
                             'know; the project module would refuse it. Known keys: %s'
                             % (project, key, ', '.join(METADATA_BOOL + METADATA_INT + METADATA_TEXT)))
    return out


def project_options(found):
    """The project's own options, from one entry of project_info's result."""
    name = found['name']
    if found.get('registry_id') and not found.get('proxy_registry'):
        raise ValueError('project_export: project %s is a proxy cache, but the name of its registry could not be '
                         'read (only a system administrator may read registries). Export it as an administrator.'
                         % name)
    out = dict(name=name)
    for option, default in PROJECT_OPTIONS:
        if option not in found:
            continue
        value = metadata(name, found[option]) if option == 'metadata' else found[option]
        if default is KEEP or value != default:
            out[option] = value
    return out


def robot_options(project, found, vault):
    name = '%s' % (found['name'],)
    out = kept(OPTIONS['robot_account'], found)
    permissions = []
    for permission in out.get('permissions') or []:
        entry = {}
        # A project robot's entry is for its own project: kind and namespace are the module's defaults.
        if permission.get('kind', 'project') != 'project':
            entry['kind'] = permission['kind']
        if permission.get('namespace') not in (None, project):
            entry['namespace'] = permission['namespace']
        entry['access'] = [dict(resource=item.get('resource'), action=item.get('action'))
                           for item in permission.get('access') or []]
        permissions.append(entry)
    out['permissions'] = permissions
    out['secret'] = vault.reference('robot_account', name, 'secret', 'robot account %s: secret' % name)
    out.update(ON_CREATE)
    return name, out


def member_options(project, found):
    out = kept(OPTIONS['project_member'], found)
    if found.get('group') is not None and not found.get('group_type'):
        raise ValueError('project_export: the type of group member %s of project %s could not be read (only a system '
                         'administrator may read user groups), and project_apply needs it. Export the project as an '
                         'administrator.' % (found['group'], project))
    if 'role' not in out or out['role'] is None:
        raise ValueError('project_export: member %s of project %s has a role this collection does not know (role id '
                         '%s)' % (found.get('user') or found.get('group'), project, found.get('role_id')))
    return out


def retention_options(found):
    out = kept(OPTIONS['tag_retention'], found)
    rules = []
    for rule in out.get('rules') or []:
        entry = kept(RULE_OPTIONS, rule)
        if entry.get('template') == 'always':
            entry.pop('value', None)
        rules.append(entry)
    out['rules'] = rules
    return out


def webhook_options(project, found, vault):
    name = '%s' % (found['name'],)
    if (found.get('endpoints') or 1) > 1:
        raise ValueError('project_export: webhook %s of project %s has %d endpoints; the webhook module manages '
                         'webhooks with one, as the Harbor UI makes them' % (name, project, found['endpoints']))
    out = kept(OPTIONS['webhook'], found)
    if found.get('notify_type') == 'http' and out.get('payload_format') == 'Default':
        # What a new http webhook gets.
        out.pop('payload_format')
    if 'event_types' in out:
        out['event_types'] = sorted(out['event_types'] or [])
    if found.get('auth_header_set'):
        out['auth_header'] = vault.reference('webhook', name, 'auth_header', 'webhook %s: auth header' % name)
    if found.get('notify_type') == 'slack' and out.get('address'):
        # A Slack incoming-webhook URL is all it takes to post to the channel.
        out['address'] = vault.reference('webhook', name, 'address', 'webhook %s: Slack webhook URL' % name)
    return name, out


def export_config(info, vault_prefix='vault'):
    """(config, vault): the mapping project_apply reads, and the Vault with the references in it."""
    if not isinstance(info, dict) or not isinstance(info.get('project'), dict) or not info['project'].get('name'):
        raise ValueError('project_export needs a mapping with the project (as project_info returns it) under "project" '
                         'and what the _info modules return under the section names: %s' % ', '.join(SECTIONS))
    project = info['project']['name']
    vault = Vault(vault_prefix, project)
    config = project_options(info['project'])

    for section in SECTIONS:
        found = info.get(section)
        wanted = dict if section == 'tag_retention' else (list, tuple)
        if found is not None and not isinstance(found, wanted):
            raise ValueError('project_export: "%s" has to be the %s the %s_info module returns'
                             % (section, 'mapping' if section == 'tag_retention' else 'list', section))

    robots = {}
    for found in sorted(info.get('robot_account') or [], key=lambda r: '%s' % (r.get('name'),)):
        if found.get('level', 'project') != 'project':
            continue
        name, options = robot_options(project, found, vault)
        if name in robots:
            raise ValueError('project_export: two robot accounts of project %s are named %r' % (project, name))
        robots[name] = options
    if robots:
        config['robot_account'] = robots

    members = [member_options(project, found) for found in info.get('project_member') or []]
    if members:
        config['project_member'] = members

    retention = info.get('tag_retention') or {}
    if retention.get('rules'):
        config['tag_retention'] = retention_options(retention)

    rules = [kept(OPTIONS['tag_immutability'], found) for found in info.get('tag_immutability') or []]
    if rules:
        config['tag_immutability'] = rules

    webhooks = {}
    for found in sorted(info.get('webhook') or [], key=lambda w: '%s' % (w.get('name'),)):
        name, options = webhook_options(project, found, vault)
        if name in webhooks:
            raise ValueError('project_export: two webhooks of project %s are named %r' % (project, name))
        webhooks[name] = options
    if webhooks:
        config['webhook'] = webhooks
    return config, vault


def plain(value):
    """`value` with every vault reference as the text that stands for it."""
    if isinstance(value, VaultReference):
        return value.text()
    if isinstance(value, dict):
        return dict((key, plain(item)) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    return value


# ---- YAML (copied from the semaphoreui collection's project_export) -----------

def quoted(text):
    out = []
    for ch in text:
        if ch in ESCAPES:
            out.append(ESCAPES[ch])
        elif ch < ' ' or ch in UNPRINTABLE or u'\x80' <= ch <= u'\x9f' or u'\ud800' <= ch <= u'\udfff':
            out.append('\\x%02x' % ord(ch) if ord(ch) < 0x100 else '\\u%04x' % ord(ch))
        else:
            out.append(ch)
    return '"%s"' % ''.join(out)


def block(text):
    """Whether `text` can be written as a literal block: lines as they are, under a "|"."""
    if '\n' not in text.rstrip('\n') or text.endswith('\n\n') or text.startswith((' ', '\n')):
        return False
    for line in text.split('\n'):
        if line != line.rstrip() or any(ch < ' ' or ch in UNPRINTABLE or u'\x80' <= ch <= u'\x9f' or
                                        u'\ud800' <= ch <= u'\udfff' for ch in line):
            return False
    return True


def scalar(value, indent):
    """A value that is not a mapping or a list, as it goes after "key: " or "- "."""
    if isinstance(value, VaultReference):
        return quoted(value.text())
    if value is None:
        return 'null'
    if value is True:
        return 'true'
    if value is False:
        return 'false'
    if isinstance(value, int):
        return '%d' % value
    if isinstance(value, float):
        if math.isnan(value):
            return '.nan'
        if value in (float('inf'), float('-inf')):
            return '.inf' if value > 0 else '-.inf'
        text = repr(value)
        # YAML 1.1 takes 1e+300 for text: a number has a point in it.
        if 'e' in text and '.' not in text:
            text = text.replace('e', '.0e')
        return text
    text = '%s' % (value,)
    # What the server stores is data, also when it looks like a template:
    # without the tag, loading the file would try to render it.
    tag = '!unsafe ' if any(mark in text for mark in JINJA) else ''
    if block(text):
        lines = text.rstrip('\n').split('\n')
        pad = ' ' * indent
        return '%s|%s\n%s' % (tag, '' if text.endswith('\n') else '-',
                              '\n'.join(pad + line if line else '' for line in lines))
    if not tag and PLAIN.match(text) and text.lower() not in NOT_PLAIN:
        return text
    return tag + quoted(text)


def key_text(key):
    if not isinstance(key, str):
        raise ValueError('project_export: a mapping key has to be text, got %r' % (key,))
    if PLAIN.match(key) and ' ' not in key and key.lower() not in NOT_PLAIN:
        return key
    return quoted(key)


def emit(value, indent, lines):
    """Add `value`, a non-empty mapping or list, to `lines` in block style."""
    pad = ' ' * indent
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, (dict, list, tuple)) and item:
                lines.append('%s%s:' % (pad, key_text(key)))
                emit(item, indent + 2, lines)
            else:
                lines.append('%s%s: %s' % (pad, key_text(key), leaf(item, indent + 2)))
        return
    for item in value:
        if isinstance(item, (dict, list, tuple)) and item:
            nested = []
            emit(item, indent + 2, nested)
            lines.append('%s- %s' % (pad, nested[0][indent + 2:]))
            lines.extend(nested[1:])
        else:
            lines.append('%s- %s' % (pad, leaf(item, indent + 2)))


def leaf(value, indent):
    if isinstance(value, dict):
        return '{}'
    if isinstance(value, (list, tuple)):
        return '[]'
    return scalar(value, indent)


def comment(text):
    return '\n'.join('# %s' % line if line else '#' for line in text.replace('\r', ' ').split('\n'))


# ---- the filters --------------------------------------------------------------

def project_export_config(info, vault_prefix='vault'):
    """The project as the mapping project_apply reads, secrets as "{{ variable }}" text."""
    config, dummy = export_config(info, vault_prefix)
    return plain(config)


def project_export_vault_variables(info, vault_prefix='vault'):
    """The variables the exported project needs, in the order they appear, each with what it is."""
    dummy, vault = export_config(info, vault_prefix)
    return [dict(name=reference.variable, description=reference.what) for reference in vault.references]


def project_export_yaml(info, part=None, vault_prefix='vault'):
    """The project as YAML text: all of it, or one part ("project", or the name of a section).

    A part with nothing in it gives an empty text, so no file needs writing for it.
    """
    config, vault = export_config(info, vault_prefix)
    name = config['name']
    if part is None:
        body = config
    elif part == 'project':
        body = dict((key, value) for key, value in config.items() if key not in SECTIONS)
    elif part in SECTIONS:
        if part not in config:
            return ''
        body = {part: config[part]}
    else:
        raise ValueError('project_export: no part %r; it is "project" or one of %s' % (part, ', '.join(SECTIONS)))
    head = ['Harbor project %s' % name if part in (None, 'project') else 'Harbor project %s: %s' % (name, part),
            '',
            'Written by the ramanavelineni.harbor.project_export role from what the server',
            'returns. Each section is named after the module that manages its objects and',
            'takes that module\'s options.']
    if vault.references and part != 'project':
        head += ['', 'Harbor does not return robot secrets, and webhook auth headers and Slack',
                 'webhook URLs are kept out of the file. Each one is a variable here',
                 '("{{ %s_... }}"); define them in an Ansible Vault file.' % vault.stem]
    lines = []
    if part is None:
        # The project's own options, then one block per section.
        emit(dict((key, value) for key, value in body.items() if key not in SECTIONS), 0, lines)
        for section in SECTIONS:
            if section in body:
                lines.append('')
                emit({section: body[section]}, 0, lines)
    else:
        emit(body, 0, lines)
    return '---\n%s\n\n%s\n' % (comment('\n'.join(head)), '\n'.join(lines))


def project_export_vault(info, vault_prefix='vault'):
    """A file of the variables to fill in: one per secret, empty, with what it is above it."""
    config, vault = export_config(info, vault_prefix)
    head = ['Secrets of the Harbor project %s.' % config['name'],
            '',
            'Harbor does not return robot secrets, and webhook auth headers and Slack',
            'webhook URLs are kept out of the project file, so it refers to these variables.',
            'Give each its value and keep the result in an Ansible Vault file that the play',
            'applying the project loads. A robot secret needs at least 8 characters with',
            'upper and lower case letters and a digit.']
    lines = []
    for reference in vault.references:
        lines.append('')
        lines.append(comment(reference.what))
        lines.append('%s: ""' % reference.variable)
    if not vault.references:
        head += ['', 'This project has no secrets.']
        lines = ['', '{}']
    return '---\n%s\n%s\n' % (comment('\n'.join(head)), '\n'.join(lines))


class FilterModule(object):
    """Filters of the project_export role."""

    def filters(self):
        return dict(
            project_export_config=project_export_config,
            project_export_yaml=project_export_yaml,
            project_export_vault=project_export_vault,
            project_export_vault_variables=project_export_vault_variables,
        )
