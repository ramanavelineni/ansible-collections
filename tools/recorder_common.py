# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""What the two fixture recorders share.

The recorders create, change and delete objects on the server they are
pointed at, and what they write ends up in a public repository. So they

- refuse a server that is not on this machine, unless told otherwise
  (require_throwaway),
- keep only their own objects from every listing (keep),
- look through a recording for secrets before it is written (write_fixture), and
- take their own objects off the server again, before an area is recorded and
  after it, whether it worked or not (run_area).
"""

import ipaddress
import json
import os
import re
import socket
import sys
import urllib.parse

ALLOW_REMOTE = '--allow-remote'
# Seconds one request may take. A recorder that hangs keeps its objects on the server.
TIMEOUT = 30


def parse_args(argv, areas):
    """(url, areas to record, allow_remote) from the command line; exits on a usage error."""
    args = [a for a in argv[1:] if a != ALLOW_REMOTE]
    if not args or args[0].startswith('-'):
        sys.exit('usage: %s [%s] <server url> [AREA ...]   (areas: %s)'
                 % (argv[0], ALLOW_REMOTE, ', '.join(sorted(areas))))
    chosen = args[1:] or sorted(areas)
    unknown = [a for a in chosen if a not in areas]
    if unknown:
        sys.exit('unknown area(s) %s; known: %s' % (', '.join(unknown), ', '.join(sorted(areas))))
    return args[0], chosen, ALLOW_REMOTE in argv[1:]


def is_loopback(url, resolve=socket.getaddrinfo):
    """Whether the URL's host is this machine: a loopback address, or a name that only resolves to them."""
    host = urllib.parse.urlsplit(url).hostname
    if not host:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        pass
    try:
        addresses = [info[4][0] for info in resolve(host, None)]
    except OSError:
        return False
    return bool(addresses) and all(ipaddress.ip_address(a.split('%')[0]).is_loopback for a in addresses)


def require_throwaway(url, allow_remote, resolve=socket.getaddrinfo):
    """Exit unless the server is on this machine or the caller passed --allow-remote."""
    if allow_remote or is_loopback(url, resolve):
        return
    sys.exit('%s is not on this machine. The recorder creates, changes and deletes objects, and writes\n'
             'what the server answers into the repository, so it only records from a throwaway server.\n'
             'If this one is throwaway too, pass %s.' % (url, ALLOW_REMOTE))


def run_area(area, record, sweep, srv, out):
    """Record one area into out, with the area's own objects swept off the server before and after.

    sweep(srv) removes what the area creates, and nothing else: it goes by the
    names the area gives its objects. Before the recording it clears what an
    earlier run that died left behind; after it, it clears what this run left,
    also when the recording failed. The failure of the recording is what is
    reported then, not a failure of the sweep that follows it.
    """
    sweep(srv)
    try:
        record(srv, out)
    except BaseException:
        try:
            sweep(srv)
        except (Exception, SystemExit) as e:
            print('%s: cleaning up after the failure failed as well: %s' % (area, e), file=sys.stderr)
        raise
    sweep(srv)


def keep(result, wanted):
    """A recorded listing with only the items wanted(item) accepts.

    A server that isn't empty lists other people's objects as well; those
    are not the recording's to publish. X-Total-Count, where the server
    sent it, is set to what is left.
    """
    body = result.get('body')
    if not isinstance(body, list):
        return result
    kept = [item for item in body if wanted(item)]
    out = dict(result, body=kept)
    if 'x-total-count' in (result.get('headers') or {}):
        out['headers'] = dict(result['headers'], **{'x-total-count': str(len(kept))})
    return out


# Shapes of credentials that have no business in a fixture, whatever key they are under.
SECRET_SHAPES = (
    ('a private key', re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----')),
    ('a JSON Web Token', re.compile(r'\beyJ[\w-]{8,}\.eyJ[\w-]{8,}\.[\w-]+')),
    ('a Semaphore runner token', re.compile(r'\bsmrs_[\w-]{8,}')),
)
# Keys whose value is a credential. A fixture may hold nothing, a mask, or one of the recorder's dummies there.
# A recorder whose server has more such keys passes its own pattern.
SECRET_KEY = re.compile(r'(secret|password|passphrase|private_key|token)$', re.I)
# An empty JSON object as a string is what Semaphore answers for a new task's "secret".
DUMMY = re.compile(r'^\**$|^\{\}$|not-?a-?real', re.I)


def find_secrets(responses, secrets=(), placeholders=(), secret_key=SECRET_KEY):
    """What looks like a secret in a recording, as a list of '<response>: <what>' lines.

    secrets are the live values the run knows (the admin password, tokens the
    server generated); placeholders are the stand-ins the recorder writes in
    their place. The lines never quote a value.
    """
    found = []

    def strings(value, key=None):
        if isinstance(value, dict):
            for k, v in value.items():
                yield None, str(k)
                for pair in strings(v, str(k)):
                    yield pair
        elif isinstance(value, list):
            for item in value:
                for pair in strings(item, key):
                    yield pair
        elif isinstance(value, str):
            yield key, value

    for name in sorted(responses):
        reasons = []
        for key, text in strings(responses[name]):
            if text in placeholders:
                continue
            if any(s and s in text for s in secrets):
                reasons.append('holds a secret this run used (the admin password, or a token the server made)')
            for what, shape in SECRET_SHAPES:
                if shape.search(text):
                    reasons.append('holds %s' % what)
            if key and secret_key.search(key) and not DUMMY.search(text):
                reasons.append('has a value under "%s"' % key)
        found.extend('%s: %s' % (name, reason) for reason in sorted(set(reasons)))
    return found


def write_fixture(path, version, responses, secrets=(), placeholders=(), secret_key=SECRET_KEY):
    """Write one area's recording, unless something in it looks like a secret."""
    found = find_secrets(responses, secrets, placeholders, secret_key)
    if found:
        sys.exit('not writing %s, it would publish secrets:\n  %s\n'
                 'If the admin password is a common word (it also matches where that word is used\n'
                 'otherwise), give the throwaway server another one.' % (path, '\n  '.join(found)))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(dict(recorded_from=version, responses=responses), f, indent=2, sort_keys=True)
        f.write('\n')
    print('wrote %s (%d responses, server %s)' % (path, len(responses), version))
