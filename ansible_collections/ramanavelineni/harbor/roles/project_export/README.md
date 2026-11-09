# project_export

Reads one project from Harbor and writes it as YAML, in the layout the
`project_apply` role reads. Use it to put a project that was built by hand in
the UI under version control, or to copy a project to another Harbor.

The top of the file holds the project's own options (those of the `project`
module). Below that is one section per kind of object, named after the module
that manages it, with that module's options:

```yaml
name: apps
public: false
metadata:
  auto_scan: true
quota_gb: 50

robot_account:
  ci:
    duration: 90
    permissions:
      - access:
          - resource: repository
            action: push
    secret: "{{ vault_apps_robot_ci_secret }}"
    update_secret: on_create

project_member:
  - user: admin
    role: project_admin
  - group: harbor-readonly
    group_type: oidc
    role: guest

tag_retention:
  schedule: "0 0 3 * * *"
  rules:
    - template: latestPushedK
      value: 10

tag_immutability:
  - tags: "v*"

webhook:
  ci-notify:
    event_types:
      - PUSH_ARTIFACT
    address: "https://ci.example.com/hook"
    auth_header: "{{ vault_apps_webhook_ci_notify_auth_header }}"
```

Options at what a new object gets without them are left out, so the file shows
what was chosen. Ids and what Harbor fills in itself (a robot's full name and
expiry time, the project's retention id) are left out too.

## Example

```yaml
- name: Export a Harbor project
  hosts: localhost
  gather_facts: false
  module_defaults:
    group/ramanavelineni.harbor.harbor:
      url: https://harbor.example.com
      username: admin
      password: "{{ harbor_admin_password }}"
  roles:
    - role: ramanavelineni.harbor.project_export
      vars:
        project_export_project: apps
        project_export_dest: "{{ playbook_dir }}/config/projects"
```

This writes `config/projects/apps.yml` and `config/projects/apps.vault.example`.
The connection options are not role variables: set them with `module_defaults`
as above, or in the environment (`HARBOR_URL`, `HARBOR_USERNAME`,
`HARBOR_PASSWORD`).

The role runs on the host of the play and writes the files there, so it
normally runs on `localhost`.

## Variables

| Variable | Default | What it is |
|---|---|---|
| `project_export_project` | required | Name of the project |
| `project_export_dest` | required | Directory to write into. It is created if it is not there |
| `project_export_layout` | `file` | `file`: one file, `<dest>/<name>.yml`. `directory`: `<dest>/<name>/` with `project.yml` and one file per section that has objects |
| `project_export_file_name` | the project's name | Name of the file or directory, without `.yml` |
| `project_export_vault_prefix` | `vault` | What the names of the variables that stand for secrets start with |
| `project_export_vault_file` | `<dest>/<name>.vault.example` | File that lists those variables. Written only when it does not exist yet |
| `project_export_overwrite` | `false` | Whether a project file that exists and differs in content may be replaced. Never the vault file |
| `project_export_no_log` | `true` | Hide the result of reading the webhooks, which holds their addresses. Turn it off to see why that read failed |
| `project_export_file_mode` | `0644` | Mode of the files |
| `project_export_directory_mode` | `0755` | Mode of the directories the role creates |

`meta/argument_specs.yml` has the full description of each
(`ansible-doc -t role ramanavelineni.harbor.project_export`).

## Secrets

Three kinds of value become a reference to a variable instead of being written
into the file:

- a robot account's secret, which Harbor never returns
  (`vault_<project>_robot_<robot>_secret`);
- a webhook's auth header, which the `webhook_info` module does not return
  (`vault_<project>_webhook_<webhook>_auth_header`);
- a Slack webhook's URL, which is all it takes to post to the channel
  (`vault_<project>_webhook_<webhook>_address`).

The second file the role writes lists these variables, each empty, with a
comment that says what it is the secret of:

```yaml
# robot account ci: secret
vault_apps_robot_ci_secret: ""
```

Give each its value and keep the result in an Ansible Vault file that the play
applying the project loads. A robot secret needs at least 8 characters with
upper and lower case letters and a digit. Inside the directory
`project_apply` reads, the name of this file must not end in `.yml` or
`.yaml`, or it would be taken for a project. The default name does not.

The role writes this file only when it does not exist yet. It never replaces
it, also not with `project_export_overwrite`, because it may hold the values
you filled in. When the project gains a secret, the message at the end of the
run names every variable to define. To get a fresh list, remove the file or
point `project_export_vault_file` at a new one.

### Sending secrets again

Every robot account is written with `update_secret: on_create`. Harbor never
returns a secret, so it cannot be compared with the vault value. With
`on_create`, applying the export sends a secret only when the robot account is
new, and a second apply of an unchanged project reports no change. To push a
changed vault value to a robot account that exists, set
`update_secret: always` on that entry for one apply.

A webhook's auth header and address need nothing like this: the `webhook`
module compares them with what Harbor stores.

## What stops the export

The role stops before it writes anything when the project can't be written as
a file `project_apply` would apply:

- a group member whose type (`oidc`, `ldap`, `http`) the login user may not
  read. Only a system administrator may read Harbor's user groups;
- a proxy-cache project whose registry name the login user may not read;
- a webhook with more than one endpoint (the `webhook` module manages
  webhooks with one, as the Harbor UI makes them);
- a metadata key or a member role this collection does not know.

It also stops when a file it would write is there and differs, unless
`project_export_overwrite` is true.

## What is not exported

Registries, replication rules, system robot accounts, the system settings and
the schedules belong to the whole server, not to a project; `server_apply`
manages them. A proxy-cache project names its registry, so apply the server's
registries before the project.

A quota is written only when the login user may read it (a system
administrator).

## Files written

| Layout | Files |
|---|---|
| `file` | `<dest>/<name>.yml` and the vault file |
| `directory` | `<dest>/<name>/project.yml`, one `<section>.yml` per section with objects, and the vault file |

The same project always gives the same files, so a second run reports no
change. With the `directory` layout, the file of a section that has no objects
any more is removed (with `project_export_overwrite`).
