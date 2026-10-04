# server_apply

Applies the users and the runners of a Semaphore UI server: the objects that
belong to the server, not to a project. For projects see the `project_apply`
role.

## Variables

| Variable | Default | |
|---|---|---|
| `server_apply_users` | `{}` | Users, keyed by login name. An entry takes the options of the `user` module |
| `server_apply_runners` | `{}` | Runners, keyed by name. An entry takes the options of the `runner` module |
| `server_apply_drift_check` | `false` | Fail at the end when something changed, or would have changed with `--check`. Passwords are then only sent for users that don't exist yet |
| `server_apply_no_log` | `true` | Hide the output of the task that carries the users' passwords |

Every entry is created or updated; an entry marked `state: absent` is deleted.
Users and runners that are not mentioned are left alone. An option a module
doesn't have fails before anything is changed.

A new runner's registration token is shown once, in the output of the run.

Afterwards `server_apply_changed` says whether anything changed.

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
    - role: ramanavelineni.semaphoreui.server_apply
      vars:
        server_apply_users:
          alice:
            name: Alice Example
            email: alice@example.com
            admin: true
            user_password: "{{ vault_alice_password }}"
            update_secret: on_create
          mallory:
            state: absent
        server_apply_runners:
          builder-1:
            max_parallel_tasks: 2
            tags:
              - build
    - role: ramanavelineni.semaphoreui.project_apply
      vars:
        project_apply_path: "{{ playbook_dir }}/config/projects"
```

The user the playbook logs in as is best left out of `server_apply_users`.
