# Plan: ramanavelineni.harbor and ramanavelineni.semaphoreui

Two Ansible collections that manage Harbor and Semaphore UI declaratively, so
roles call one idempotent module per resource instead of writing their own
REST calls with `ansible.builtin.uri`.

They start from the two roles in the homelab ansible repo,
`roles/harbor_config` and `roles/semaphore_config`, which already cover
both APIs and work around their quirks. The collections move that knowledge
into Python modules and make it usable by anyone.

Status: semaphoreui phases 1–3 complete (every module listed below, with its `_info` module). Harbor: scaffold, client, `info`, `project`, `project_info`; the other Harbor areas are in progress.

---

## Decisions

| Topic | Decision |
|---|---|
| Namespace | `ramanavelineni`: collections `ramanavelineni.harbor` and `ramanavelineni.semaphoreui` |
| Repository | this monorepo, public at <https://github.com/ramanavelineni/ansible-collections> |
| Deletion | each resource module takes `state: present \| absent` |
| Module names | follow the Semaphore 2.19 UI labels: `key_store`, `variable_group`, `team_member`, `template`, …, plus `*_info` |
| Project references | objects inside a project take `project: <name>` |
| Deleting an object in use | fails with the list from Semaphore's `/refs` endpoint (Semaphore's own answer is misleading) |
| Module imports | modules import only `module_utils`: Ansible ships nothing else with a module, and sanity's import test enforces it |
| License hygiene | no GPL-licensed ansible-core code is imported, extended or copied: only its BSD `module_utils` and the Python standard library |
| License | Apache-2.0 |
| CI | `ansible-test sanity` and unit tests only; no integration tests against live servers in CI |
| Distribution | install from Git tags via `requirements.yml`; publishing to Ansible Galaxy is optional and can come later |
| ansible-core | 2.18 and newer, CI on 2.18, 2.19, 2.20 and 2.21 (the versions still getting releases; the homelab controller runs 2.19) |
| Option names | follow the `semaphore_config` role's YAML (same keys, name-based references), so the role can pass its dicts straight through; fields the role doesn't use keep the API's names |
| Unit-test fixtures | recorded from a throwaway local Semaphore container (2.18 and 2.19, SQLite) on the development machine, never from the homelab |
| Tooling | Makefile targets for local runs, `ansible-community/ansible-test-gh-action` in CI, light pre-commit hooks |
| Commits | first commit (scaffolding only) directly on `main`; everything after goes through a feature branch and pull request; no Co-Authored-By trailer; the owner pushes |
| Harbor | Harbor v2 API, tested against 2.14 and 2.15 (fixtures from 2.14.4 and 2.15.2; the homelab runs 2.15.1) |
| Semaphore | tested against 2.18 and 2.19, matching `semaphore_config_tested_versions` |

Apache-2.0 fits with ansible-core: modules import `ansible.module_utils.basic`
and `ansible.module_utils.urls`, which are BSD-2-Clause licensed, so an Apache
collection can use them. The one restriction is that Apache-licensed
collections cannot be added to the Ansible community package, which isn't a
goal.

---

## Repository layout

`ansible-test` only runs when a collection sits at
`ansible_collections/<namespace>/<name>/`, so both collections live under
that path:

```
ansible-collections/
├── PLAN.md
├── README.md                  # what is here, how to install from Git
├── LICENSE                    # Apache-2.0
├── Makefile                   # make sanity / units / changelog-lint / build
├── .pre-commit-config.yaml    # whitespace, YAML, changelog lint
├── .github/workflows/ci.yml   # sanity + unit, matrix per collection and ansible-core
└── ansible_collections/ramanavelineni/
    ├── semaphoreui/
    │   ├── galaxy.yml
    │   ├── README.md
    │   ├── CHANGELOG.md / changelogs/     # antsibull-changelog fragments
    │   ├── meta/runtime.yml               # requires_ansible: ">=2.18.0"
    │   ├── plugins/
    │   │   ├── doc_fragments/auth.py      # shared connection options
    │   │   ├── module_utils/semaphore.py  # HTTP client, pagination, diff helpers
    │   │   └── modules/
    │   └── tests/unit/
    └── harbor/
        └── (same shape; module_utils/harbor.py, fixtures per area)
```

Each collection stands alone, with no dependency between them. The small
HTTP client is duplicated rather than shared: collections cannot import each
other's `module_utils` without declaring a dependency, and the two APIs
authenticate differently anyway.

---

## Conventions for every module

These apply to both collections and replace what each role now does by hand.

1. **Declarative and idempotent.** A module reads the current object, compares
   it with the desired one, and writes only when they differ. `changed`
   reflects a real difference. Every module supports check mode and
   `--diff`.
2. **Look up by name.** A resource is identified by its name (and its project,
   where it belongs to one). A module fails if it finds more than one object
   with that name; Semaphore doesn't enforce unique names.
3. **References by name.** When one resource points at another, the module
   takes the other resource's name and resolves the id itself. For example, a
   template's `repository: homelab` instead of `repository_id: 3`. This moves
   the roles' name→id maps into the modules.
4. **Updates send the whole object.** Where the API replaces the whole row on
   PUT (Semaphore templates, inventories), the module starts from the current
   object, applies the desired fields and sends everything, so unset fields
   are never wiped by accident.
5. **Secrets.** Neither API ever returns a secret, so drift in a secret can't be
   detected. Secret options are `no_log` and paired with
   `update_secret: always | on_create` (default `always`, which is how the
   roles behave today). Writing a secret always counts as a change.
6. **Connection options** come from one doc fragment per collection:
   `url`, `username` / `password` or `token`, `validate_certs`, `ca_path`,
   `timeout`, `retries`, `retry_delay`. Requests go through
   `ansible.module_utils.urls.open_url`, which supports `ca_path`, so the
   step-ca CA works without changing the trust store. The options can also
   be read from environment variables (`HARBOR_URL`, `SEMAPHORE_URL`, …) so
   `module_defaults` stays short.
7. **Retries** apply to reads and idempotent PUTs only. Creates are never
   retried, because a connection reset after the server has already acted
   would create a duplicate. This is the same rule the roles follow.
8. **Useful failures.** On an HTTP error the module reports the method, URL,
   status, response body and the request body, with secrets masked. This
   replaces the `semaphore_config` rescue block, which dumped the raw request.
9. **Pagination.** List reads follow every page. There is no silent cap.
10. **`_info` modules** exist for each resource, for reading without
    changing anything.
11. **No cascading deletes.** `state: absent` removes only the named object and
    fails if the API refuses because other objects still use it.

---

## ramanavelineni.harbor

Scope matches `roles/harbor_config`. Harbor API v2, HTTP basic auth only
(admin, user, robot account, or an OIDC user's CLI secret), with
`HARBOR_*` environment fallbacks. Module names follow the Harbor UI labels,
singular. Robot and write-only configuration secrets follow `update_secret`
(`always` / `on_create`), as in semaphoreui.

| Module | Manages | Notes |
|---|---|---|
| `configuration` | `/configurations` system settings, including auth mode and OIDC | done. Partial PUT: only the keys given are compared and sent. Harbor silently ignores unknown keys (and read-only `scan_all_policy`) and answers a wrong type with 422, so keys and types are checked first (57 writable keys, identical in 2.14 and 2.15). `oidc_client_secret` and `ldap_search_password` are write-only: separate `no_log` options following `update_secret` (`on_create` = only while the partner `oidc_client_id` / `ldap_search_dn` is empty or changing). `uaa_client_secret` is returned in clear text: compared, never output. `auth_mode` can only change while no user but the admin exists |
| `garbage_collection`, scan-all, audit-log purge | job schedules | create or update on cron drift |
| `registry` | registry endpoints (proxy-cache upstreams, replication targets) | done. Create and update ping the endpoint (400 `the registry is unhealthy`, or a bare 500 for some adapters); the update merges the given fields; `type` has no update field, so a different type fails with instructions, but `url` can change (the role refused it; Harbor strips a trailing slash); the option is `endpoint_url` because `url` is the connection; the secret comes back as `*****`, so it follows `update_secret`; `ca_certificate` exists only in 2.15 (2.14 silently ignores it: the module fails there); delete answers 412 while a replication rule or proxy-cache project uses the endpoint |
| `project` | projects: public, metadata, proxy-cache registry, storage quota | done. `PUT /projects/{id}` merges the given metadata keys; a top-level `public` is ignored (sent as `metadata.public`); Harbor silently drops unknown metadata keys and stores an invalid severity as `unknown`, so keys and values are checked first (2.15 adds `proxy_cache_local_on_not_found`); the proxy-cache registry can't change after creation: fail with instructions; create answers 201 with an empty body and the id in `Location`; `/projects/<n>` takes a numeric `<n>` as an id, so projects are addressed by id; quota via `/quotas?reference=project&reference_id=` and `PUT /quotas/{id}`; delete needs `confirm_delete` and fails first while repositories remain |
| `robot_account` | system and project robot accounts, permissions, secret | name matched without Harbor's robot name prefix (system: `q=name` matches the stored name; project: stored as `<project>+<name>`, found in the project's list); create ignores a `secret` in the body and always generates one, so a declared secret is set with `PATCH /robots/{id}` right after (8-128 characters with upper, lower and digit, checked before writing); without one the generated secret is returned on create only (module results can't be masked: set `no_log` on the task); PUT needs the full prefixed name and the level (else 400), overwrites description and disable, replaces permissions (must be non-empty), so every field goes back; permissions compared as sets (read-back order is random); `namespace: '*'` = every project including future ones (the role's `projects: all`); identical in 2.14.4 and 2.15.2 |
| `tag_retention` | a project's tag retention policy (at most one; linked by project metadata `retention_id`) | done. Rules and schedule; `rules` is the exact list. Harbor checks only the cron (6 fields), duplicate rules (409) and the 15-rule limit, and stores an unknown template or a missing/non-integer count as given, so the module validates rules first. An empty cron means no schedule. The module never starts a run. Identical in 2.14 and 2.15 |
| `tag_immutability` | one tag immutability rule per call, identified by its repository/tag patterns and decorations | done. A new rule is always stored enabled (a disabled one takes a create plus a toggle); an update either toggles `disabled` (then Harbor ignores the rest of the body) or rewrites the selectors, never both, so the module only toggles and treats other patterns as another rule. Duplicates get 409; no rule limit |
| `webhook` | webhook policies per project | `auth_header` is returned by Harbor in plain text, so it is compared like any option (no `update_secret`) but never put in results; PUT replaces the whole policy (omitted `enabled` becomes false, description and auth header are emptied) and resets `creation_time`, so the current policy goes back with the changes; one endpoint per webhook as the UI makes (the API allows several: the module refuses to edit targets then); `skip_cert_verify: false` and the default payload format are omitted from reads, so targets are compared normalised; slack targets take no payload format; duplicate names 409; 2.14 and 2.15 identical |
| `replication` | replication rules (UI: Administration > Replications) | done. Exactly one side is a remote endpoint, the other the local Harbor (returned as registry id 0, "Local"); the update replaces the whole rule (an omitted `dest_namespace_replace_count` becomes -1), so every field goes back; cron has 6 fields, seconds must be 0 and minutes can't be `*`; `single_active_replication` with an `event_based` trigger is a bare 500, so it fails first; filters compared without regard to order (label values too); `decoration` only for tag and label filters |
| `info` | server version | done. Harbor answers `/systeminfo` (and even `/projects`, with public projects only) anonymously when the credentials are wrong; only an authenticated `/systeminfo` carries `harbor_version`, so every module checks that first and fails on bad credentials |
| `*_info` | read-only versions of the above | |

Before building, compare against `xrow.harbor` on Galaxy and note any
behaviour worth matching (option names, how robot secrets are handled).

---

## ramanavelineni.semaphoreui

Scope matches `roles/semaphore_config`. Authentication is by API token
(recommended) or username/password. With a password, each module logs in and
out within its own call, so no session state crosses tasks.

| Module | Manages | Quirks to handle inside the module |
|---|---|---|
| `user` | global users | options `login` / `user_password` (the connection options own `username` / `password`); PUT rewrites name, username, email, alert, admin and pro together, so the current values go back; the password has its own endpoint (no current password needed for an admin setting someone else's) and follows `update_secret`; `external` is fixed at creation and external users take no password (Semaphore answers 400); duplicate emails get a bare 400, so they fail early; the login user is never changed or deleted (its password is skipped with a warning); Semaphore 2.18 can't delete a user who ever logged in (no ON DELETE CASCADE on sessions until 2.19: bare 500), explained in the failure |
| `runner` | global and project runners | a new runner has no credentials: the module asks for a one-time registration token (valid 1 hour) right after creating it and returns it; `regenerate_token` gets a new one, which resets an already registered runner; the update replaces every field (tags included), so the whole runner is sent; the global list includes project runners, so global lookups filter on `project_id`; project runners are Pro-only (Community lists none and answers 403 on create), so their success paths are unit-tested only |
| `project` | projects | the API caps the list at 200 rows: fail rather than miss projects; `state: absent` needs `confirm_delete: true` because it deletes everything inside |
| `key_store` | Key Store entries (`ssh`, `login_password`, `none`) | PUT needs `id` and `project_id` in the body and `override_secret: true`, or the secret is silently ignored. Secret required on create; omitted on an existing key means "leave it". Type changes happen in place (a change to `ssh`/`login_password` needs the secret). **Every update of a key a repository uses makes Semaphore delete that repository's checkouts**: such a key's secret is skipped with a warning, and a type change fails, unless `force_repository_key_update: true` |
| `repository` | Git repositories and local paths | `git_branch` required unless `git_url` is a local path; changing `git_url` deletes the checkouts |
| `inventory` | `file`, `static`, `static-yaml` inventories | PUT replaces the whole row; Semaphore rejects any update of a `file` inventory whose path is outside its working directory (so any absolute path), though it accepts it on create: fail with an explanation; `""` clears a repository/key reference |
| `variable_group` | variable groups (environments) and their secrets | secrets are a list of `{name, type, value}` (a dict keyed by name would mask the words `env`/`var` in all output once marked `no_log`); `update_secret` like `key_store`; undeclared secrets left alone unless `purge_secrets: true`; a type change is a delete + create in one update |
| `view` | UI tabs: position, hidden, sort | the update must send the current `type` back; the built-in `All` view can't be deleted by the module; `filter` isn't written by Semaphore's update and is left alone |
| `template` | task templates, including build/deploy, vaults and surveys | the list omits `vaults`, so each template is read on its own; PUT rewrites every column and the vault and variable-group lists (a vault left out is deleted), so the whole current template goes back with the changes; references the caller didn't change keep their ids (a Terraform-family template's own workspace inventory is hidden from the inventory list and would be lost if resolved by name); `variable_groups` is a list; only fields 2.18 and 2.19 share are managed; `type` is `task`/`build`/`deploy` and survey `type` `string`/`int`/`enum`/`text` (`text` needs 2.19); `task_params` merged per key, keys checked per app |
| `schedule` | cron schedules, commit pollers, run-at schedules | the project list leaves out pollers and each template's list has only its pollers, so both are read; `active: false` on a poller fails (Semaphore's scheduler ignores it); task-parameter overrides are read from the single schedule and sent back (an update without them unlinks them); an update resets the poller's last commit, so its next tick runs |
| `integration` | webhook integrations, matchers, extracted values | `auth_header` is only a header name; the secret is a `login_password` key (`auth_key`); matchers and extracted values are exact lists matched by name; the module ensures one webhook alias and returns the URLs; creating an alias or matcher answers 200, not 201 |
| `team_member` | project membership and role | the member is `user:` (the connection already uses `username`); the user must exist, looked up with `GET /users?s=` (a username prefix match, so the exact name is picked out); add answers 204 with no body, a duplicate 409, an unknown role a bare 400 (non-built-in roles are Pro custom-role slugs); refuses to remove or downgrade the last owner, and to change the login user's own membership (found with `GET /user`) |
| `info` | server version and registered apps | for the version check the role does today |
| `*_info` | read-only versions of the above | |

A module warns when the server reports a version outside the tested list.
It doesn't fail, because a collection can't know how strict a caller wants to
be. `semaphore_config` keeps its own `fail`/`warn` switch on top of `info`.

---

## Testing

- `ansible-test sanity` for each collection on each supported ansible-core
  version (2.16 through the current release) in GitHub Actions.
- Unit tests with mocked HTTP. Response fixtures are recorded from the
  throwaway local containers of the tested versions (Semaphore 2.18 and 2.19, Harbor 2.15), and each quirk in the
  tables above gets at least one test. These tests are what replace
  integration tests.
- No live servers in CI (decided). Before each release, point the ansible
  repo's roles at the new version and run them against the homelab: first in
  check mode, then for real.

---

## Versioning and release

- Semantic versioning, separate for each collection. Tags are `harbor-vX.Y.Z`
  and `semaphoreui-vX.Y.Z`.
- Changelogs come from `antsibull-changelog` fragments.
- A release is a GitHub release carrying the tarball built by
  `ansible-galaxy collection build`.
- Publishing to Galaxy can be added to the release workflow later. It needs a
  Galaxy API token; the `ramanavelineni` namespace is created when you first
  log in to Galaxy with GitHub.
- Installing from Git in the ansible repo:

  ```yaml
  collections:
    - name: https://github.com/ramanavelineni/ansible-collections.git#/ansible_collections/ramanavelineni/semaphoreui
      type: git
      version: semaphoreui-v0.1.0
  ```

---

## Phases

1. **Scaffolding.** README, LICENSE, Makefile, pre-commit, the CI workflow,
   and the semaphoreui collection's `galaxy.yml`, `meta/runtime.yml` and
   changelog setup, all passing sanity with no modules yet. This becomes the
   first commit. The harbor collection gets its skeleton when phase 5 starts.
2. **semaphoreui core.** The client in `module_utils` (auth, retries, error
   reports), then `info`, `project`, `key`, `repository`, `inventory` and
   `environment`, with their `_info` modules. Semaphore goes first because
   it has no usable declarative collection today.
3. **semaphoreui complete.** `view`, `template`, `schedule`, `integration`,
   `runner`, `user`, `team_member`. Release `semaphoreui-v0.1.0`.
4. **Switch `semaphore_config` to the collection.** Add the Git source to
   `collections/requirements.yml` in the ansible repo. The role keeps loading
   project files, validating, the version switch and the never-delete rule
   (it only passes `state: present`). Its `uri` tasks and name→id maps go away.
5. **harbor.** Same order: client, then `configuration`, `project`,
   `registry`, `robot`, then the policy modules. Release `harbor-v0.1.0`.
6. **Switch `harbor_config` to the collection.**
7. **Galaxy (optional).** Add the publish step to the release workflow.

After phase 4, the `THINGS_TO_CHECK.md` entry in the ansible repo for
`ebdruplab.semaphoreui` can be replaced with a note about this collection.

---

## Open questions

- Oldest Harbor version to support. The default is 2.15, and it only goes
  lower if someone asks.
- Whether `update_secret` should default to `on_create` for users of the
  collection, even though the roles keep passing `always`.
