# ramanavelineni.semaphoreui

**Configure [Semaphore UI](https://semaphoreui.com) as code.** Projects, keys,
repositories, inventories, variable groups, templates, schedules, webhooks,
users and runners, each described once and kept that way.

[![CI](https://github.com/ramanavelineni/ansible-collections/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/ramanavelineni/ansible-collections/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](https://github.com/ramanavelineni/ansible-collections/blob/main/LICENSE)
![ansible-core 2.18–2.21](https://img.shields.io/badge/ansible--core-2.18%20%E2%80%93%202.21-EE0000?logo=ansible)
![Semaphore UI 2.18 | 2.19](https://img.shields.io/badge/Semaphore%20UI-2.18%20%7C%202.19-7B42BC)

Every module finds its object **by name**, changes only what differs from the
options you set, and supports **check mode and `--diff`**. Objects refer to
each other by name too: a repository's `ssh_key: deploy`, a template's
`inventory: homelab`.

## Install

In `requirements.yml` (no Galaxy account needed):

```yaml
collections:
  - name: https://github.com/ramanavelineni/ansible-collections.git#/ansible_collections/ramanavelineni/semaphoreui
    type: git
    version: semaphoreui-v0.3.1
```

```sh
ansible-galaxy collection install -r requirements.yml
```

Needs ansible-core 2.18 or newer and Semaphore UI 2.18 or 2.19. Other versions
work but print a warning.

## Example

```yaml
- hosts: localhost
  gather_facts: false
  module_defaults:
    group/ramanavelineni.semaphoreui.semaphoreui:
      url: https://semaphore.example.com
      api_token: "{{ semaphore_api_token }}"
  tasks:
    - name: Project
      ramanavelineni.semaphoreui.project:
        name: homelab

    - name: Deploy key, set once and left alone afterwards
      ramanavelineni.semaphoreui.key_store:
        project: homelab
        name: deploy
        type: ssh
        ssh:
          login: git
          private_key: "{{ vault_deploy_key }}"
        update_secret: on_create

    - name: Repository
      ramanavelineni.semaphoreui.repository:
        project: homelab
        name: ansible
        git_url: git@github.com:example/ansible.git
        git_branch: main
        ssh_key: deploy

    - name: Inventory read from the repository
      ramanavelineni.semaphoreui.inventory:
        project: homelab
        name: homelab
        type: file
        inventory: inventories/homelab/hosts
        repository: ansible
        ssh_key: deploy

    - name: Variable group with a secret
      ramanavelineni.semaphoreui.variable_group:
        project: homelab
        name: default
        env:
          TZ: UTC
        secrets:
          - name: API_TOKEN
            type: env
            value: "{{ vault_api_token }}"

    - name: Template
      ramanavelineni.semaphoreui.template:
        project: homelab
        name: site
        playbook: site.yml
        repository: ansible
        inventory: homelab
        variable_groups: [default]

    - name: Run it whenever main moves (checked every 5 minutes)
      ramanavelineni.semaphoreui.schedule:
        project: homelab
        name: site-on-push
        template: site
        repository: ansible
        cron: "*/5 * * * *"
```

Run it with `--check --diff` first to see what would change.

## Modules

| Area | Module | Read-only |
|---|---|---|
| Server | | `info`: version, tested flag, registered apps |
| Projects | `project` | `project_info` |
| Key Store | `key_store`: `ssh`, `login_password`, `none` | `key_store_info` |
| Repositories | `repository` | `repository_info` |
| Inventories | `inventory`: `file`, `static`, `static-yaml` | `inventory_info` |
| Variable groups | `variable_group`: extra vars, env vars, secrets | `variable_group_info` |
| Views (template tabs) | `view` | `view_info` |
| Task templates | `template` | `template_info` |
| Schedules | `schedule`: cron, commit poller, run-at | `schedule_info` |
| Integrations (inbound webhooks) | `integration`: returns the webhook URL | `integration_info` |
| Team | `team_member` | `team_member_info` |
| Runners | `runner`: global, and project runners on Pro | `runner_info` |
| Users | `user` | `user_info` |

Full documentation for each: `ansible-doc ramanavelineni.semaphoreui.<module>`.

Every module that works inside a project names it with `project` (its name)
or `project_id` (its id), one of the two. The name is looked up in the list
of projects, which Semaphore cuts off at 200 rows, so the modules refuse to
look a project up by name on a server with 200 or more projects. With
`project_id` that list is not read and the project is found whatever their
number.

## Roles

| Role | |
|---|---|
| `project_apply` | Applies a directory of project descriptions: each project a YAML file, or a directory of them, with its keys, repositories, inventories, variable groups, views, templates, schedules, integrations and team |
| `server_apply` | Applies the users and the runners of the server |

Both check what they are given before they change anything, leave alone what
is not mentioned, delete only what is marked `state: absent`, and can run as a
drift check that fails when Semaphore differs. Each role's README has the
details: [project_apply](roles/project_apply/README.md),
[server_apply](roles/server_apply/README.md), or
`ansible-doc -t role ramanavelineni.semaphoreui.project_apply`.

```yaml
- name: Configure Semaphore
  hosts: localhost
  gather_facts: false
  module_defaults:
    group/ramanavelineni.semaphoreui.semaphoreui:
      url: https://semaphore.example.com
      api_token: "{{ vault_semaphore_api_token }}"
  roles:
    - role: ramanavelineni.semaphoreui.project_apply
      vars:
        project_apply_path: "{{ playbook_dir }}/config/projects"
```

## Connecting

Each module takes `url` (with or without `/api`) and either an `api_token` or
`username` + `password`. With a password, the module logs in and out within
the task. Set them once per play with the action group
`group/ramanavelineni.semaphoreui.semaphoreui`:

```yaml
- hosts: localhost
  gather_facts: false
  module_defaults:
    group/ramanavelineni.semaphoreui.semaphoreui:
      url: https://semaphore.example.com
      api_token: "{{ semaphore_api_token }}"
  tasks:
    - ramanavelineni.semaphoreui.project_info:
```

Or leave them out of the playbook and set environment variables where it
runs:

| Option | Environment variable |
|---|---|
| `url` | `SEMAPHORE_URL` |
| `api_token` | `SEMAPHORE_API_TOKEN` |
| `username` / `password` | `SEMAPHORE_USERNAME` / `SEMAPHORE_PASSWORD` |
| `validate_certs` / `ca_path` | `SEMAPHORE_VALIDATE_CERTS` / `SEMAPHORE_CA_PATH` |
| `client_cert` / `client_key` | `SEMAPHORE_CLIENT_CERT` / `SEMAPHORE_CLIENT_KEY` |
| `use_proxy` | `SEMAPHORE_USE_PROXY` |

Credentials a task sets win over the environment as a whole: a task with
`username` and `password` ignores `SEMAPHORE_API_TOKEN`, and a task with
`api_token` ignores `SEMAPHORE_USERNAME` and `SEMAPHORE_PASSWORD`. When
everything comes from the environment and both kinds are set, the token is
used.

`ca_path` points at a private CA's certificate, so you don't have to turn off
certificate checks.

For a server that asks for a TLS client certificate (mutual TLS), `client_cert`
is the PEM file with the certificate and `client_key` the one with its key;
`client_key` isn't needed when the certificate file holds the key too. Both are
read on the host the module runs on.

The modules use the proxy from `http_proxy`, `https_proxy` and `no_proxy` on
that host. `use_proxy: false` goes to the server directly.

The examples in the module documentation (`ansible-doc`) leave the connection
options out; they rely on one of the two ways above.

### Where the modules run

A module calls the Semaphore API from the host its task runs on. Nothing has
to be installed on the Semaphore server, so that host is usually the
controller: `hosts: localhost` as in the example, or `delegate_to: localhost`
in a play for other hosts. The environment variables above and the files
named by `ca_path`, `client_cert` and `client_key` are read on that host.

## Good to know

<details>
<summary><b>Secrets</b> (<code>key_store</code>, <code>variable_group</code>, <code>user</code>)</summary>

Semaphore never returns a stored secret, so a changed secret can't be
detected. `update_secret: always` (the default) sends the declared secret on
every run and reports a change; `on_create` sends it only when the object is
created. Leave the secret out to keep the stored one.

`key_store` never sends the secret of a key a repository uses unless
`force_repository_key_update: true` is set: Semaphore deletes every checkout of
those repositories whenever such a key is updated.

`variable_group` leaves secrets you don't list alone unless
`purge_secrets: true`, and recreates a secret whose type (`env` or `var`)
changed, since Semaphore can't change it in place.

</details>

<details>
<summary><b>Values that are not secret options but can hold a secret</b></summary>

Secret options (`ssh`, `login_password`, `user_password`, a variable group's
secret values) are never printed. Three other values are ordinary fields, so
they appear in a task's result and in `--diff` output:

- `repository.git_url`, when the URL has a user name and password or a token
  in it. Clone with a key from the Key Store (`ssh_key`) instead.
- `inventory.inventory` of a `static` or `static-yaml` inventory, when the
  content has a password such as `ansible_password`. Keep passwords in the Key
  Store (`ssh_key`, `become_key`).
- An integration's `webhook_urls`. With `auth_method: none`, knowing the URL is
  enough to start the task.

Where one of these can't be avoided, set `no_log: true` on the task.

</details>

<details>
<summary><b>Templates</b></summary>

- Fields the module doesn't manage (such as 2.19's `executor_image`) are sent
  back unchanged on every update.
- `task_params` is merged key by key, and a key the template's app doesn't
  know fails instead of being silently ignored.
- `app` also takes the id of an app an administrator registered on the
  server. The module checks it against the server's app list (in check mode
  it only warns), and sends that app's `task_params` without checking the
  keys.
- `start_version` belongs to a `build` template and `build_template` to a
  `deploy` template. Setting either on another type fails: Semaphore would
  not store it.
- An empty string removes a reference: `inventory: ""`, `view: ""`,
  `build_template: ""`.
- A Terraform/OpenTofu template created without an inventory gets a
  workspace inventory named `default` from Semaphore, and keeps it through
  later updates.
- `type` is `task`, `build` or `deploy`; survey variable types are `string`,
  `int`, `enum` and `text` (`text` needs 2.19).

</details>

<details>
<summary><b>Schedules, integrations, team, users, runners</b></summary>

- `schedule` also finds commit pollers, which Semaphore's own project list
  leaves out, and refuses `active: false` on a poller, because Semaphore keeps
  running pollers whatever `active` says. Use `state: absent` to stop one.
- `integration` makes sure the integration has a webhook URL and returns it.
  Matchers and extracted values are complete lists.
- `team_member` never removes or downgrades a project's last owner, and never
  changes the membership of the user it logs in as. The member is `user:`,
  because `username` is the login option.
- `user` names the managed user `login:` / `user_password:` for the same
  reason, and never changes the user it logs in as.
- `runner` returns a new runner's registration token. Register the task with
  `no_log: true`, since a module can't mask values it returns.

</details>

<details>
<summary><b>Deleting</b></summary>

`state: absent` fails with a list of what still uses the object: which
templates use an inventory, which repositories use a key. Deleting a project
also needs `confirm_delete: true`, because it deletes everything inside.

</details>

## Exporting a project

The role `project_export` reads a project from the server and writes it as the
YAML the `project_apply` role reads: the project's options, and one section per
kind of object, keyed by object name, with the options of the module that
manages it.

```yaml
- name: Export a Semaphore project
  hosts: localhost
  gather_facts: false
  roles:
    - role: ramanavelineni.semaphoreui.project_export
      vars:
        project_export_project: homelab
        project_export_dest: "{{ playbook_dir }}/config/projects"
```

Semaphore never returns a stored secret, so each one becomes a reference to a
variable (`"{{ vault_homelab_key_deploy_ssh_private_key }}"`), and the role
lists those variables in a second file for you to fill in and keep in an Ansible
Vault. The same project always gives the same files, and a file that differs is
not replaced unless `project_export_overwrite` is set. See the
[role's README](roles/project_export/README.md) for the variables and for what
is left out. The filters behind it (`project_export_config`,
`project_export_yaml`, `project_export_vault` and
`project_export_vault_variables`) can be used on their own.

## More

- [Repository and other collections](https://github.com/ramanavelineni/ansible-collections)
- [Design notes and every Semaphore API quirk found](https://github.com/ramanavelineni/ansible-collections/blob/main/PLAN.md)
- [Changelog](https://github.com/ramanavelineni/ansible-collections/blob/main/ansible_collections/ramanavelineni/semaphoreui/CHANGELOG.md)

Apache-2.0 licensed.
