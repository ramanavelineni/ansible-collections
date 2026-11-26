# project_apply

Applies a directory of project descriptions to Harbor. The role reads and
checks every project in the directory, then creates, updates and trims each one
through the modules of this collection.

## What a project looks like

One file `<name>.yml` (or `.yaml`), or one directory `<name>/` of such files,
per project. The role puts the files of a directory together, so a large
project can keep its members apart from its robot accounts.

```yaml
# projects/apps.yml
name: apps
public: false
metadata:
  auto_scan: true
  severity: high
quota_gb: 50

robot_account:
  ci:
    duration: -1
    permissions:
      - access:
          - {resource: repository, action: push}
          - {resource: repository, action: pull}
    secret: "{{ vault_harbor_apps_ci_secret }}"
    update_secret: on_create
  retired:
    state: absent

project_member:
  - user: alice
    role: maintainer
  - group: harbor-readonly
    group_type: oidc
    role: guest
  - user: bob
    state: absent

tag_retention:
  schedule: "0 0 3 * * *"
  rules:
    - template: latestPushedK
      value: 10

tag_immutability:
  - tags: "v*"
  - repositories: "base/**"
    tags: latest

webhook:
  ci-notify:
    event_types:
      - PUSH_ARTIFACT
    address: https://ci.example.com/hooks/harbor
    auth_header: "Bearer {{ vault_ci_hook_token }}"
```

- Every key is an option of the `project` module, except the sections below.
  `name` is required. See `ansible-doc ramanavelineni.harbor.project`.
- Each section is named after a module and takes that module's options. See
  `ansible-doc ramanavelineni.harbor.<module>`.

| Section | Shape | The role fills in |
|---|---|---|
| `robot_account` | entries keyed by robot name | `project`, `name`, and `level: project` |
| `project_member` | a list, one item per user or group | `project` |
| `tag_retention` | one set of options: the project's single retention policy | `project` |
| `tag_immutability` | a list, one item per rule | `project` |
| `webhook` | entries keyed by webhook name | `project`, `name` |

- A member is known by its `user`, or by its `group` and `group_type`. An
  immutability rule has no name: the module finds it by `repositories`,
  `repositories_decoration`, `tags` and `tags_decoration`. Change one of those
  and it is another rule, so mark the old one `state: absent`.
- A key that starts with an underscore is ignored: a place for YAML anchors.
- Values may use variables (`{{ ... }}`), so secrets can come from a vault,
  such as the project's own [vault file](#vault-files).

A robot account without `secret` gets one from Harbor when it is created. The
role never shows it, so declare `secret` when something has to log in as the
robot. With `update_secret: on_create` the secret is set once; the default,
`always`, sets it on every run and reports a change each time.

### Proxy-cache projects

A proxy-cache project names its registry endpoint in `proxy_registry`. This
role does not create endpoints: create the endpoint first, with
`ramanavelineni.harbor.registry` (or the `server_apply` role), in an earlier
play or task. Harbor can't change a project's endpoint after it is created.

```yaml
# projects/dockerhub.yml
name: dockerhub
public: true
proxy_registry: docker-hub
retention_days: 14          # Harbor 2.16, used when the project is created
metadata:
  proxy_cache_filter_kind: doublestar     # Harbor 2.16
  proxy_cache_filter_pattern: "library/**"
  proxy_referrer_api: true
```

With Harbor 2.16 a proxy-cache project can proxy only some repositories
(`proxy_cache_filter_pattern`, read as a glob or, with
`proxy_cache_filter_kind: regex`, as a regular expression) and the OCI
referrers API (`proxy_referrer_api`). `retention_days` sets the retention
policy Harbor creates with a new proxy-cache project; it is not compared
afterwards, so change that policy in the project's `tag_retention` section.

### Vault files

A project directory can keep its secrets in a vault file, `vault.yaml` or
`vault.yml`. The role does not read that file as part of the project. It loads
the file as variables with `ansible.builtin.include_vars`, which decrypts a
file encrypted with `ansible-vault`, and the project's other files refer to
those variables:

```yaml
# projects/webshop/project.yaml
name: webshop
robot_account:
  release:
    duration: -1
    permissions:
      - access:
          - {resource: repository, action: push}
    secret: "{{ vault_webshop_robot_release_secret }}"
    update_secret: on_create
```

```yaml
# projects/webshop/vault.yaml, before `ansible-vault encrypt projects/webshop/vault.yaml`
vault_webshop_robot_release_secret: Change-me-1
```

Run the play with the vault password, for example with
`--ask-vault-pass` or `--vault-password-file`.

- The role loads the vault files of all projects before it reads the first
  project. The variables stay defined for the rest of the play.
- The variables are ordinary Ansible variables, loaded with `include_vars`
  and with its precedence. The role loads the vault files in sorted path
  order, so when two projects define the same variable, the later project's
  value wins for both. Give each project variable names of its own, for
  example starting with the project's name, as `project_export` does.
- A directory with both `vault.yaml` and `vault.yml` fails too.
- Only a project directory has a vault file. A `vault.yaml` directly in
  `project_apply_path` is a single-file project like any other file, and the
  role refuses it because it does not set `name`. Keep secrets for a
  single-file project in your own vars files.
- `project_apply_vault_files` sets the names. `[]` turns vault files off: the
  role then reads every `.yml` and `.yaml` file of a directory as the project.

## What the role does with it

1. It reads every project and checks all of them before it changes anything.
   Before that, it loads the vault files. It fails, and changes nothing, on
   any of these:
   - an option a module doesn't have, or a section of the wrong shape
   - a project described twice: a file and a directory, `.yml` and `.yaml`,
     or two files that declare the same `name`
   - an entry declared twice, in one file or in two files of a directory
   - a project named in `project_apply_protected_projects`
   - a project directory with more than one vault file
   - a project with `state: absent` but without `confirm_delete: true`, or
     with anything else described in it
2. It creates or updates everything declared, in this order: the project,
   robot accounts, members, tag retention, tag immutability, webhooks.
3. It deletes the entries marked `state: absent` in the reverse order.

What a project does not mention is left alone. Nothing is ever deleted because
it is missing from a file.

A project with `state: absent` and `confirm_delete: true` is deleted with
everything in it. Harbor deletes only a project without repositories, and
removes its robot accounts, members, retention policy and immutability rules
with it.

```yaml
# projects/old.yml
name: old
state: absent
confirm_delete: true
```

## Variables

| Variable | Default | |
|---|---|---|
| `project_apply_path` | required | The directory that holds the projects. Give an absolute path, such as `{{ playbook_dir }}/config/projects` |
| `project_apply_drift_check` | `false` | Fail at the end when something changed, or would have changed with `--check`. Robot secrets are then only sent for robot accounts that don't exist yet |
| `project_apply_protected_projects` | `[]` | Names of projects the role refuses to manage |
| `project_apply_vault_files` | `["vault.yaml", "vault.yml"]` | Names of the files in a project directory that are loaded as variables, not read as the project. `[]` turns this off. See [Vault files](#vault-files) |
| `project_apply_no_log` | `true` | Hide the output of the tasks that carry secrets: the vault files, robot accounts, webhooks and the loaded projects |

Afterwards `project_apply_changed` says whether anything changed, and
`project_apply_projects` lists the projects that were applied.

The connection options are not variables of the role. Set them once for the
play with `module_defaults`, or in the environment (`HARBOR_URL`,
`HARBOR_USERNAME` and `HARBOR_PASSWORD`).

## Example

```yaml
- name: Configure Harbor
  hosts: localhost
  gather_facts: false
  module_defaults:
    group/ramanavelineni.harbor.harbor:
      url: https://harbor.example.com
      username: admin
      password: "{{ vault_harbor_admin_password }}"
  roles:
    - role: ramanavelineni.harbor.project_apply
      vars:
        project_apply_path: "{{ playbook_dir }}/config/projects"
```

Run it with `--check --diff` first to see what would change. In check mode a
project that doesn't exist yet makes each of its entries report a change with
a warning, because the project they belong to was not created.

A drift check, for a schedule that should fail when someone changed Harbor by
hand:

```sh
ansible-playbook site.yml --check --diff -e project_apply_drift_check=true
```

`proxy_registry` and `quota_gb` need a Harbor administrator; see
`ansible-doc ramanavelineni.harbor.project`.
