# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""HTTP client and shared helpers for the ramanavelineni.semaphoreui modules.

The transport itself (the request loop, retries, masking, the failure
message) is in transport.py, which is the same in every collection of this
repository. This file adds what is Semaphore's own: the options, the login,
the API path and the lookups.
"""

import json
import os
import re

from datetime import datetime, timezone

from http.cookiejar import CookieJar

from ansible.module_utils.basic import env_fallback
from ansible.module_utils.urls import open_url

from ansible_collections.ramanavelineni.semaphoreui.plugins.module_utils import transport

# Defined in transport.py. The modules and tests import them from here.
MASK = transport.MASK
MESSAGE_BODY_LIMIT = transport.MESSAGE_BODY_LIMIT
MissingReference = transport.MissingReference
RETRY_STATUSES = transport.RETRY_STATUSES
fail_from_error = transport.fail_from_error
permanent_failure = transport.permanent_failure
scrub = transport.scrub
secret_forms = transport.secret_forms

# Major.minor releases the modules are tested against. Any other version
# gets a warning, not a failure: the API has been additive-only between
# these releases, but that is verified per release, not assumed.
TESTED_VERSIONS = ('2.18', '2.19')

# Semaphore caps some list endpoints (projects among them) at this many rows
# and has no paging for them. A list that comes back exactly this long may be
# missing rows, so lookups on it fail rather than create a duplicate.
LIST_CAP = 200

# Request bodies are shown in failures. Values under keys like these, and any
# value of a no_log option, are replaced first: Ansible's own masking only
# finds a secret that appears exactly as it was passed.
SECRET_KEYS = re.compile(r'secret|password|passphrase|private_key|token|alias', re.IGNORECASE)


def semaphore_argument_spec():
    """Connection options shared by every module (see doc fragment auth)."""
    return dict(
        url=dict(type='str', required=True, fallback=(env_fallback, ['SEMAPHORE_URL'])),
        # No env fallback here: it would fill these in before the "mutually
        # exclusive" check and make a token from the environment clash with a
        # username the task passes. resolve_credentials() reads the environment.
        api_token=dict(type='str', no_log=True),
        username=dict(type='str'),
        password=dict(type='str', no_log=True),
        validate_certs=dict(type='bool', default=True, fallback=(env_fallback, ['SEMAPHORE_VALIDATE_CERTS'])),
        ca_path=dict(type='path', fallback=(env_fallback, ['SEMAPHORE_CA_PATH'])),
        # client_key is the path of the key file, not the key: nothing to hide.
        client_cert=dict(type='path', fallback=(env_fallback, ['SEMAPHORE_CLIENT_CERT'])),
        client_key=dict(type='path', no_log=False, fallback=(env_fallback, ['SEMAPHORE_CLIENT_KEY'])),
        use_proxy=dict(type='bool', default=True, fallback=(env_fallback, ['SEMAPHORE_USE_PROXY'])),
        timeout=dict(type='int', default=30),
        retries=dict(type='int', default=3),
        retry_delay=dict(type='int', default=2),
    )


# The constraints a module may add to the shared ones, each a list as
# AnsibleModule takes it.
MODULE_CONSTRAINTS = ('mutually_exclusive', 'required_if', 'required_together', 'required_one_of')


def semaphore_module_kwargs(project=None, **constraints):
    """AnsibleModule keyword arguments that go with semaphore_argument_spec().

    A module passes the constraints between its own options by name, for
    example required_if=[('state', 'present', ('role',))]. They are added to
    the shared ones, so that the argument spec holds them and ansible-doc and
    the sanity tests see them.

    A module that takes project_argument_spec() passes project=PROJECT_REQUIRED
    or project=PROJECT_OPTIONAL. project and project_id then exclude each
    other, and with PROJECT_REQUIRED one of them must be set.
    """
    # Only what must hold for the options a task passes itself. That a
    # credential is there at all, and that a username has its password, is
    # checked by resolve_credentials(), after the environment is read.
    kwargs = dict(
        mutually_exclusive=[('api_token', 'username'), ('api_token', 'password')],
    )
    if project not in (None, PROJECT_REQUIRED, PROJECT_OPTIONAL):
        raise TypeError('semaphore_module_kwargs() takes project=%r or %r, not %r'
                        % (PROJECT_REQUIRED, PROJECT_OPTIONAL, project))
    if project is not None:
        kwargs['mutually_exclusive'].append(PROJECT_OPTIONS)
    if project == PROJECT_REQUIRED:
        kwargs['required_one_of'] = [PROJECT_OPTIONS]
    for name, rules in constraints.items():
        if name not in MODULE_CONSTRAINTS:
            raise TypeError('semaphore_module_kwargs() takes %s, not %r' % (', '.join(MODULE_CONSTRAINTS), name))
        kwargs[name] = kwargs.get(name, []) + list(rules)
    return kwargs


def resolve_credentials(module):
    """(api_token, username, password) to connect with: the task's options first, then the environment.

    Options the task passes win over the environment, as a whole: a task that
    passes a username doesn't use SEMAPHORE_API_TOKEN, and one that passes a
    token doesn't use SEMAPHORE_USERNAME. A username or password passed alone
    takes its other half from the environment. With nothing passed, the
    environment decides, and there a token wins over a username.
    """
    params = module.params
    env = dict((name, os.environ.get('SEMAPHORE_' + name.upper()) or None)
               for name in ('api_token', 'username', 'password'))
    token, username, password = params.get('api_token'), params.get('username'), params.get('password')
    if token is None and username is None and password is None:
        token = env['api_token']
        if token is None:
            username, password = env['username'], env['password']
    elif token is None:
        username = username if username is not None else env['username']
        password = password if password is not None else env['password']
    if token is None and username is None and password is None:
        module.fail_json(msg='one of the following is required: api_token, username')
    if token is None and (username is None or password is None):
        module.fail_json(msg='parameters are required together: username, password')
    # Secrets from the environment are not no_log option values; register them
    # so they are masked like the ones a task passes. Not every ansible-core
    # masks a result from this set any more, so the client also takes its own
    # credentials out of what a server answers (see scrub()).
    module.no_log_values.update(v for v in (token, password) if v)
    return token, username, password


def validate_connection(module):
    """Fail before any request on connection options that cannot work."""
    transport.validate_connection(module, 'Semaphore')


def base_url(url):
    """Server base URL without a trailing slash or /api suffix."""
    url = url.rstrip('/')
    if url.endswith('/api'):
        url = url[:-len('/api')]
    return url


def server_minor(version):
    """(major, minor) of a reported version ("v2.19.12-012ed06-...", "v2.19-rc1"), or None when it doesn't parse."""
    return transport.parse_version(version)


def redact(value, secrets=(), key=''):
    """A copy of a request body that is safe to show: secret strings replaced by MASK."""
    return transport.redact(value, SECRET_KEYS, secrets, key)


def version_is_tested(version):
    """True when a reported version ("v2.19.12", "2.18.30", "v2.19-rc1") is in TESTED_VERSIONS."""
    return transport.version_in(version, TESTED_VERSIONS)


class SemaphoreError(transport.ApiError):
    """A request failed. Carries everything needed to see why."""

    product = 'Semaphore'


class SemaphoreClient(transport.ApiClient):
    """Talks to the Semaphore API on behalf of one module run.

    With username/password the client logs in on first use and logs out in
    close(); with an API token every request carries it as a Bearer token.
    """

    error_class = SemaphoreError
    secret_keys = SECRET_KEYS

    def __init__(self, module):
        super(SemaphoreClient, self).__init__(module)
        self.url = base_url(module.params['url'])
        self.api_token, self.username, self.password = resolve_credentials(module)
        # A server can repeat a credential in an error. Wherever it came from,
        # it is taken out of what a failure shows of the answer, together with
        # every other no_log value of the task (see secrets).
        self.credentials = (self.api_token, self.password)
        self.cookies = CookieJar()
        self.logged_in = False
        self._info = None

    @property
    def secrets(self):
        """Every value an answer must not show: the credentials and the task's no_log values."""
        return set(v for v in self.credentials if v) | set(self.module.no_log_values)

    def open(self, url, **kwargs):
        # The session cookie of a login goes with every request of the run.
        return open_url(url, cookies=self.cookies, **kwargs)

    # -- session -----------------------------------------------------------

    def login(self):
        if self.api_token or self.logged_in:
            return
        # A login only opens a session, so it is safe to retry.
        self._request('POST', '/auth/login',
                      body={'auth': self.username, 'password': self.password},
                      expected=(204,), retry=True)
        self.logged_in = True

    def close(self):
        """Log out if this client logged in. Never raises."""
        if not self.logged_in:
            return
        try:
            self._request('POST', '/auth/logout', expected=(204,), retry=False)
        except SemaphoreError:
            pass
        self.logged_in = False

    # -- requests ----------------------------------------------------------

    def get(self, path):
        return self.request('GET', path, expected=(200,), retry=True)

    def post(self, path, body, expected=(201,)):
        # Most creates answer 201; a few (integration aliases and matchers)
        # answer 200, and their callers say so.
        return self.request('POST', path, body=body, expected=expected, retry=False)

    def put(self, path, body):
        return self.request('PUT', path, body=body, expected=(204,), retry=True)

    def delete(self, path):
        return self.request('DELETE', path, expected=(204,), retry=False)

    def request(self, method, path, body=None, expected=(200,), retry=False):
        self.login()
        return self._request(method, path, body=body, expected=expected, retry=retry)

    def _request(self, method, path, body=None, expected=(200,), retry=False):
        headers = {}
        if self.api_token:
            headers['Authorization'] = 'Bearer %s' % self.api_token
        return self.send(method, '%s/api%s' % (self.url, path), body=body, headers=headers,
                         expected=expected, retry=retry)[0]

    # -- server ------------------------------------------------------------

    def info(self):
        """GET /api/info, cached for the module run."""
        if self._info is None:
            self._info = self.get('/info') or {}
        return self._info

    def warn_if_untested(self):
        version = self.info().get('version', '')
        if not version_is_tested(version):
            self.module.warn(
                'Semaphore reports version %r, which this collection has not been tested with '
                '(tested: %s). Continuing.' % (version, ', '.join(TESTED_VERSIONS)))

    # -- lookups -----------------------------------------------------------

    def list(self, path, capped=False):
        items = self.get(path) or []
        if not isinstance(items, list):
            raise ValueError('GET %s/api%s did not return a list. Is url the address of a Semaphore server?'
                             % (self.url, path))
        if capped and len(items) >= LIST_CAP:
            raise ValueError(
                'GET %s/api%s returned %d rows, the most Semaphore returns for this list. Rows past '
                'the cap are invisible, so looking up by name could miss an existing object and '
                'create a duplicate. Refusing to continue.' % (self.url, path, len(items)))
        return items


def find_by_name(items, name, what, field='name'):
    """The single item whose `field` equals `name`, or None.

    Semaphore does not enforce unique names, so two matches is an error the
    caller has to fix by hand: picking one would be a guess.
    """
    matches = [item for item in items if item.get(field) == name]
    if len(matches) > 1:
        raise ValueError(
            'More than one %s is named %r (ids %s). Names must be unique for this module to '
            'manage them; rename or delete the extra ones in Semaphore.'
            % (what, name, ', '.join(str(m.get('id')) for m in matches)))
    return matches[0] if matches else None


def resolve_project(client, name, missing_ok=False):
    """Id of the project named `name`; fails when there is none, or returns None with missing_ok."""
    project = find_by_name(client.list('/projects', capped=True), name, 'project')
    if project is None:
        if missing_ok:
            return None
        raise MissingReference(
            'Project %r does not exist, or the user this module logs in as cannot see it.' % name)
    return project['id']


# The two ways a task names its project (see doc fragment project).
PROJECT_OPTIONS = ('project', 'project_id')

# What semaphore_module_kwargs(project=...) takes: whether a module needs a
# project (doc fragment project) or also works without one (project.optional).
PROJECT_REQUIRED = 'required'
PROJECT_OPTIONAL = 'optional'


def project_argument_spec():
    """The options project and project_id, which every module that works in a project takes."""
    return dict(project=dict(type='str'), project_id=dict(type='int'))


def project_ref(client, params, missing_ok=False):
    """(id, name) of the project a task names with `project` or `project_id`.

    (None, None) when the task names none, or with missing_ok when the
    project doesn't exist. By name the project is looked up in the project
    list, which Semaphore cuts off at LIST_CAP rows. By id only that project
    is read, so it is found however many projects there are, and its name is
    there for messages and results.
    """
    if params.get('project_id') is None:
        if params.get('project') is None:
            return None, None
        return resolve_project(client, params['project'], missing_ok=missing_ok), params['project']
    project = read_project(client, params['project_id'])
    if project is None:
        if missing_ok:
            return None, None
        raise MissingReference(missing_project_id(params['project_id']))
    return params['project_id'], project.get('name')


def read_project(client, project_id):
    """The project with this id, or None when there is none or the user cannot see it.

    Reads only that project, not the list Semaphore cuts off at LIST_CAP rows.
    """
    try:
        return client.get('/project/%d' % project_id) or {}
    except SemaphoreError as e:
        # Semaphore answers the same for a project that isn't there and for
        # one the user is no member of.
        if e.status not in (403, 404):
            raise
        return None


def missing_project_id(project_id):
    return 'Project with id %d does not exist, or the user this module logs in as cannot see it.' % project_id


def refuse_delete_if_used(client, path, what, name):
    """Fail with what still uses the object at `path` (via its /refs), if anything.

    Semaphore refuses such a delete itself, but its answer is misleading:
    2.19 always blames templates and 2.18 sends an empty body.
    """
    refs = client.get(path + '/refs') or {}
    used = ['%s %s' % (kind.replace('_', ' '), ', '.join(sorted(r.get('name') or str(r.get('id')) for r in items)))
            for kind, items in sorted(refs.items()) if items]
    if used:
        raise ValueError('Cannot delete %s %r: it is still used by %s. Change or delete those first.'
                         % (what, name, '; '.join(used)))


def diff_fields(desired, current):
    """Keys of `desired` whose value differs from `current`. None means "not managed"."""
    return sorted(k for k, v in desired.items() if v is not None and current.get(k) != v)


def run_module(module, handler, placeholder=None):
    """Run handler(client) with login/logout and uniform error reporting.

    `placeholder` holds the module's own return values, empty. With it, a
    MissingReference in check mode is reported as a change instead of a failure.
    """
    transport.run_client(module, SemaphoreClient(module), handler, placeholder)


# -- views: objects as the modules and their _info modules return them --------


def project_view(project):
    """The API omits false/zero/null fields; fill them in so values compare."""
    return dict(
        id=project.get('id'),
        name=project.get('name'),
        alert=bool(project.get('alert', False)),
        alert_chat=project.get('alert_chat') or '',
        max_parallel_tasks=int(project.get('max_parallel_tasks') or 0),
        type=project.get('type') or '',
    )


def user_view(user):
    return dict(
        id=user.get('id'), username=user.get('username'), name=user.get('name') or '',
        email=user.get('email') or '', admin=bool(user.get('admin', False)),
        alert=bool(user.get('alert', False)), external=bool(user.get('external', False)),
    )


def repository_view(repo, key_names):
    return dict(
        id=repo.get('id'),
        name=repo.get('name'),
        git_url=repo.get('git_url') or '',
        git_branch=repo.get('git_branch') or '',
        ssh_key_id=repo.get('ssh_key_id'),
        ssh_key=key_names.get(repo.get('ssh_key_id')),
        project_id=repo.get('project_id'),
    )


# option -> (id field, what it names, list endpoint)
INVENTORY_REFERENCES = dict(
    repository=('repository_id', 'repository', 'repositories'),
    ssh_key=('ssh_key_id', 'key', 'keys'),
    become_key=('become_key_id', 'key', 'keys'),
)


def inventory_view(inv, names):
    out = dict(id=inv.get('id'), name=inv.get('name'), type=inv.get('type'),
               inventory=inv.get('inventory') or '', project_id=inv.get('project_id'))
    for option, (field, dummy, endpoint) in INVENTORY_REFERENCES.items():
        out[field] = inv.get(field)
        out[option] = names[endpoint].get(inv.get(field))
    return out


def json_field(text, empty):
    """A field Semaphore stores as JSON in a string: the parsed value, or the string as stored when it isn't valid JSON.

    `empty` stands in for a field that is not set (null or ""). Every module
    that returns such a field reads it with this, so bad input gets one rule.
    """
    if text is None or text == '':
        return empty
    try:
        return json.loads(text)
    except ValueError:
        return text


def variable_group_view(group, secrets):
    """A variable group as modules return it: json/env parsed (see json_field), secrets as name/type."""
    return dict(
        id=group.get('id'), name=group.get('name'), project_id=group.get('project_id'),
        json=json_field(group.get('json'), {}),
        env=json_field(group.get('env'), {}),
        secrets=sorted((dict(name=s['name'], type=s['type']) for s in secrets), key=lambda s: s['name']),
    )


def parse_time(value):
    """An ISO 8601 time as a datetime (naive when it names no time zone), or None when it doesn't parse."""
    text = value.strip()
    if text[-1:] in ('Z', 'z'):
        text = text[:-1] + '+00:00'
    if '.' in text:
        # Go sends up to nanoseconds; Python parses at most microseconds.
        head, rest = text.split('.', 1)
        digits = len(rest) - len(rest.lstrip('0123456789'))
        text = head + '.' + rest[:digits][:6].ljust(6, '0') + rest[digits:]
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def normalize_time(value):
    """An ISO 8601 time as a comparable UTC string, or the input when it doesn't parse."""
    if not value:
        return None
    moment = parse_time(value)
    if moment is None:
        return value
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
    return moment.strftime('%Y-%m-%dT%H:%M:%S') + (moment.strftime('.%f') if moment.microsecond else '') + 'Z'


def all_schedules(client, base, templates, name=None):
    """Every schedule in the project, with its template's name.

    The project list leaves out commit pollers, and each template's list has
    only its pollers; together they are complete. Neither carries a
    schedule's task-parameter overrides: read the schedule itself for those.

    With `name`, the caller wants only the schedule of that name. When the
    project list has it, the template lists are not read: that is one request
    per template saved, at the price of not noticing a commit poller of the
    same name.

    A schedule that both lists return is kept once.
    """
    out = client.list(base + '/schedules')
    if name is not None and any(sched.get('name') == name for sched in out):
        return out
    seen = set(sched.get('id') for sched in out)
    names = dict((t['id'], t.get('name')) for t in templates)
    for tpl in templates:
        for sched in client.list('%s/templates/%d/schedules' % (base, tpl['id'])):
            if sched.get('id') in seen:
                continue
            seen.add(sched.get('id'))
            out.append(dict(sched, tpl_name=names.get(sched.get('template_id'))))
    return out


def schedule_view(sched, repos, templates):
    """A schedule as the schedule modules return it."""
    kind = 'run_at' if sched.get('type') == 'run_at' else ('poller' if sched.get('repository_id') else 'cron')
    return dict(
        id=sched.get('id'), name=sched.get('name'), project_id=sched.get('project_id'),
        template=templates.get(sched.get('template_id')), kind=kind,
        cron=sched.get('cron_format') or '', repository=repos.get(sched.get('repository_id')),
        run_at=normalize_time(sched.get('run_at')), delete_after_run=bool(sched.get('delete_after_run', False)),
        active=bool(sched.get('active', False)),
    )


MATCHER_FIELDS = ('match_type', 'method', 'body_data_type', 'key', 'value')
VALUE_FIELDS = ('value_source', 'body_data_type', 'key', 'variable', 'variable_type')
# The API spells "no authentication" as "".
NO_AUTH = 'none'


def item_view(item, fields):
    """An integration matcher or extracted value, with the given fields."""
    return dict([('name', item.get('name'))] + [(f, item.get(f) or '') for f in fields])


def integration_view(integ, templates, keys, matchers, values):
    """An integration as the integration modules return it."""
    return dict(
        id=integ.get('id'), name=integ.get('name'), project_id=integ.get('project_id'),
        template=templates.get(integ.get('template_id')),
        auth_method=integ.get('auth_method') or NO_AUTH,
        auth_key=keys.get(integ.get('auth_secret_id')),
        auth_header=integ.get('auth_header') or '',
        searchable=bool(integ.get('searchable', False)),
        matchers=sorted((item_view(m, MATCHER_FIELDS) for m in matchers), key=lambda m: m['name']),
        extract_values=sorted((item_view(v, VALUE_FIELDS) for v in values), key=lambda v: v['name']),
    )
