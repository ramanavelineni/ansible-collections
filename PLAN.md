# Plan: ramanavelineni.harbor and ramanavelineni.semaphoreui

Two Ansible collections that manage Harbor and Semaphore UI declaratively, so
roles call one idempotent module per resource instead of writing their own
REST calls with `ansible.builtin.uri`.

They start from the two roles in the homelab ansible repo,
`roles/harbor_config` and `roles/semaphore_config`, which already cover
both APIs and work around their quirks. The collections move that knowledge
into Python modules and make it usable by anyone.

Status: phase 2 in progress. Done: scaffolding, client, `info`, `project`, `key_store`, `repository`, `inventory`, `variable_group` and their `_info` modules (phase 2 complete); phase 3 in progress: `view`, `template`, `schedule`, `integration`.

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
| Harbor | Harbor v2 API, tested against 2.15 (homelab runs 2.15.1) |
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
    └── harbor/                            # created when phase 5 starts
        └── (same shape; module_utils/harbor.py)
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

Scope matches `roles/harbor_config`. Harbor API v2, basic auth with an admin
user or robot account.

| Module | Manages | Notes from the role |
|---|---|---|
| `configuration` | `/configurations` system settings, including auth mode and OIDC | key-level diff; only the keys given are compared and sent |
| `schedule` | GC, scan-all and audit-log purge schedules | create or update on cron drift |
| `registry` | registry endpoints (proxy-cache upstreams, replication targets) | `type` and `url` can't be changed after creation: fail with instructions instead of trying |
| `project` | projects, metadata (public, auto_scan, severity, …), storage quota | the proxy-cache registry binding can't be changed after creation: fail with instructions |
| `robot` | system and project robot accounts, permissions, secret | secret set on create; re-applied according to `update_secret` |
| `retention_policy` | tag retention rules per project | rules matched by content, not by id |
| `immutability_rule` | tag immutability rules per project | matched by content |
| `webhook` | webhook policies per project | `auth_header` is a secret |
| `replication_policy` | replication policies | matched by name |
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
| `user` | global users | the login user can't modify itself; password is a secret |
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
