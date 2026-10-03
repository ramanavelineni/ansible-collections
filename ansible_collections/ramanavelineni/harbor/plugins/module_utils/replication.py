# Copyright: ramanavelineni
# Apache License 2.0 (see LICENSE or https://www.apache.org/licenses/LICENSE-2.0)

"""Shared helpers for the registry and replication modules."""

# Adapter types Harbor 2.14 and 2.15 accept (GET /replication/adapters).
REGISTRY_TYPES = ('ali-acr', 'aws-ecr', 'azure-acr', 'docker-hub', 'docker-registry', 'github-ghcr',
                  'google-gcr', 'harbor', 'huawei-SWR', 'jfrog-artifactory', 'tencent-tcr', 'volcengine-cr')

FILTER_TYPES = ('name', 'tag', 'label', 'resource')
DECORATIONS = ('matches', 'excludes')
RESOURCE_VALUES = ('image', 'artifact')


def normalize_url(url):
    """A registry URL as Harbor stores it: without a trailing slash."""
    return (url or '').rstrip('/')


def registry_view(registry):
    """A registry endpoint as the registry modules return it (never a secret)."""
    credential = registry.get('credential') or {}
    return dict(
        id=registry.get('id'), name=registry.get('name'), type=registry.get('type'),
        url=registry.get('url') or '', description=registry.get('description') or '',
        insecure=bool(registry.get('insecure', False)),
        credential_type=credential.get('type') or '', access_key=credential.get('access_key') or '',
        has_secret=bool(credential.get('access_secret')),
        ca_certificate=registry.get('ca_certificate') or '',
        status=registry.get('status') or '',
    )


def validate_cron(cron):
    """Raise ValueError unless Harbor accepts `cron` for a scheduled replication."""
    parts = (cron or '').split()
    if len(parts) != 6:
        raise ValueError('trigger.cron must have 6 fields (seconds minutes hours day-of-month month '
                         'day-of-week), for example "0 0 2 * * *"; got %r.' % cron)
    if parts[0] != '0':
        raise ValueError('The first (seconds) field of trigger.cron must be 0; got %r.' % cron)
    if parts[1] == '*':
        raise ValueError('Harbor does not allow * in the minutes field of a replication schedule; got %r.' % cron)


def normalize_filter(item):
    """A replication filter in a comparable shape, after checking it."""
    ftype = item.get('type')
    value = item.get('value')
    decoration = item.get('decoration') or ''
    if ftype not in FILTER_TYPES:
        raise ValueError('Filter type must be one of %s, not %r.' % (', '.join(FILTER_TYPES), ftype))
    if ftype == 'label':
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ValueError('A label filter takes a list of label names as its value.')
        value = sorted(value)
    else:
        if not isinstance(value, str):
            raise ValueError('A %s filter takes a string as its value, not %r.' % (ftype, value))
        if ftype == 'resource' and value not in RESOURCE_VALUES:
            raise ValueError('A resource filter value must be one of %s, not %r.' % (', '.join(RESOURCE_VALUES), value))
    if decoration:
        if ftype not in ('tag', 'label'):
            raise ValueError('Only tag and label filters take a decoration (matches or excludes).')
        if decoration not in DECORATIONS:
            raise ValueError('Filter decoration must be matches or excludes, not %r.' % decoration)
    return dict(type=ftype, value=value, decoration=decoration)


def filters_key(filters):
    """Order-independent comparison key for a list of normalized filters."""
    return sorted((f['type'], repr(f['value']), f['decoration']) for f in filters)


def replication_view(policy):
    """A replication policy as the replication modules return it.

    The local Harbor side of a policy comes back as registry id 0 ("Local");
    it is shown as null.
    """
    src = policy.get('src_registry') or {}
    dest = policy.get('dest_registry') or {}
    trigger = policy.get('trigger') or {}
    settings = trigger.get('trigger_settings') or {}
    filters = [dict(type=f.get('type'), value=sorted(f.get('value')) if isinstance(f.get('value'), list) else f.get('value'),
                    decoration=f.get('decoration') or '')
               for f in policy.get('filters') or []]
    return dict(
        id=policy.get('id'), name=policy.get('name'), description=policy.get('description') or '',
        src_registry=src.get('name') if src.get('id') else None,
        dest_registry=dest.get('name') if dest.get('id') else None,
        dest_namespace=policy.get('dest_namespace') or '',
        dest_namespace_replace_count=policy.get('dest_namespace_replace_count', -1),
        trigger=dict(type=trigger.get('type') or 'manual', cron=settings.get('cron') or ''),
        filters=filters,
        enabled=bool(policy.get('enabled', False)),
        override=bool(policy.get('override', False)),
        replicate_deletion=bool(policy.get('replicate_deletion', policy.get('deletion', False))),
        speed=int(policy.get('speed') or 0),
        copy_by_chunk=bool(policy.get('copy_by_chunk', False)),
        single_active_replication=bool(policy.get('single_active_replication', False)),
    )
