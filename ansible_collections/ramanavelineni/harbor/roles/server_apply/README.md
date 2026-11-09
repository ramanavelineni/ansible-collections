# server_apply

Applies the objects of a Harbor server that belong to no project: the system
settings, the garbage collection, Scan All and log rotation schedules, the
registry endpoints, the replication rules and the system robot accounts.

## Variables

| Variable | Default | |
|---|---|---|
| `server_apply_configuration` | `{}` | System settings. Takes the options of the `configuration` module |
| `server_apply_garbage_collection` | `{}` | Garbage collection schedule. Takes the options of the `garbage_collection` module |
| `server_apply_scan_all` | `{}` | Scan All schedule. Takes the options of the `scan_all` module |
| `server_apply_log_rotation` | `{}` | Audit log rotation schedule. Takes the options of the `log_rotation` module |
| `server_apply_registries` | `{}` | Registry endpoints, keyed by name. An entry takes the options of the `registry` module |
| `server_apply_replications` | `{}` | Replication rules, keyed by name. An entry takes the options of the `replication` module |
| `server_apply_robot_accounts` | `{}` | System robot accounts, keyed by name. An entry takes the options of the `robot_account` module, without `level` and `project` |
| `server_apply_drift_check` | `false` | Fail at the end when something changed, or would have changed with `--check`. Secrets are then only sent for objects that don't exist yet |
| `server_apply_no_log` | `true` | Hide the output of the tasks that carry secrets, and don't show the secrets Harbor generates for new robot accounts |

See `ansible-doc ramanavelineni.harbor.<module>` for the options of each
module. An entry keyed by name leaves out `name`: the key is the name.

An empty dictionary is not managed. With `server_apply_scan_all` empty the
role doesn't ask Harbor about Scan All at all, which matters because Harbor
refuses every Scan All request while it has no default vulnerability scanner.

## What the role does

1. An option a module doesn't have, and an entry that is not a dictionary,
   fail before anything is changed.
2. Everything declared is created or updated, in this order: the system
   settings, the schedules, the registries, the replications (they name
   registries) and the robot accounts.
3. Entries marked `state: absent` are deleted in the reverse order: robot
   accounts, replications, registries. So a replication goes before the
   registry it uses.

Only what the variables mention is changed. A registry, replication or robot
account that is not in them is left alone, and a setting or schedule option
that is not given keeps its value.

A new robot account without a declared `secret` gets one from Harbor. It is
shown once, in the output of the run, and only with
`server_apply_no_log: false`. With the default it stays out of the logs. Declare
a `secret` (from a vault) to know it in advance.

Afterwards `server_apply_changed` says whether anything changed.

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
    - role: ramanavelineni.harbor.server_apply
      vars:
        server_apply_configuration:
          settings:
            auth_mode: oidc_auth
            oidc_name: SSO
            oidc_endpoint: https://sso.example.com
            oidc_client_id: harbor
            robot_name_prefix: robot$
          oidc_client_secret: "{{ vault_harbor_oidc_secret }}"
          update_secret: on_create
        server_apply_garbage_collection:
          schedule: custom
          cron: "0 0 4 * * 0"
          delete_untagged: true
          workers: 2
        server_apply_log_rotation:
          schedule: daily
          audit_retention_hour: 720
          include_event_types:
            - create_artifact
            - delete_artifact
            - pull_artifact
        server_apply_registries:
          docker-hub:
            type: docker-hub
            endpoint_url: https://hub.docker.com
          old-mirror:
            state: absent
        server_apply_replications:
          to-dr:
            dest_registry: dr-harbor
            trigger:
              type: scheduled
              cron: "0 0 2 * * *"
            filters:
              - type: name
                value: "apps/**"
          old-rule:
            state: absent
        server_apply_robot_accounts:
          puller:
            description: Pulls from every project
            permissions:
              - namespace: "*"
                access:
                  - resource: repository
                    action: pull
            secret: "{{ vault_harbor_puller_secret }}"
            update_secret: on_create
```

`to-dr` names the registry `dr-harbor`, which must exist already or be
declared in `server_apply_registries` too.

Run it with `--check --diff` first to see what would change.

A drift check, for a schedule that should fail when someone changed Harbor by
hand:

```sh
ansible-playbook harbor.yml --check --diff -e server_apply_drift_check=true
```
