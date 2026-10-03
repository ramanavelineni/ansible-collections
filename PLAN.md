# Plan and design notes

Two Ansible collections, `ramanavelineni.semaphoreui` and
`ramanavelineni.harbor`, that manage Semaphore UI and Harbor declaratively, so
roles call one idempotent module per resource instead of writing REST calls
with `ansible.builtin.uri`.

They grew out of two roles in the homelab ansible repo, `semaphore_config` and
`harbor_config`, which already covered both APIs and worked around their
quirks. The collections move that knowledge into Python modules that anyone
can use. This file records the decisions behind them and every API quirk found
along the way. Each quirk is handled inside a module and covered by a test.

## Status and roadmap

- [x] Scaffolding: repository, CI, Makefile, pre-commit, changelog setup
- [x] `ramanavelineni.semaphoreui`: 25 modules
- [x] `ramanavelineni.harbor`: 23 modules
- [x] First releases: `semaphoreui-v0.1.0` and `harbor-v0.1.0`, built and
      published as GitHub Releases by a workflow on tag push
- [ ] Switch the homelab `semaphore_config` role to the collection. The role
      keeps loading project files, validating, its version switch and its
      never-delete rule (it only passes `state: present`); its `uri` tasks and
      name→id maps go away.
- [ ] Switch the homelab `harbor_config` role to the collection

---

## Decisions

| Topic | Decision |
|---|---|
| Namespace | `ramanavelineni`: `ramanavelineni.semaphoreui` and `ramanavelineni.harbor` |
| Repository | this monorepo, public at <https://github.com/ramanavelineni/ansible-collections> |
| License | Apache-2.0 |
| Supported versions | ansible-core 2.18–2.21 (the versions still getting releases); Semaphore UI 2.18 and 2.19; Harbor 2.14 and 2.15. Other server versions warn but work |
| Module names | the servers' UI labels, singular (`key_store`, `variable_group`, `team_member`, `robot_account`, `tag_retention`, …), each with an `_info` module |
| Option names | follow the old roles' YAML, with name-based references, so the roles can pass their data straight through. Fields the roles didn't use keep the API's names. Where a name clashes with a connection option, the module uses another: `user`, `login`/`user_password`, `endpoint_url` |
| State | every resource module takes `state: present \| absent` |
| Project references | objects inside a project take `project: <name>` |
| Deleting | fails with the list of what still uses the object. Deleting a project needs `confirm_delete: true` |
| Secrets | `update_secret: always` (default) or `on_create`, since neither server returns stored secrets |
| Module imports | modules import only `module_utils`: Ansible ships nothing else with a module, and sanity's import test enforces it |
| License hygiene | no GPL-licensed ansible-core code is imported, extended or copied; only its BSD-licensed `module_utils` and the Python standard library |
| CI | `ansible-test` sanity and unit tests on every supported ansible-core version, for the collections a change touches. No live servers in CI |
| Fixtures | API responses recorded from throwaway local servers of every supported version, one file per area |
| Distribution | Git tags via `requirements.yml`, with GitHub Releases for the tarballs. Not published to Ansible Galaxy |
| Workflow | feature branch and pull request for every change; squash-merge; no Co-Authored-By trailer; the owner pushes. `main` takes changes only through a pull request whose "CI result" check passed |

Apache-2.0 fits with ansible-core: the modules only import
`ansible.module_utils.basic`, `ansible.module_utils.urls` and similar, which
are BSD-2-Clause licensed. The one restriction is that Apache-licensed
collections can't be added to the Ansible community package, which isn't a
goal.

---

## Repository layout

`ansible-test` only runs when a collection sits at
`ansible_collections/<namespace>/<name>/`:

```
ansible-collections/
├── README.md, PLAN.md, LICENSE, CONTRIBUTING.md, SECURITY.md
├── Makefile                    # make sanity / units / changelog-lint / build
├── .pre-commit-config.yaml     # whitespace, YAML, changelog lint
├── .github/workflows/ci.yml    # sanity + units per collection and ansible-core
├── tools/
│   ├── record_semaphoreui_fixtures.py   # record API responses per area
│   ├── record_harbor_fixtures.py
│   ├── recorder_common.py               # throwaway-server guard, listing filter, secret scan
│   └── tests/                           # make tools-test
└── ansible_collections/ramanavelineni/
    ├── semaphoreui/
    │   ├── galaxy.yml, README.md, meta/runtime.yml, changelogs/
    │   ├── plugins/doc_fragments/      # auth.py, attributes.py
    │   ├── plugins/module_utils/       # semaphore.py (client), template.py
    │   ├── plugins/modules/
    │   └── tests/unit/plugins/fixtures/<version>/<area>.json
    └── harbor/
        └── same shape; module_utils: harbor.py (client), schedule.py, replication.py
```

The two collections don't depend on each other. The small HTTP client is
duplicated rather than shared: collections can't import each other's
`module_utils` without declaring a dependency, and the two APIs authenticate
differently anyway.

---

## Conventions for every module

1. **Declarative and idempotent.** Read the current object, compare it with the
   desired one, write only when they differ. `changed` means a real
   difference. Check mode and `--diff` everywhere.
2. **Look up by name.** A module fails when it finds two objects with the
   same name, rather than guess (Semaphore doesn't enforce unique names).
3. **References by name.** A template's `repository: ansible`, not
   `repository_id: 3`; the module resolves the id.
4. **Only what you set.** Options left out are not managed and keep their
   current value.
5. **Whole-object updates.** Where an update replaces the whole object, the
   module starts from the current one and applies the changes, so nothing
   unmentioned is wiped.
6. **Connection options** from one doc fragment per collection, with
   `SEMAPHORE_*` / `HARBOR_*` environment fallbacks and an action group for
   `module_defaults`. `ca_path` works for private CAs.
7. **Retries** for reads and updates on transport errors and 502/503/504.
   Never for creates, where a retry after a lost answer would make a
   duplicate. (A 401 from Harbor's login lock is the one exception; see
   Harbor `info`.)
8. **Useful failures.** Method, URL, status, response and request body, with
   secrets masked.
9. **Pagination** follows every page; a capped list fails instead of silently
   missing rows.
10. **Versions.** A server version outside the tested list gives a warning, not
    a failure.

---

## ramanavelineni.semaphoreui

Authentication is by API token or username and password. With a password,
each module logs in and out within its own run.

### project
- The API caps the project list at 200 rows. The module fails at the cap
  rather than risk creating a duplicate.
- The modules that work inside a project take `project_id` as an alternative
  to the project's name. It reads that one project (`GET /project/<id>`)
  instead of the list, so they work past the cap. `project` itself still
  finds a project by name only.
- `state: absent` needs `confirm_delete: true`, because it deletes everything
  inside.

### key_store
- The update needs `id` and `project_id` in the body and
  `override_secret: true`, or Semaphore silently ignores the secret.
- The secret is required on create. Leaving it out for an existing key keeps
  the stored one.
- Type changes happen in place; a change to `ssh` or `login_password` needs
  the secret.
- **Every update of a key a repository uses makes Semaphore delete that
  repository's checkouts.** Such a key's secret is skipped with a warning, and
  a type change fails, unless `force_repository_key_update: true`.

### repository
- `git_branch` is required unless `git_url` is a local path.
- Changing `git_url` deletes the repository's checkouts.

### inventory
- The update replaces the whole row.
- Semaphore accepts a `file` inventory with a path outside its working
  directory (any absolute path) on create, but rejects every update of it.
  The module fails with an explanation.
- `""` clears a repository or key reference.

### variable_group
- Secrets are a list of `{name, type, value}`. A dict keyed by name would mask
  the words `env` and `var` in all output once its values are `no_log`.
- Undeclared secrets are left alone unless `purge_secrets: true`.
- A secret's type can't change in place, so a type change is a delete plus a
  create in one update.

### view
- The update must send the current `type` back, or the built-in `All` view
  becomes an ordinary one.
- The module doesn't delete the `All` view.
- `filter` isn't written by Semaphore's update, so it's left alone.

### template
- The list leaves out `vaults`, so each template is read on its own.
- The update rewrites every column and the vault and variable-group lists (a
  vault left out is deleted), so the whole current template goes back with
  the changes.
- References the caller didn't change keep their ids. A Terraform-family
  template's own workspace inventory is hidden from the inventory list and
  would be lost if resolved by name.
- Only fields 2.18 and 2.19 share are managed; the rest go back unchanged.
- `type` is `task`/`build`/`deploy` and survey types `string`/`int`/`enum`/`text`
  (the API spells the first of each `""`); `text` needs 2.19.
- `task_params` is merged key by key, and keys are checked against the
  template's app.

### schedule
- The project list leaves out commit pollers, and each template's list has
  only its pollers, so both are read.
- Semaphore's scheduler runs a poller whatever `active` says, so
  `active: false` on a poller fails.
- Task-parameter overrides are only in the single read, and an update without
  them unlinks them, so they're read and sent back.
- An update resets a poller's last commit, so its next tick runs.

### integration
- `auth_header` is only a header name; the secret is a `login_password` key
  (`auth_key`).
- Matchers and extracted values are exact lists matched by name.
- The module makes sure one webhook alias exists and returns the URLs.
- Creating an alias or a matcher answers 200, not 201.

### team_member
- The member is `user:`, because `username` is the connection's login.
- The user must exist; `GET /users?s=` matches username *prefixes*, so the
  exact name is picked out.
- Adding answers 204 with no body; a duplicate 409; an unknown role a bare
  400 (other role names are Pro custom-role slugs).
- Refuses to remove or downgrade the last owner, and to change the login
  user's own membership. Semaphore only protects a non-admin owner changing
  themselves.

### user
- The managed user is `login:` / `user_password:`, because `username` and
  `password` are the connection's.
- The update rewrites name, username, email, alert, admin and pro together,
  so the current values go back.
- The password has its own endpoint (an admin needs no current password) and
  follows `update_secret`.
- `external` is fixed at creation, and external users take no password.
- Duplicate emails get a bare 400, so they fail early.
- The login user is never changed or deleted.
- Semaphore 2.18 can't delete a user who has ever logged in (no
  `ON DELETE CASCADE` on sessions until 2.19; a bare 500). The failure
  explains it.

### runner
- A new runner has no credentials. The module asks for a one-time
  registration token (valid one hour) right after creating it and returns it.
  `regenerate_token` gets a new one, which resets an already registered
  runner.
- The token request is the one POST that is retried: each answer is a new
  token and only the last is handed out. If it still fails for a new runner,
  the runner is deleted again, because a runner left without its token looks
  finished to the next run.
- The update replaces every field, tags included, so the whole runner is
  sent.
- The global list includes project runners, so global lookups filter on
  `project_id`.
- Project runners are Pro-only (Community answers 403 on create), so their
  success paths are unit-tested only.

### info
- Server version and registered apps; the old role builds its own `fail` or
  `warn` version switch on top.

---

## ramanavelineni.harbor

Harbor's API only takes HTTP basic authentication: admin, user, robot account,
or an OIDC user's CLI secret.

### info (and every module's login check)
- With wrong credentials Harbor answers many requests anonymously instead of
  refusing them: `/systeminfo` answers 200, and `/projects` lists public
  projects only. Only an authenticated `/systeminfo` carries
  `harbor_version`, so every module checks that first.
- Harbor locks a username for 1.5 s after any failed login. A request for that
  user during the lock is handled the same way (anonymous reads, 401 on
  anything that needs a login). The failed request itself waits out the lock,
  so only *other* clients using the same account at that moment are hit. The
  client asks `/systeminfo` once more, and retries a 401 once, after 2 s.
- A lock that starts mid-run makes `/projects` answer 200 without the private
  projects, and nothing in that answer says so. So a project that is not in
  the answer is only taken as missing after `/systeminfo` was asked again
  (`read_as_user`): still the login user less than 1.5 s after the last such
  answer means no lock fits in between; anonymous means wait, check and read
  again; anonymous twice fails the task. `project_info` checks after every
  full list. A project that is found costs nothing extra. Automation is still
  better off with its own account.

### project
- Create answers 201 with an empty body; the id is only in `Location`.
- `/projects/<n>` reads a numeric name as an id, so projects are addressed by
  id.
- The update merges metadata keys. A top-level `public` is ignored (it belongs
  in metadata). Unknown keys are silently dropped, and an invalid severity is
  stored as `unknown`, so keys and values are checked first. 2.15 adds
  `proxy_cache_local_on_not_found`.
- The proxy-cache registry can't change after creation; the module fails with
  instructions.
- Quota through `/quotas?reference=project&reference_id=` and
  `PUT /quotas/{id}`.
- Delete needs `confirm_delete`, and fails up front while repositories remain.

### robot_account
- Names are matched without Harbor's robot name prefix. System robots are
  found with `q=name`; project robots are stored as `<project>+<name>`.
- Create ignores a `secret` in the body and always generates one, so a
  declared secret is set with `PATCH /robots/{id}` right after. It's checked
  first (8–128 characters with upper case, lower case and a digit).
- Without a declared secret, the generated one is returned on create only.
  Module results can't be masked, so the task needs `no_log`.
- The update needs the full prefixed name and the level (otherwise 400). It
  overwrites description and disable and replaces permissions (which must not
  be empty), so every field goes back.
- Permissions are compared as sets; read-back order is random.
  `namespace: "*"` means every project, including future ones.

### registry
- Create and update check that the endpoint is reachable: 400 "the registry is
  unhealthy", or a bare 500 for some adapters.
- The update merges the given fields. `type` has no update field, so a
  different type fails with instructions. The URL can change; Harbor strips a
  trailing slash.
- The option is `endpoint_url`, because `url` is the connection.
- The secret comes back as `*****`, so it follows `update_secret`.
- `ca_certificate` exists only in 2.15; 2.14 silently ignores it, so the
  module fails there.
- Delete answers 412 while a replication rule or proxy-cache project uses the
  endpoint.

### replication
- One side is a remote endpoint and the other the local Harbor, returned as
  registry id 0, "Local".
- The update replaces the whole rule (an omitted
  `dest_namespace_replace_count` becomes -1), so every field goes back.
- Cron has 6 fields; seconds must be 0, and minutes can't be `*`.
- `single_active_replication` with an `event_based` trigger is a bare 500, so
  it fails first.
- Filters are compared regardless of order, label values included.
  `decoration` only applies to tag and label filters.

### webhook
- Harbor returns the auth header in plain text, so it's compared like any
  option (no `update_secret`) but never put in results.
- The update replaces the whole policy: an omitted `enabled` becomes false,
  description and header are emptied, and `creation_time` resets. So the
  current policy goes back with the changes.
- One target per webhook, as the UI makes. The API allows several, and the
  module refuses to edit targets then.
- Reads leave out `skip_cert_verify: false` and the default payload format,
  so targets are compared with those filled in. Slack targets take no payload
  format. Duplicate names get 409.

### tag_retention
- At most one policy per project, linked by the project metadata
  `retention_id`. `rules` is the exact list.
- Harbor checks only the cron (6 fields), duplicate rules (409) and the
  15-rule limit. It stores an unknown template or a missing count as given, so
  the module validates rules first.
- An empty cron means no schedule. The module never starts a run.

### tag_immutability
- A new rule is always stored enabled; a disabled one takes a create plus a
  toggle.
- An update either toggles `disabled` (then Harbor ignores the rest of the
  body) or rewrites the selectors, never both. So the module only toggles, and
  other patterns count as another rule. Duplicates get 409; there's no rule
  limit.

### configuration
- Only the keys given are compared and sent. Harbor silently ignores unknown
  keys (and the read-only `scan_all_policy`) and answers a wrong type with
  422, so keys and types are checked first. The 57 writable keys are identical
  in 2.14 and 2.15.
- `oidc_client_secret` and `ldap_search_password` are write-only. They're
  separate `no_log` options following `update_secret`; `on_create` sends them
  only while `oidc_client_id` / `ldap_search_dn` is empty or changing.
  `uaa_client_secret` is returned in clear text: compared, never output.
- `auth_mode` can only change while no user but the admin exists.

### garbage_collection, scan_all, log_rotation
- Schedules only. Type `Manual` is never sent, so no run is ever started.
- A schedule GET with no schedule answers 200 with an empty body; GC's POST
  and PUT behave the same.
- 2.14 includes Harbor's internal Redis URL (which can carry a password) in
  GC job parameters. 2.15 removed it, and the modules strip it everywhere.
  `delete_tag` is refused on 2.14, which ignores it.
- Without a default vulnerability scanner, every Scan All call answers 412.
  POST refuses while a schedule exists, so the module uses PUT.
- Every log-rotation write needs `audit_retention_hour` and
  `include_event_types`, removing the schedule included. The old role's
  example omitted `include_event_types` and would have been rejected.

---

## Testing

- `ansible-test sanity` and unit tests for both collections on ansible-core
  2.18, 2.19, 2.20 and 2.21, in GitHub Actions on every pull request. Changes
  that only touch Markdown skip CI.
- Unit tests replay API responses recorded from throwaway local servers:
  Semaphore UI 2.18.30 and 2.19.12, Harbor 2.14.4 and 2.15.2. Each quirk above
  has at least one test. The recorders live in `tools/`, one area at a time.
  They refuse a server that isn't on a loopback address unless
  `--allow-remote` is passed, keep only their own objects from listings, and
  don't write a recording in which they find a secret.
- Before merging, every module is exercised live against those servers.
- No live servers in CI. Before a release is used, the homelab roles run
  against it: first in check mode, then for real.

## Versioning and release

- Semantic versioning, separate for each collection. Tags are
  `semaphoreui-vX.Y.Z` and `harbor-vX.Y.Z`.
- Changelogs come from `antsibull-changelog` fragments, and new modules are
  listed from their `version_added`.
- Pushing a tag runs that collection's changelog lint, sanity and unit tests
  at the tagged commit (the release workflow calls the CI workflow for it).
  When they pass, it builds the collection with
  `ansible-galaxy collection build` and publishes a GitHub Release with the
  tarball and the changelog.
- Installing a release from Git:

  ```yaml
  collections:
    - name: https://github.com/ramanavelineni/ansible-collections.git#/ansible_collections/ramanavelineni/semaphoreui
      type: git
      version: semaphoreui-v0.2.1
  ```
