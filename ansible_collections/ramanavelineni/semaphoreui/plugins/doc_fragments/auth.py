# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)


class ModuleDocFragment(object):

    DOCUMENTATION = r'''
options:
  url:
    description:
      - Base URL of the Semaphore UI server, for example C(https://semaphore.example.com).
      - A trailing C(/api) is accepted and ignored, so an API URL works too.
      - Must start with C(http://) or C(https://). Anything else fails before a request is sent.
      - Redirects are not followed, because the credentials would go wherever the redirect points. A server
        that answers with one (C(http://) redirected to C(https://), for example) makes the task fail with
        the redirect's target in the message. Set O(url) to that address.
      - If not set, the value of the E(SEMAPHORE_URL) environment variable is used.
    type: str
    required: true
  api_token:
    description:
      - API token, sent as a Bearer token.
      - Mutually exclusive with O(username) and O(password).
      - If the task sets none of O(api_token), O(username) and O(password), the value of the
        E(SEMAPHORE_API_TOKEN) environment variable is used. A task that sets O(username) or O(password)
        ignores that variable.
    type: str
  username:
    description:
      - Login name or email address to log in with.
      - The module logs in at the start of its run and logs out at the end, so no session outlives the task.
      - Requires O(password). Mutually exclusive with O(api_token).
      - If not set, the value of the E(SEMAPHORE_USERNAME) environment variable is used. A task that sets
        O(api_token) ignores that variable. When the task sets no credential at all and both
        E(SEMAPHORE_API_TOKEN) and E(SEMAPHORE_USERNAME) are set, the token is used.
    type: str
  password:
    description:
      - Password for O(username).
      - If not set, the value of the E(SEMAPHORE_PASSWORD) environment variable is used, under the same
        conditions as for O(username).
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
  client_cert:
    description:
      - PEM file with the TLS client certificate to present, for a server that asks for one (mutual TLS).
      - The file may hold the private key as well. If it does not, set O(client_key).
      - The file is read on the host the module runs on. A path that is not a file there fails before a
        request is sent.
      - If not set, the value of the E(SEMAPHORE_CLIENT_CERT) environment variable is used.
    type: path
    version_added: 0.3.0
  client_key:
    description:
      - PEM file with the private key that belongs to O(client_cert). Not needed when O(client_cert) holds
        the key too.
      - Requires O(client_cert). The key must not be protected by a passphrase.
      - If not set, the value of the E(SEMAPHORE_CLIENT_KEY) environment variable is used.
    type: path
    version_added: 0.3.0
  use_proxy:
    description:
      - Whether to go through the proxy named by the E(http_proxy), E(https_proxy) and E(no_proxy)
        environment variables on the host the module runs on.
      - Set to V(false) to reach the server directly even when those variables are set.
      - If not set, the value of the E(SEMAPHORE_USE_PROXY) environment variable is used.
    type: bool
    version_added: 0.3.0
    default: true
  timeout:
    description:
      - Seconds to wait for each HTTP response. Must be 1 or more.
    type: int
    default: 30
  retries:
    description:
      - How many times to retry a request that failed without an HTTP response (connection reset, timeout)
        or with HTTP 502, 503 or 504.
      - Reads, updates and the login are retried. Creates, deletes and other requests that act at once
        (setting a password, asking for a runner token) are never retried, because the server may already
        have acted.
      - V(0) turns retries off. A negative value is an error.
    type: int
    default: 3
  retry_delay:
    description:
      - Seconds to wait between retries. Must be 0 or more.
    type: int
    default: 2
notes:
  - Supports Semaphore UI 2.18 and 2.19. On another version the module warns and continues.
  - Either O(api_token) or O(username) and O(password) must be given.
  - The module calls the Semaphore API from the host the task runs on. That is usually the controller, so run
    the play against C(localhost) or delegate the task to it. O(ca_path), O(client_cert) and O(client_key) name
    files on that host.
'''
