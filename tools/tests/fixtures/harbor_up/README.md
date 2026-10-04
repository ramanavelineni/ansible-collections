# Fixtures for `tools/tests/test_harbor_up.py`

- `compose-v<version>.prepare.yml`: the `docker-compose.yml` that Harbor's
  `prepare` writes for that version, for plain HTTP on port 8080 and the data
  directory `/var/home/core/harbor-lab/v<version>/data`. Rendered with the
  prepare code of the tagged Harbor release (`make/photon/prepare`, Apache-2.0,
  <https://github.com/goharbor/harbor>).
- `compose-v<version>.working.yml`: the compose file of the throwaway Harbor of
  that version that the committed unit-test fixtures were recorded from
  (ports 8014 and 8015). It holds no secret: those are in the `env` files that
  `prepare` writes, which are not here.
- `harbor.yml.tmpl`: the lines of Harbor's `harbor.yml.tmpl` that
  `tools/harbor_up.sh` edits, with a few around them. Its passwords are the
  defaults that Harbor publishes.
