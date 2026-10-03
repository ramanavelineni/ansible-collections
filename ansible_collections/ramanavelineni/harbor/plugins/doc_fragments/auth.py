# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)


class ModuleDocFragment(object):

    DOCUMENTATION = r'''
options:
  url:
    description:
      - Base URL of the Harbor server, for example C(https://harbor.example.com).
      - A trailing C(/api/v2.0) is accepted and ignored, so an API URL works too.
      - If not set, the value of the E(HARBOR_URL) environment variable is used.
    type: str
    required: true
  username:
    description:
      - User to authenticate as, with HTTP basic authentication, which is all Harbor's API accepts.
      - An administrator, an ordinary user, a robot account (its full name, for example
        C(robot$ci)) or an OIDC user with their CLI secret as O(password).
      - If not set, the value of the E(HARBOR_USERNAME) environment variable is used.
    type: str
    required: true
  password:
    description:
      - Password (or robot secret, or OIDC CLI secret) for O(username).
      - If not set, the value of the E(HARBOR_PASSWORD) environment variable is used.
    type: str
    required: true
  validate_certs:
    description:
      - Whether to verify the server's TLS certificate.
      - If not set, the value of the E(HARBOR_VALIDATE_CERTS) environment variable is used.
    type: bool
    default: true
  ca_path:
    description:
      - PEM file with the CA certificate(s) to verify the server against, instead of the system trust store.
      - If not set, the value of the E(HARBOR_CA_PATH) environment variable is used.
    type: path
  timeout:
    description:
      - Seconds to wait for each HTTP response.
    type: int
    default: 30
  retries:
    description:
      - How many times to retry a request that failed without an HTTP response (connection refused or reset,
        timeout) or with HTTP 502, 503 or 504.
      - A failure that asking again cannot cure is not retried, so that a wrong setting fails at once. That is
        a certificate that does not verify, a O(ca_path) file that does not exist and a host name that does
        not resolve.
      - Reads and updates are retried. Creates and deletes are never retried, because the server may already
        have acted.
      - Separately, any request answered with HTTP 401 is sent once more after 2 seconds, because Harbor
        answers 401 while a user is locked after a failed login.
    type: int
    default: 3
  retry_delay:
    description:
      - Seconds to wait between retries.
    type: int
    default: 2
  warn_untested_version:
    description:
      - Whether to warn when the server reports a Harbor version this collection is not tested with.
      - Set it to V(false) once you know the modules you use work with your version, to stop every task
        from printing the warning.
      - If not set, the value of the E(HARBOR_WARN_UNTESTED_VERSION) environment variable is used.
    type: bool
    default: true
notes:
  - Supports Harbor 2.14 and 2.15. On another version the module warns and continues, unless
    O(warn_untested_version=false).
  - An option that needs a newer Harbor than the server reports fails the task. When the reported version
    cannot be read, the option is sent and Harbor decides.
'''
