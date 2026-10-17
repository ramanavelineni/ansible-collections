# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""HTTP transport shared by the clients of every collection in this repository.

This file is the same, byte for byte, in every collection of the repository
(tools/tests/test_shared_helpers.py checks that), so a fix made here reaches
every client at once. It names no product. What differs per server, such as
the login, the API path and the product name in messages, is given by the
client module that imports it: as an argument, or by a subclass of ApiError
and ApiClient.
"""

import json
import os
import re
import socket
import ssl
import time
import traceback

from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

from ansible.module_utils.common.text.converters import to_text

# Statuses worth retrying: a proxy or the server itself was briefly unable
# to answer. Anything else is the server's real answer.
RETRY_STATUSES = (502, 503, 504)

MASK = '********'

# How much of a response body a failure message quotes. A proxy's error page
# runs to kilobytes; the whole body is in request_details.response.
MESSAGE_BODY_LIMIT = 500

# A reported version: major.minor, then the end, a patch level (".12") or a
# suffix ("-rc1", "-4b2c1e3a"). "v2.180" is 2.180, not 2.18.
VERSION = re.compile(r'^v?(\d+)\.(\d+)(\.|-|$)')


def parse_version(version):
    """(major, minor) of a reported version ("v2.19.12-012ed06", "v2.19-rc1"), or None when it doesn't parse."""
    match = VERSION.match(version or '')
    return (int(match.group(1)), int(match.group(2))) if match else None


def version_in(version, tested):
    """True when a reported version's major.minor is one of `tested` ("2.19", ...)."""
    minor = parse_version(version)
    return minor is not None and '%d.%d' % minor in tested


def validate_connection(module, product):
    """Fail before any request on connection options that cannot work.

    `product` names the server in the message ("Example" gives the example
    https://example.example.com).
    """
    params = module.params
    url = params['url']
    try:
        parts = urlsplit(url)
        usable = parts.scheme in ('http', 'https') and bool(parts.netloc)
    except ValueError:
        usable = False
    if not usable:
        module.fail_json(msg='url must be the address of the %s server, starting with http:// or https://, '
                             'for example https://%s.example.com. Got %r.' % (product, product.lower(), url))
    if params['timeout'] < 1:
        module.fail_json(msg='timeout must be 1 or more (seconds). Got %d.' % params['timeout'])
    for name in ('retries', 'retry_delay'):
        if params[name] < 0:
            module.fail_json(msg='%s must be 0 or more. Got %d.' % (name, params[name]))
    if params.get('client_key') and not params.get('client_cert'):
        module.fail_json(msg='client_key needs client_cert: a key alone cannot identify the client.')
    # A missing file would otherwise surface as an error from deep inside the
    # TLS setup. Only the path is named, never what a file holds.
    for name in ('client_cert', 'client_key'):
        path = params.get(name)
        if path and not os.path.isfile(path):
            module.fail_json(msg='%s %r is not a file on the host this module runs on.' % (name, path))


def redact(value, secret_keys, secrets=(), key=''):
    """A copy of a request body that is safe to show: secret strings replaced by MASK.

    A string is secret when it is one of `secrets`, or when the key it is
    under matches the regular expression `secret_keys`.
    """
    if isinstance(value, dict):
        return dict((k, redact(v, secret_keys, secrets, k)) for k, v in value.items())
    if isinstance(value, list):
        return [redact(v, secret_keys, secrets, key) for v in value]
    if isinstance(value, str) and value and (secret_keys.search(key) or value in secrets):
        return MASK
    return value


def secret_forms(secret):
    """The ways a server can write `secret` in an answer: as it is, and as JSON writes a string.

    JSON from Python escapes non-ASCII characters as \\uXXXX. JSON from Go, which the servers these
    collections talk to are written in, keeps them, but escapes <, > and & as \\u003c, \\u003e and \\u0026.
    """
    forms = set([secret])
    for ascii_only in (True, False):
        quoted = json.dumps(secret, ensure_ascii=ascii_only)[1:-1]
        forms.add(quoted)
        forms.add(quoted.replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026'))
    return forms


def scrub(text, secrets):
    """Text a server sent, with each of `secrets` replaced by MASK, in every form secret_forms() names."""
    if not text:
        return text
    forms = set()
    for secret in secrets:
        if isinstance(secret, str) and secret:
            forms.update(secret_forms(secret))
    for form in sorted(forms, key=len, reverse=True):
        text = text.replace(form, MASK)
    return text


def permanent_failure(error):
    """True for a failure without an HTTP response that asking again cannot cure.

    A certificate that does not verify, a ca_path that is not there and a host
    name that does not resolve are settings to fix, not moments to wait out.
    open_url hands on a missing CA file as it is and wraps the other two in a
    URLError. A refused or reset connection and a timeout stay worth a retry:
    a server that is restarting answers like that.
    """
    cause = error
    if isinstance(error, URLError) and isinstance(error.reason, BaseException):
        cause = error.reason
    if isinstance(cause, (ssl.SSLCertVerificationError, FileNotFoundError)):
        return True
    if isinstance(cause, socket.gaierror):
        # EAI_AGAIN is the resolver saying "try again later".
        return cause.errno != socket.EAI_AGAIN
    return False


class ApiError(Exception):
    """A request failed. Carries everything needed to see why.

    A client module subclasses it and sets `product`, the server's name in messages.
    """

    product = 'API'

    def __init__(self, method, url, status=None, response=None, request=None, reason=None, location=None):
        self.method = method
        self.url = url
        self.status = status
        self.response = response
        self.request = request
        self.reason = reason
        self.location = location
        super(ApiError, self).__init__(self.message())

    def message(self):
        if self.status is None:
            return '%s %s failed without an HTTP response: %s' % (self.method, self.url, self.reason)
        if 300 <= self.status < 400:
            # Redirects are not followed: the credentials would go wherever
            # the answer points. Nearly always url names the wrong scheme,
            # host or path, and the target shows the right one.
            target = 'a redirect to %s' % self.location if self.location else 'a redirect without a Location header'
            return ('%s %s returned HTTP %s, %s. Redirects are not followed. Set url to the address the '
                    '%s server itself answers on.' % (self.method, self.url, self.status, target, self.product))
        # Some servers answer a rejected write with a bare 400 and an empty body.
        body = self.response if self.response else '(empty body)'
        if len(body) > MESSAGE_BODY_LIMIT:
            body = '%s... (%d more characters; the whole body is in request_details.response)' % (
                body[:MESSAGE_BODY_LIMIT], len(body) - MESSAGE_BODY_LIMIT)
        msg = '%s %s returned HTTP %s: %s' % (self.method, self.url, self.status, body)
        if self.reason:
            msg += ' (%s)' % self.reason
        return msg

    def details(self):
        details = dict(method=self.method, url=self.url, status=self.status, response=self.response,
                       request=self.request)
        if self.location:
            details['location'] = self.location
        return details


class MissingReference(ValueError):
    """Something a task refers to by name (its project, for example) doesn't exist.

    A failure, except in check mode: there an earlier task of the same play
    may be the one that creates it, and check mode didn't.
    """


class ApiClient(object):
    """The connection options of one module run, and the request loop that uses them.

    A client module subclasses it and provides:
      - error_class, an ApiError subclass that names the product;
      - secret_keys, the regular expression of body keys whose values redact() hides;
      - open(url, **kwargs), which calls open_url with whatever more the product needs (a cookie jar);
    and may override:
      - secrets, every value an answer must not show;
      - resend_once(status), for an HTTP error that one more request, which uses up no attempt, can cure;
      - start() and close(), run around a module's work by run_client().
    """

    error_class = ApiError
    secret_keys = re.compile(r'secret|password|token', re.IGNORECASE)

    def __init__(self, module):
        self.module = module
        params = module.params
        validate_connection(module, self.error_class.product)
        self.validate_certs = params['validate_certs']
        self.ca_path = params.get('ca_path')
        self.client_cert = params.get('client_cert')
        self.client_key = params.get('client_key')
        self.use_proxy = params['use_proxy']
        self.timeout = params['timeout']
        self.retries = params['retries']
        self.retry_delay = params['retry_delay']

    @property
    def secrets(self):
        """Every value an answer must not show: by default the task's no_log values."""
        return set(self.module.no_log_values)

    def open(self, url, **kwargs):
        raise NotImplementedError('%s has no open()' % type(self).__name__)

    def resend_once(self, status):
        """True when an HTTP error with this status is worth one more request that uses up no attempt."""
        return False

    def start(self):
        """Run before a module's work."""

    def close(self):
        """Run after a module's work, also when it failed. Never raises."""

    def send(self, method, url, body=None, headers=None, expected=(200,), retry=False):
        """(parsed JSON or None, response headers with lower-case names) for one request.

        A read (retry=True) is sent again after a gateway status or a failure
        without an HTTP response, up to `retries` times, `retry_delay` seconds
        apart. A failure that asking again cannot cure (permanent_failure) is
        not sent again. Anything else raises error_class at once.
        """
        error_class = self.error_class
        send_headers = {'Accept': 'application/json'}
        send_headers.update(headers or {})
        data = None
        sent = None
        if body is not None:
            data = json.dumps(body)
            sent = self.redact(body)
            send_headers['Content-Type'] = 'application/json'

        attempts = 1 + (self.retries if retry else 0)
        attempt = 0
        resent = False
        while True:
            attempt += 1
            try:
                response = self.open(
                    url,
                    data=data,
                    headers=send_headers,
                    method=method,
                    timeout=self.timeout,
                    validate_certs=self.validate_certs,
                    ca_path=self.ca_path,
                    client_cert=self.client_cert,
                    client_key=self.client_key,
                    follow_redirects='none',
                    use_proxy=self.use_proxy,
                    use_netrc=False,
                )
                status = response.getcode()
                raw = to_text(response.read(), errors='surrogate_or_strict')
                resp_headers = dict((k.lower(), v) for k, v in (response.headers or {}).items())
            except HTTPError as e:
                try:
                    raw = to_text(e.read(), errors='surrogate_or_strict')
                except Exception:
                    raw = ''
                if not resent and self.resend_once(e.code):
                    resent = True
                    attempt -= 1
                    continue
                if e.code in RETRY_STATUSES and attempt < attempts:
                    time.sleep(self.retry_delay)
                    continue
                headers_in = getattr(e, 'headers', None)
                raise error_class(method, url, status=e.code, response=scrub(raw.strip(), self.secrets),
                                  request=sent, location=headers_in.get('Location') if headers_in else None)
            except (URLError, socket.timeout, ConnectionError, OSError, HTTPException) as e:
                # HTTPException: the answer was cut short or isn't HTTP at all
                # (IncompleteRead, BadStatusLine). Neither is an OSError.
                if attempt < attempts and not permanent_failure(e):
                    time.sleep(self.retry_delay)
                    continue
                raise error_class(method, url, request=sent,
                                  reason=scrub(to_text(e), self.secrets) or type(e).__name__)

            if status not in expected:
                raise error_class(method, url, status=status, response=scrub(raw.strip(), self.secrets),
                                  request=sent, location=resp_headers.get('location'))
            if not raw.strip():
                return None, resp_headers
            try:
                return json.loads(raw), resp_headers
            except ValueError:
                raise error_class(method, url, status=status, response=scrub(raw.strip(), self.secrets),
                                  request=sent, reason='response is not JSON')

    def redact(self, body):
        return redact(body, self.secret_keys, self.module.no_log_values)


def fail_from_error(module, error, **result):
    """fail_json with an ApiError's request/response details; the request is already redacted."""
    module.fail_json(msg=error.message(), request_details=error.details(), **result)


def run_client(module, client, handler, placeholder=None):
    """Run handler(client) between client.start() and client.close(), report its failure, or exit with its result.

    `placeholder` holds the module's own return values, empty. With it, a
    MissingReference in check mode is reported as a change instead of a failure.
    """
    try:
        try:
            client.start()
            result = handler(client)
        finally:
            client.close()
    except ApiError as e:
        fail_from_error(module, e)
    except MissingReference as e:
        if not module.check_mode or placeholder is None:
            module.fail_json(msg=to_text(e))
        module.warn('%s Check mode assumes that an earlier task creates it, and reports this task as changed '
                    'without comparing anything.' % to_text(e))
        result = dict(placeholder, changed=True, diff=dict(before={}, after={}))
    except ValueError as e:
        module.fail_json(msg=to_text(e))
    except Exception as e:
        # Anything else is a bug here or an answer in a form the module doesn't
        # expect. The message names the exception; the traceback goes into
        # `exception`, which Ansible shows only with -vvv.
        module.fail_json(msg='Unexpected %s: %s. %s may have answered in a form this module does not '
                             'expect.' % (type(e).__name__, to_text(e), client.error_class.product),
                         exception=traceback.format_exc())
    module.exit_json(**result)
