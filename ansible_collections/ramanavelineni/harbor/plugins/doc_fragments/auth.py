# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)


class ModuleDocFragment(object):

    DOCUMENTATION = r'''
options:
  url:
    description:
      - Base URL of the Harbor server, for example C(https://harbor.example.com). It must start with
        C(http://) or C(https://).
      - A trailing C(/api/v2.0) is accepted and ignored, so an API URL works too.
      - A redirect is not followed, so that the credentials are not sent to wherever it points. The failure
        names the target; set O(url) to the address the Harbor server itself answers on.
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
  client_cert:
    description:
      - PEM file with the TLS client certificate to present, for a server that asks for one (mutual TLS).
      - The file may hold the private key as well. If it does not, set O(client_key).
      - The file is read on the host the module runs on. A path that is not a file there fails before a
        request is sent.
      - If not set, the value of the E(HARBOR_CLIENT_CERT) environment variable is used.
    type: path
  client_key:
    description:
      - PEM file with the private key that belongs to O(client_cert). Not needed when O(client_cert) holds
        the key too.
      - Requires O(client_cert). The key must not be protected by a passphrase.
      - If not set, the value of the E(HARBOR_CLIENT_KEY) environment variable is used.
    type: path
  use_proxy:
    description:
      - Whether to go through the proxy named by the E(http_proxy), E(https_proxy) and E(no_proxy)
        environment variables on the host the module runs on.
      - Set to V(false) to reach the server directly even when those variables are set.
      - If not set, the value of the E(HARBOR_USE_PROXY) environment variable is used.
    type: bool
    default: true
  timeout:
    description:
      - Seconds to wait for each HTTP response. Must be 1 or more.
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
      - V(0) turns retries off. A negative value is an error.
    type: int
    default: 3
  retry_delay:
    description:
      - Seconds to wait between retries. Must be 0 or more.
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
