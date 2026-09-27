# Plan: ramanavelineni.harbor and ramanavelineni.semaphoreui

Two Ansible collections that manage Harbor and Semaphore UI declaratively, so
roles call one idempotent module per resource instead of writing their own
REST calls with `ansible.builtin.uri`.

They start from the two roles in the homelab ansible repo,
`roles/harbor_config` and `roles/semaphore_config`, which already cover
both APIs and work around their quirks. The collections move that knowledge
into Python modules and make it usable by anyone.

Status: phase 1 (scaffolding) in progress. No modules yet; nothing committed.

---

## Decisions

| Topic | Decision |
|---|---|
| Namespace | `ramanavelineni`: collections `ramanavelineni.harbor` and `ramanavelineni.semaphoreui` |
| Repository | this monorepo, public at <https://github.com/ramanavelineni/ansible-collections> |
| Deletion | each resource module takes `state: present \| absent` |
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
| `runner` | global and project runners | the registration token is returned only once, so it goes into the module result |
| `project` | projects | the API caps lists at 200 rows; fail rather than miss projects |
| `key` | key store entries (`ssh`, `login_password`, `none`) | PUT needs `id` and `project_id` in the body and `override_secret: true`, or the secret is silently ignored. **Updating a key that a repository uses makes Semaphore delete every checkout of that repository.** Such keys default to `update_secret: on_create`, and re-applying their secret needs an explicit `force_repository_key_update: true` |
| `repository` | Git repositories | |
| `inventory` | `file`, `static`, `static-yaml` inventories | PUT replaces the whole row |
| `environment` | variable groups and their secrets | secrets are created or updated, deleted only with `state: absent` on the environment |
| `view` | UI tabs and their position | |
| `template` | task templates, including build/deploy, vaults and surveys | the list omits `vaults`, so each template is read on its own; PUT replaces the whole row, and a missing `vaults` deletes them; POST inserts the row before checking the app, so the module checks `/apps` first; `build_template` resolved by name |
| `schedule` | cron schedules and commit pollers | pollers don't appear in the project schedule list and are read per template |
| `integration` | webhook integrations, matchers, extracted values | `auth_header` is a secret |
| `project_member` | project membership and role | |
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
   `runner`, `user`, `project_member`. Release `semaphoreui-v0.1.0`.
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
