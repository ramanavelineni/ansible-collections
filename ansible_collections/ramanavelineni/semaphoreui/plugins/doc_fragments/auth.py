# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)


class ModuleDocFragment(object):

    DOCUMENTATION = r'''
options:
  url:
    description:
      - Base URL of the Semaphore UI server, for example C(https://semaphore.example.com).
      - A trailing C(/api) is accepted and ignored, so an API URL works too.
      - If not set, the value of the E(SEMAPHORE_URL) environment variable is used.
    type: str
    required: true
  api_token:
    description:
      - API token, sent as a Bearer token.
      - Mutually exclusive with O(username) and O(password).
      - If not set, the value of the E(SEMAPHORE_API_TOKEN) environment variable is used.
    type: str
  username:
    description:
      - Login name or email address to log in with.
      - The module logs in at the start of its run and logs out at the end, so no session outlives the task.
      - Requires O(password). Mutually exclusive with O(api_token).
      - If not set, the value of the E(SEMAPHORE_USERNAME) environment variable is used.
    type: str
  password:
    description:
      - Password for O(username).
      - If not set, the value of the E(SEMAPHORE_PASSWORD) environment variable is used.
    type: str
  validate_certs:
    description:
      - Whether to verify the server's TLS certificate.
      - If not set, the value of the E(SEMAPHORE_VALIDATE_CERTS) environment variable is used.
    type: bool
    default: true
  ca_path:
    description:
      - PEM file with the CA certificate(s) to verify the server against, instead of the system trust store.
      - If not set, the value of the E(SEMAPHORE_CA_PATH) environment variable is used.
    type: path
  timeout:
    description:
      - Seconds to wait for each HTTP response.
    type: int
    default: 30
  retries:
    description:
      - How many times to retry a request that failed without an HTTP response (connection reset, timeout)
        or with HTTP 502, 503 or 504.
      - Only reads and updates are retried. Creates are never retried, because the server may already
        have acted and a retry would create a duplicate.
    type: int
    default: 3
  retry_delay:
    description:
      - Seconds to wait between retries.
    type: int
    default: 2
notes:
  - Supports Semaphore UI 2.18 and 2.19. On another version the module warns and continues.
  - Either O(api_token) or O(username) and O(password) must be given.
'''
