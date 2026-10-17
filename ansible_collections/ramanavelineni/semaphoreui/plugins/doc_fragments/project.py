# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)


class ModuleDocFragment(object):

    # The options project and project_id, which name the project a task works
    # in. Their argument spec is project_argument_spec() in
    # module_utils/semaphore.py.
    #
    # A module still lists project_id with only its version_added, because
    # that release is not the same in every module. Ansible adds the module's
    # keys to the fragment's when it merges them.

    # For a module that cannot work without a project.
    DOCUMENTATION = r'''
options:
  project:
    description:
      - Name of the project.
      - Mutually exclusive with O(project_id). One of the two is required.
    type: str
  project_id:
    description:
      - Id of the project, as an alternative to O(project).
      - With it the list of projects is not read, so a project is found on a server with 200 or more
        projects too. Semaphore cuts that list off at 200, and O(project) fails there.
      - Mutually exclusive with O(project). One of the two is required.
    type: int
'''

    # For a module that also works without a project. Its description says
    # what it does then.
    OPTIONAL = r'''
options:
  project:
    description:
      - Name of the project.
      - Mutually exclusive with O(project_id). Both are optional. What the module does without a project is
        in its description.
    type: str
  project_id:
    description:
      - Id of the project, as an alternative to O(project).
      - With it the list of projects is not read, so a project is found on a server with 200 or more
        projects too. Semaphore cuts that list off at 200, and O(project) fails there.
      - Mutually exclusive with O(project). Both are optional.
    type: int
'''
