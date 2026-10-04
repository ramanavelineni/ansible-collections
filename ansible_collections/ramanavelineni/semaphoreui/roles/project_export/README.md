# project_export

Reads one project from a Semaphore server and writes it as YAML, in the layout
the `project_apply` role reads. Use it to put a project that was built by hand
in the UI under version control, or to copy a project to another server.

The top of the file holds the project's own options. Below that is one section
per kind of object (`key_store`, `repository`, `inventory`, `variable_group`,
`view`, `template`, `schedule`, `integration`, `team_member`), keyed by object
name, with the options of the module of that name:

```yaml
name: homelab
max_parallel_tasks: 2

key_store:
  deploy:
    type: ssh
    ssh:
      login: "{{ vault_homelab_key_deploy_ssh_login }}"
      passphrase: "{{ vault_homelab_key_deploy_ssh_passphrase }}"
      private_key: "{{ vault_homelab_key_deploy_ssh_private_key }}"

repository:
  ansible:
    git_url: "git@github.com:example/ansible.git"
    git_branch: main
    ssh_key: deploy
```

## Example

```yaml
- name: Export a Semaphore project
  hosts: localhost
  gather_facts: false
  module_defaults:
    group/ramanavelineni.semaphoreui.semaphoreui:
      url: https://semaphore.example.com
      api_token: "{{ semaphore_api_token }}"
  roles:
    - role: ramanavelineni.semaphoreui.project_export
      vars:
        project_export_project: homelab
        project_export_dest: "{{ playbook_dir }}/config/projects"
```

This writes `config/projects/homelab.yml` and
`config/projects/homelab.vault.example`. The connection options are not role
variables: set them with `module_defaults` as above, or in the environment
(`SEMAPHORE_URL`, `SEMAPHORE_API_TOKEN`).

The role runs on the host of the play and writes the files there, so it
normally runs on `localhost`.

## Variables

| Variable | Default | What it is |
|---|---|---|
| `project_export_project` | | Name of the project. One of this and `project_export_project_id` is required |
| `project_export_project_id` | | Id of the project, for a server with 200 or more projects, where a project cannot be found by name |
| `project_export_dest` | required | Directory to write into. It is created if it is not there |
| `project_export_layout` | `file` | `file`: one file, `<dest>/<name>.yml`. `directory`: `<dest>/<name>/` with `project.yml` and one file per section that has objects |
| `project_export_file_name` | the project's name | Name of the file or directory, without `.yml` |
| `project_export_vault_prefix` | `vault` | What the names of the variables that stand for secrets start with |
| `project_export_vault_file` | `<dest>/<name>.vault.example` | File that lists those variables |
| `project_export_overwrite` | `false` | Whether a file that exists and differs may be replaced |
| `project_export_file_mode` | `0644` | Mode of the files |
| `project_export_directory_mode` | `0755` | Mode of the directories the role creates |

`meta/argument_specs.yml` has the full description of each
(`ansible-doc -t role ramanavelineni.semaphoreui.project_export`).

## Secrets

Semaphore never returns a stored secret, so the role cannot write one. Each
secret becomes a reference to a variable, named after the project, the section,
the object and the field:

- a key of type `ssh`: its login, passphrase and private key
  (`vault_<project>_key_<key>_ssh_private_key`);
- a key of type `login_password`: its login and password;
- each secret of a variable group (`vault_<project>_var_<group>_<secret>`).

A key's login is asked for too. The modules do not treat it as a secret, but
Semaphore stores it with the secret and does not return it either.

The second file the role writes lists these variables, each empty, with a
comment that says what it is the secret of:

```yaml
# key deploy: ssh.private_key
vault_homelab_key_deploy_ssh_private_key: ""
```

Give each its value and keep the result in an Ansible Vault file that the play
applying the project loads. A value may stay empty where the object has none,
such as a key without a passphrase. The exported project can be applied as soon
as the variables are defined. Inside the directory `project_apply` reads, the
name of this file must not end in `.yml` or `.yaml`, or it would be taken for a
project; the default name does not.

Some fields are not secrets to Semaphore but can carry one: a repository's
`git_url` with credentials in it, the content of a static inventory with
`ansible_password`, the webhook URLs of an integration. The URL and the
inventory are written as the server returns them; look at the files before
committing them. Webhook URLs are not written.

## What is left out

- **Ids and what only the server knows:** a view's type, a schedule's kind, an
  integration's webhook URLs, the repositories that use a key.
- **Options at the value a new object has.** A template is written with its
  `app`, `playbook`, `repository`, `inventory` and `variable_groups`, and with
  the checkboxes and lists that were changed, not with all of them. Applying
  the file to the project it came from changes nothing either way.
- **What is not part of a project:** global users and runners. They belong to
  the `server_apply` role.
- **What the modules have no option for,** such as the `target` of a survey
  variable on Semaphore 2.19. The modules keep such a field when they update a
  template, but it is not in the file, so a project built from the file on
  another server does not have it.
- **Run options:** `state`, `update_secret`, `purge_secrets`,
  `force_repository_key_update` and `confirm_delete` say what a run should do,
  not what an object is. Add them to the file by hand where you want them.

A value Semaphore stores that looks like a template, such as `{{ name }}` in a
variable group's JSON, is written with the `!unsafe` tag, so that loading the
file does not try to render it.

## Running it again

The same project always gives the same files, with the objects in the order of
their names, so a second run reports no change and a `git diff` shows only what
changed on the server. Templates are the one exception to the order: a build
template comes before the deploy templates that name it, because `project_apply`
creates them in the order of the file.

A file that exists and differs from the project on the server is not replaced:
the role stops before it writes anything and names the file. That protects
edits made by hand, such as shared settings moved into a YAML anchor. Set
`project_export_overwrite: true` to replace what differs. With the `directory`
layout this also removes the file of a section that has no objects any more.
