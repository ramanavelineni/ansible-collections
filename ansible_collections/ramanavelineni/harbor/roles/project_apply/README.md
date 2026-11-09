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
- Values may use variables (`{{ ... }}`), so secrets can come from a vault.

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
```

## What the role does with it

1. It reads every project and checks all of them before it changes anything.
   It fails, and changes nothing, on any of these:
   - an option a module doesn't have, or a section of the wrong shape
   - a project described twice: a file and a directory, `.yml` and `.yaml`,
     or two files that declare the same `name`
   - an entry declared twice, in one file or in two files of a directory
   - a project named in `project_apply_protected_projects`
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
| `project_apply_no_log` | `true` | Hide the output of the tasks that carry secrets: robot accounts, webhooks and the loaded projects |

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
