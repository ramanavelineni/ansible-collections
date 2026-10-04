# Contributing

Bug reports, fixes and new modules are welcome. For anything larger than a
fix, open an issue first, so the options and behaviour can be agreed before
the code is written. Security problems go through [SECURITY.md](SECURITY.md),
not through an issue. Everyone taking part is expected to follow the
[code of conduct](CODE_OF_CONDUCT.md).

[PLAN.md](PLAN.md) holds the design decisions, the conventions every module
follows, and each API quirk found so far. Read "Conventions for every module"
before changing a module.

## Running the tests

`ansible-test` only works from inside a collection directory; the Makefile
goes there for you. `COLLECTION` is `semaphoreui` (the default) or `harbor`.

```sh
make sanity COLLECTION=harbor    # ansible-test sanity
make units COLLECTION=harbor     # unit tests
make coverage COLLECTION=harbor  # unit tests with coverage, against the floor
make lint COLLECTION=harbor      # ansible-lint and the sanity ignore files
make docs-lint COLLECTION=harbor # antsibull-docs lint of the module docs
make install-test COLLECTION=harbor  # build the tarball, install it elsewhere, use it
make changelog-lint              # check changelog fragments
make tools-test                  # tests for the fixture recorders
make build                       # collection tarball into build/
```

`sanity`, `units` and `coverage` run in a container (docker, or podman when
docker isn't installed). `ANSIBLE_TEST_FLAGS="--venv --python 3.13"` runs them
in a virtual environment instead. `lint`, `docs-lint` and `install-test` need
`ansible-lint`, `antsibull-docs` and `ansible-core` installed.

CI runs sanity and the unit tests on ansible-core 2.18, 2.19, 2.20 and 2.21,
and lints the changelog fragments, for the collections a change touches. It
also runs, for those collections:

- **Install test:** the tarball is built, installed into an empty directory
  and used from there: `ansible-doc` for every module, and the `info` module
  against a port where nothing listens, which has to fail with the
  collection's own connection error. On the oldest and the newest supported
  ansible-core.
- **Lint:** `ansible-lint` with the production profile, and a check that each
  `tests/sanity/ignore-<version>.txt` has one explained entry per module and
  nothing else.
- **Coverage:** the unit tests have to cover at least 95% of the plugin code
  (98% when the floor was set). The floor is in
  `.github/scripts/coverage-floor.sh`.
- **Docs lint:** `antsibull-docs lint-collection-docs`. It doesn't block a
  merge yet.

All of these except the docs lint are part of "CI result", the one check a
pull request needs.

A
change to the CI workflow or the `Makefile` runs both collections, a change
under `tools/` runs the recorder tests, and a change that only touches Markdown
runs none of them. Once a week everything runs for both collections, so a new
ansible-core patch release that breaks something is noticed.

The jobs named "Units (..., devel)" run the unit tests on ansible-core's
development branch. They are an early warning and never block a merge: a
failure there on a pull request is worth a look, but usually means ansible-core
changed, not that the pull request is wrong.

### Live suites

Each collection has a live suite in `tests/live`: the modules run in-process
against a real server, so it shows what the unit tests can't, that the server
accepts what a module sends and that a second run changes nothing.

```sh
SEMAPHORE_URL=http://127.0.0.1:3019 SEMAPHORE_USERNAME=admin SEMAPHORE_PASSWORD=... \
    make live COLLECTION=semaphoreui
HARBOR_URL=http://127.0.0.1:8015 HARBOR_USERNAME=admin HARBOR_PASSWORD=... \
    make live COLLECTION=harbor
```

The live suites are local only and never run in CI. Use throwaway servers:
the tests create and delete objects. Without the URL in the environment the
tests are skipped. Run them before a release, and when a change touches what a
module sends.

## What a change needs

- **Tests.** Unit tests replay recorded API responses (see Fixtures below).
  A new behaviour gets a test; a bug fix gets a test that fails without it.
- **A changelog fragment** for every change a user can notice: a YAML file
  under `ansible_collections/ramanavelineni/<collection>/changelogs/fragments/`
  with one of the sections of `changelogs/config.yaml` (`bugfixes`,
  `minor_changes`, `breaking_changes`, `security_fixes`, ...). New modules
  need none; they are listed from their `version_added`. Don't edit
  `CHANGELOG.md` or `changelogs/changelog.yaml`; they are generated at
  release time.
- **Documentation.** Module docs live in the module's `DOCUMENTATION`,
  `EXAMPLES` and `RETURN`. A new module is also added to its collection's
  README and to `meta/runtime.yml`'s action group.
- **One ignore line per module.** `validate-modules` expects a GPL header,
  which these Apache-2.0 modules don't have. A new module needs this line in
  every `tests/sanity/ignore-2.*.txt` of its collection, and nothing else
  goes into those files:

  ```
  plugins/modules/<name>.py validate-modules:missing-gplv3-license # Apache-2.0 collection, see LICENSE
  ```

## No GPL code

The collections are Apache-2.0. Most of ansible-core is GPL-3.0, so:

- import only ansible-core's BSD-licensed `module_utils` and the Python
  standard library;
- don't extend ansible-core's doc fragments and don't use its test helpers;
- don't copy code from ansible-core or from GPL-licensed collections, other
  Semaphore and Harbor collections included.

By opening a pull request you agree that your contribution is licensed under
Apache-2.0, like the rest of the repository.

## Fixtures

The unit tests replay responses recorded from real servers, one file per
area and server version, under `tests/unit/plugins/fixtures/`. When a module
needs a response that isn't there, record it; don't write it by hand.

### Starting a throwaway server

One server per tested version, on a local port.

Semaphore runs from its image; the command is also in the recorder's
docstring:

```sh
podman run -d --name semfx -p 127.0.0.1:3019:3000 \
    -e SEMAPHORE_DB_DIALECT=sqlite -e SEMAPHORE_ADMIN=admin \
    -e SEMAPHORE_ADMIN_PASSWORD=<password> -e SEMAPHORE_ADMIN_NAME=Admin \
    -e SEMAPHORE_ADMIN_EMAIL=admin@localhost \
    docker.io/semaphoreui/semaphore:v2.19.12
```

Harbor is several containers. `tools/harbor_up.sh` starts them the way the
servers behind the committed fixtures were set up: Harbor's `harbor.yml.tmpl`
edited for plain HTTP, Harbor's own `prepare` container, and the compose file
it writes adjusted for rootless podman (the script says what is adjusted and
why).

```sh
tools/harbor_up.sh up v2.15.2 8015      # then: user admin, password in ~/harbor-lab/v2.15.2/admin_password
tools/harbor_up.sh down v2.15.2         # stops it and removes ~/harbor-lab/v2.15.2
```

Run it where the containers run. With a podman machine (macOS) that is inside
the machine; the published port is reachable on the host, so the recorder
still runs on the host:

```sh
podman machine ssh 'bash -s -- up v2.15.2 8015' < tools/harbor_up.sh
HARBOR_PASSWORD="$(podman machine ssh cat harbor-lab/v2.15.2/admin_password)" \
    tools/record_harbor_fixtures.py http://127.0.0.1:8015
podman machine ssh 'bash -s -- down v2.15.2' < tools/harbor_up.sh
```

It needs podman or docker and a compose command (`podman compose` with a
provider installed, `docker compose`, `podman-compose` or `docker-compose`).
With podman and none of those, as in a podman machine, it runs compose from
the docker CLI image against podman's API socket.

The compose project is named after the version, so one Harbor per version:
`up` refuses when containers of that project exist already.

**What it was checked with.** The two edits the script makes itself are tested
by `make tools-test`: its `harbor.yml`, and its compose file, which for 2.14.4
and 2.15.2 equals the compose file of the servers the fixtures were recorded
from. `up` and `down` were run in a podman machine on macOS with Harbor
v2.15.1, and the harbor live suite passed against that server, including the
registry endpoint at `http://proxy:8080`. Not run so far: docker as the
engine, a compose command installed on the machine, and Linux without a
podman machine.

### Recording

```sh
SEMAPHORE_PASSWORD=<password> tools/record_semaphoreui_fixtures.py http://127.0.0.1:3019 [AREA ...]
HARBOR_PASSWORD=<password> tools/record_harbor_fixtures.py http://127.0.0.1:8015 [AREA ...]
```

Without `AREA` every area is recorded. Each script's docstring says what an
area must do. An area that fails takes its objects off the server again, and
the next run first removes what a run that died left behind, so a recording
can simply be started again. A recording replaces the area's file: ids and
timestamps in it change, so run the unit tests afterwards and read the diff.

The rules:

- **Throwaway servers only.** The recorders create, change and delete
  objects, and what the server answers is committed to a public repository.
  They refuse a server that isn't on a loopback address unless
  `--allow-remote` is passed; pass it only for another throwaway.
- **Own objects only.** An area creates what it needs under its own names,
  deletes it again, and filters every listing down to those objects with
  `keep()`.
- **A sweep per area.** Each area has a function in `SWEEPS` that deletes the
  area's objects, found by those names and by nothing else. It runs before
  and after the area. A new area gets one, and `make tools-test` checks that
  none is missing.
- **No secrets.** A value the server generates (a robot secret, a runner
  token) is replaced by a placeholder before it is stored. The recorder
  refuses to write a file in which it finds the admin password, a generated
  secret or something shaped like a credential. Read the diff of a new
  recording anyway before committing it.
- Record every supported server version, not only the newest.

### Adding a server version

1. Start a throwaway server of the new version (above) and run the recorder
   against it. The files land in `tests/unit/plugins/fixtures/<major.minor>/`
   of the collection, and the unit tests run once per directory found there.
2. Add the version to `TESTED_VERSIONS` in the collection's
   `plugins/module_utils/semaphore.py` or `harbor.py`. Until then the modules
   warn that the version is untested.
3. Run the unit tests. Where they fail, the new version answers differently:
   handle it in the module, cover it with a test, and note the difference
   under the collection's API quirks in [PLAN.md](PLAN.md). Some tests name a
   version to branch on; search the tests for the older version numbers.
4. Update the versions in the docs: the badges and the "Tested with" and
   "Supported" tables in the root `README.md`, the badge and the "Needs"
   line in the collection's `README.md`, and "Supported versions" in
   `PLAN.md`.
5. Add a changelog fragment (`minor_changes`) that names the new version.

Dropping a version is the same list backwards, with the fixture directory
removed. The `tests/sanity/ignore-*.txt` files don't come into it: they
belong to ansible-core versions, not to server versions.

## Commits and pull requests

- One topic per pull request, against `main`. `main` only takes changes
  through a pull request, and the "CI result" check has to pass before it
  can be merged.
- Titles follow [Conventional Commits](https://www.conventionalcommits.org/):
  `fix(harbor): ...`, `feat(semaphoreui): ...`, `docs: ...`, `chore: ...`.
  Pull requests are squashed, so the title becomes the commit.
- `pre-commit install` sets up the light local checks from
  `.pre-commit-config.yaml`.

## A new ansible-core version

When ansible-core gets a new minor version (a `stable-2.x` branch), nothing in
the repo changes by itself. The steps, in one pull request:

1. Copy the newest `tests/sanity/ignore-2.x.txt` to the new version's name in
   both collections. Sanity fails without it, because the entries (the
   Apache-2.0 licence header instead of the GPL one) are needed on every
   version.
2. Add `stable-2.x` to the two `ansible:` lists in `.github/workflows/ci.yml`
   (sanity and units), make it the newer of the two versions of the install
   test, and move the coverage and docs lint jobs' `ansible-core~=` to it. The
   Lint job fails until the ignore files from step 1 and the sanity list
   agree.
3. Raise the upper bound in the `pip install "ansible-core>=...,<..."` line of
   `.github/workflows/release.yml`.
4. Update the version badge at the top of the three READMEs, the "Compatibility"
   table in the root README, and the version lists in this file and in
   `PLAN.md`.
5. Check that the pinned `ansible-community/ansible-test-gh-action` knows the
   new branch; an older pin tests it with the wrong Python. Dependabot proposes
   newer pins.

Dropping a version that no longer gets releases is the reverse, plus
`requires_ansible` in both `meta/runtime.yml` files.

A red "Units (..., devel)" job, or a red weekly run, is often the first sign
that a new version needs attention: the unit-test harness sets the module
arguments through private ansible-core names (see
`tests/unit/plugins/conftest.py`), which a new version may change.

## Releases

Maintainers only. Each collection is versioned on its own
([semantic versioning](https://semver.org/)). A release pull request sets the
version in `galaxy.yml` and runs `make changelog COLLECTION=<collection>`.
Once it is merged, pushing the tag `<collection>-v<version>` on `main` starts
the release workflow. It checks the tag against `galaxy.yml` and
`CHANGELOG.md`, runs that collection's CI jobs (changelog lint, sanity, unit
tests, install test, lint and coverage) at the tagged commit, and only when
they pass builds the tarball and publishes the
GitHub Release. When a test fails, nothing is published: fix it on `main`, move
the tag to the fixed commit and push the tag again.
