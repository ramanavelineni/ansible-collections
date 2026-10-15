# CLAUDE.md

Two Ansible collections, `ramanavelineni.semaphoreui` and `ramanavelineni.harbor`, under `ansible_collections/ramanavelineni/`. [README.md](README.md) describes them, [CONTRIBUTING.md](CONTRIBUTING.md) lists every test target and what CI runs, and [PLAN.md](PLAN.md) holds the module conventions and known API quirks. Read "Conventions for every module" in PLAN.md before changing a module.

## Before a branch is ready to push

CI's "CI result" check is the gate, and a failing run costs the user another push. Before reporting a branch as ready, the checks for each collection it touches must have passed:

```sh
make lint docs-lint changelog-lint COLLECTION=<semaphoreui|harbor>
make sanity units COLLECTION=<semaphoreui|harbor>
```

`sanity` and `units` need a container and `lint` needs ansible-lint; neither runs in Claude Code's sandbox. Give the user these commands, wait for their output, and fix what it reports before handing over the push command.

What a change needs (tests, a changelog fragment for anything a user can notice) is in "What a change needs" in CONTRIBUTING.md.

## Rules

- The repository is Apache-2.0. Use only BSD-licensed `module_utils` and the standard library; never import, extend or copy GPL-licensed ansible-core code, doc fragments or test helpers.
- Branch every PR from `main`. When several branches are built in parallel, update `PLAN.md` and the root README's status lines once, on the last branch, so the merges do not conflict on them.
- `AUDIT_DETAILS_2026-09-27.md` at the repository root stays untracked; never commit it.
