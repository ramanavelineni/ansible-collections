# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)


class ModuleDocFragment(object):

    # Descriptions of the attributes every module declares. Each module sets
    # its own `support` values; this fragment only supplies the wording.
    DOCUMENTATION = r'''
attributes:
  check_mode:
    description: Can run in check mode and report what would change without changing anything.
  diff_mode:
    description: Returns the object before and after the change when run with C(--diff).
  platform:
    description: Where the module can run. It talks to the Harbor API over HTTP, so any host with Python works.
    support: full
    platforms: all
  action_group:
    description: Belongs to the C(ramanavelineni.harbor.harbor) action group, so C(module_defaults) can set the connection options once.
    support: full
    membership:
      - ramanavelineni.harbor.harbor
'''
