# project_apply

Applies a directory of project descriptions to Semaphore UI: every project
found in it is checked and then created, updated and trimmed through the
modules of this collection.

## What a project looks like

One file `<name>.yml` (or `.yaml`), or one directory `<name>/` of such files,
per project. The files of a directory are put together, so a large project can
keep its templates apart from its keys.

```yaml
# projects/site.yml
name: site
max_parallel_tasks: 2

key_store:
  deploy:
    type: ssh
    ssh:
      login: git
      private_key: "{{ vault_site_deploy_key }}"
    update_secret: on_create

repository:
  playbooks:
    git_url: git@git.example.com:infra/playbooks.git
    git_branch: main
    ssh_key: deploy

inventory:
  production:
    type: file
    inventory: inventories/production/hosts
    repository: playbooks
    ssh_key: deploy

variable_group:
  common:
    json:
      region: eu

template:
  deploy:
    playbook: deploy.yml
    repository: playbooks
    inventory: production
    variable_groups:
      - common
  retired:
    state: absent

schedule:
  nightly:
    template: deploy
    cron: "0 3 * * *"
```

- `key_store`, `repository`, `inventory`, `variable_group`, `view`,
  `template`, `schedule`, `integration` and `team_member` each hold entries
  keyed by name (`team_member` by login name). An entry takes the options of
  the module of that name; see `ansible-doc ramanavelineni.semaphoreui.<module>`.
- Every other key is an option of the `project` module. `name` is required.
- A key that starts with an underscore is ignored: a place for YAML anchors.
- Values may use variables (`{{ ... }}`), so secrets can come from a vault.

## What the role does with it

1. An option a module doesn't have, a project described twice (a file and a
   directory, or `.yml` and `.yaml`) and an entry declared in two files of a
   directory all fail before anything is changed.
2. Everything declared is created or updated, in dependency order: the
   project, keys, repositories, inventories, variable groups, views,
   templates, schedules, integrations, team.
3. Entries marked `state: absent` are deleted in the reverse order.

What a project does not mention is left alone. Nothing is ever deleted because
it is missing from a file.

A project with `state: absent` and `confirm_delete: true` is deleted with
everything in it; describe nothing else in that project then.

A new integration's webhook URL is shown in the output of the run.

## Variables

| Variable | Default | |
|---|---|---|
| `project_apply_path` | required | The directory that holds the projects. Give an absolute path, such as `{{ playbook_dir }}/config/projects` |
| `project_apply_drift_check` | `false` | Fail at the end when something changed, or would have changed with `--check`. Secrets are then only sent for objects that don't exist yet |
| `project_apply_protected_projects` | `[]` | Names of projects the role refuses to manage |
| `project_apply_no_log` | `true` | Hide the output of the tasks that carry secrets |

Afterwards `project_apply_changed` says whether anything changed, and
`project_apply_projects` lists the projects that were applied.

The connection options are not variables of the role. Set them once for the
play with `module_defaults`, or in the environment (`SEMAPHORE_URL` and
`SEMAPHORE_API_TOKEN`, or `SEMAPHORE_USERNAME` and `SEMAPHORE_PASSWORD`).

## Example

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

Run it with `--check --diff` first to see what would change.

A drift check, for a schedule that should fail when someone changed Semaphore
by hand:

```sh
ansible-playbook site.yml --check --diff -e project_apply_drift_check=true
```

## When the playbook runs inside Semaphore

Updating a key that a repository uses makes Semaphore delete that repository's
checkouts, including the one a running task works from. Run the playbook from a
project of its own that it never manages, and name that project in
`project_apply_protected_projects`.
