# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""Filters of the project_export role: what the _info modules return, as the configuration project_apply reads.

A project is described by a mapping: the project's own options, and one
section per kind of object, keyed by object name, with the options of the
module that manages it. The _info modules return each object in the shape of
its module (plus ids and what only the server knows), so turning one into the
other is a matter of leaving things out:

  - ids, and fields the server fills in (a view's type, a schedule's kind, an
    integration's webhook URLs, the repositories that use a key);
  - options that hold what an object gets when it is created without them,
    so the file shows what was chosen and not every checkbox;
  - secrets, which Semaphore never returns. Each becomes a reference to a
    variable ("{{ vault_... }}"), and the variables are listed for a vault.

Only the Python standard library is used: no YAML library, no ansible import.
"""

import re

# In the order project_apply applies them: what is referred to comes first.
SECTIONS = ('key_store', 'repository', 'inventory', 'variable_group', 'view', 'template', 'schedule', 'integration',
            'team_member')

# The field of an _info object that names it, where it is not "name".
NAME_FIELD = dict(team_member='username')

# Options of the project itself, with what a new project has.
PROJECT_OPTIONS = (('alert', False), ('alert_chat', ''), ('max_parallel_tasks', 0))

# Per section: the options to write, in the order the modules document them,
# each with what an object created without that option has. KEEP means the
# option is always written. Options that are not here are either never
# returned (secrets, see SECRETS) or mean something for a run only (state,
# update_secret, purge_secrets, force_repository_key_update, confirm_delete).
KEEP = object()
OPTIONS = dict(
    key_store=(('type', KEEP),),
    repository=(('git_url', KEEP), ('git_branch', KEEP), ('ssh_key', None)),
    inventory=(('type', KEEP), ('inventory', KEEP), ('repository', None), ('ssh_key', None), ('become_key', None)),
    variable_group=(('json', {}), ('env', {}), ('secrets', [])),
    view=(('position', KEEP), ('hidden', False), ('sort_column', ''), ('sort_reverse', False)),
    template=(
        ('app', KEEP), ('playbook', KEEP), ('repository', KEEP), ('inventory', None), ('variable_groups', KEEP),
        ('view', None), ('description', ''), ('git_branch', ''), ('arguments', []), ('type', 'task'),
        ('start_version', ''), ('build_template', None), ('autorun', False), ('allow_override_args_in_task', False),
        ('allow_override_branch_in_task', False), ('allow_parallel_tasks', False), ('suppress_success_alerts', False),
        ('runner_tag', ''), ('task_params', {}), ('vaults', []), ('survey_vars', []),
    ),
    schedule=(('template', KEEP), ('cron', ''), ('repository', None), ('run_at', None), ('delete_after_run', False),
              ('active', True)),
    integration=(('template', KEEP), ('auth_method', 'none'), ('auth_key', None), ('auth_header', ''),
                 ('searchable', False), ('matchers', []), ('extract_values', [])),
    team_member=(('role', KEEP),),
)

# Options that are lists of mappings: the keys of an entry, in order, with the
# default the module's argument spec gives each (KEEP: none, always written).
ENTRIES = {
    ('variable_group', 'secrets'): (('name', KEEP), ('type', 'env')),
    ('template', 'vaults'): (('name', 'default'), ('type', 'password'), ('key', None), ('script', '')),
    ('template', 'survey_vars'): (('name', KEEP), ('title', KEEP), ('type', 'string'), ('required', False),
                                  ('description', ''), ('default_value', ''), ('values', [])),
    ('integration', 'matchers'): (('name', KEEP), ('match_type', 'body'), ('method', 'equals'),
                                  ('body_data_type', 'json'), ('key', KEEP), ('value', KEEP)),
    ('integration', 'extract_values'): (('name', KEEP), ('value_source', 'body'), ('body_data_type', 'json'),
                                        ('key', ''), ('variable', KEEP), ('variable_type', 'environment')),
}

# What Semaphore never returns, and so has to come from a vault. Per key type:
# the option that holds the secret and its fields. The login of a key is not
# marked as a secret in the module, but it is stored with the secret and not
# returned either, so it is asked for as well.
KEY_SECRETS = dict(
    ssh=('ssh', ('login', 'passphrase', 'private_key')),
    login_password=('login_password', ('login', 'password')),
)
# The options the modules mark no_log, as section -> dotted paths. A unit test
# holds this against the modules' argument specs.
SECRETS = dict(
    key_store=('login_password.password', 'ssh.passphrase', 'ssh.private_key'),
    variable_group=('secrets.value',),
)

# A word for each section inside a variable name.
SECTION_WORD = dict(key_store='key', variable_group='var')

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


def entries(section, option, value):
    """A list of mappings with the keys the module has, without the ones at their default."""
    keys = ENTRIES[(section, option)]
    out = []
    for entry in value or []:
        kept = {}
        for key, default in keys:
            if key not in entry:
                continue
            item = entry[key]
            if key == 'values':
                # The choices of an enum survey variable: name and value, always both.
                item = [dict(name=choice.get('name'), value=choice.get('value')) for choice in item or []]
            if default is KEEP or item != default:
                kept[key] = item
        out.append(kept)
    return out


def object_options(section, found, vault):
    """One _info object as the options of its module."""
    name = name_of(section)(found)
    out = {}
    for option, default in OPTIONS[section]:
        if option not in found:
            continue
        value = found[option]
        if (section, option) in ENTRIES:
            value = entries(section, option, value)
        if default is KEEP or value != default:
            out[option] = value

    if section == 'key_store':
        option, fields = KEY_SECRETS.get(found.get('type'), (None, ()))
        if option:
            out[option] = dict((field, vault.reference(section, name, '%s_%s' % (option, field),
                                                       'key %s: %s.%s' % (name, option, field)))
                               for field in fields)
    elif section == 'variable_group':
        for secret in out.get('secrets', []):
            secret['value'] = vault.reference(section, name, secret['name'],
                                              'variable group %s: the value of secret %s' % (name, secret['name']))
    elif section == 'schedule':
        kind = found.get('kind')
        if kind == 'run_at':
            out.pop('cron', None)
        elif kind == 'poller':
            # Semaphore runs a commit poller whether it is active or not, and the module refuses active for one.
            out.pop('active', None)
    return name, out


def build_templates_first(found):
    """Templates by name, each deploy template after the build template it names: project_apply creates them in order."""
    by_name = dict((template['name'], template) for template in found)
    ordered, done = [], set()

    def place(name, trail):
        if name in done or name not in by_name or name in trail:
            return
        place(by_name[name].get('build_template'), trail + (name,))
        done.add(name)
        ordered.append(by_name[name])

    for name in sorted(by_name):
        place(name, ())
    return ordered


def name_of(section):
    """The function that gives the name of an _info object of `section`, as text."""
    field = NAME_FIELD.get(section, 'name')

    def name(found):
        return '%s' % (found[field],)
    return name


def export_config(info, vault_prefix='vault'):
    """(config, vault): the mapping project_apply reads, and the Vault with the references in it."""
    if not isinstance(info, dict) or not isinstance(info.get('project'), dict) or not info['project'].get('name'):
        raise ValueError('project_export needs a mapping with the project (as project_info returns it) under "project" '
                         'and the lists of the _info modules under the section names: %s' % ', '.join(SECTIONS))
    project = info['project']
    vault = Vault(vault_prefix, project['name'])
    config = dict(name=project['name'])
    for option, default in PROJECT_OPTIONS:
        if option in project and project[option] != default:
            config[option] = project[option]
    for section in SECTIONS:
        found = info.get(section) or []
        if not isinstance(found, (list, tuple)):
            raise ValueError('project_export: "%s" has to be the list the %s_info module returns' % (section, section))
        if section == 'template':
            found = build_templates_first(found)
        else:
            found = sorted(found, key=name_of(section))
        objects = {}
        for item in found:
            name, options = object_options(section, item, vault)
            if name in objects:
                raise ValueError('project_export: %s has two entries named %r; a mapping can hold one' % (section, name))
            objects[name] = options
        if objects:
            config[section] = objects
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


# ---- YAML -------------------------------------------------------------------

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
        if value != value:
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
    text = key
    if PLAIN.match(text) and ' ' not in text and text.lower() not in NOT_PLAIN:
        return text
    return quoted(text)


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


def to_yaml(value):
    lines = []
    emit(value, 0, lines)
    return '\n'.join(lines) + '\n'


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
    head = ['Semaphore project %s' % name if part in (None, 'project') else 'Semaphore project %s: %s' % (name, part),
            '',
            'Written by the ramanavelineni.semaphoreui.project_export role from what the server',
            'returns. Each section is keyed by object name; the options are those of the',
            'module of that name.']
    if vault.references and part != 'project':
        head += ['', 'Semaphore does not return a stored secret. Each one is a variable here',
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
    head = ['Secrets of the Semaphore project %s.' % config['name'],
            '',
            'Semaphore does not return a stored secret, so the exported project refers to',
            'these variables. Give each its value and keep the result in an Ansible Vault',
            'file that the play applying the project loads. A value may stay empty where',
            'the object has none (a key without a passphrase or a login name).']
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
