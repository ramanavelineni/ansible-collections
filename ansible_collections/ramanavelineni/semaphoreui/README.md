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
    version: semaphoreui-v0.2.1
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

## Connecting

Each module takes `url` (with or without `/api`) and either an `api_token` or
`username` + `password`. With a password, the module logs in and out within
the task. Set them once per play with the action group
`group/ramanavelineni.semaphoreui.semaphoreui`, as in the example, or through
environment variables:

| Option | Environment variable |
|---|---|
| `url` | `SEMAPHORE_URL` |
| `api_token` | `SEMAPHORE_API_TOKEN` |
| `username` / `password` | `SEMAPHORE_USERNAME` / `SEMAPHORE_PASSWORD` |
| `validate_certs` / `ca_path` | `SEMAPHORE_VALIDATE_CERTS` / `SEMAPHORE_CA_PATH` |

Credentials a task sets win over the environment as a whole: a task with
`username` and `password` ignores `SEMAPHORE_API_TOKEN`, and a task with
`api_token` ignores `SEMAPHORE_USERNAME` and `SEMAPHORE_PASSWORD`. When
everything comes from the environment and both kinds are set, the token is
used.

`ca_path` points at a private CA's certificate, so you don't have to turn off
certificate checks.

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

## More

- [Repository and other collections](https://github.com/ramanavelineni/ansible-collections)
- [Design notes and every Semaphore API quirk found](https://github.com/ramanavelineni/ansible-collections/blob/main/PLAN.md)
- [Changelog](https://github.com/ramanavelineni/ansible-collections/blob/main/ansible_collections/ramanavelineni/semaphoreui/CHANGELOG.md)

Apache-2.0 licensed.
