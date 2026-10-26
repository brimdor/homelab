#!/usr/bin/env python3
"""Skip only the October 26 Kured window using its expiring runtime lock."""

import argparse
from datetime import datetime, timezone
import hashlib
import json

from maintenance_coordination import Kubectl, LOCK, Ownership, encoded, require


EXPIRES = datetime(2026, 10, 26, 12, 5, tzinfo=timezone.utc)
OWNER = 'manual-maintenance-103-skip-20261026'
DS_UID = '4abc4fee-c3be-440e-8945-34bb3fb15ce1'
TEMPLATE_SHA = '81ca94121a6f371197cec5e55c914542c48656231b1f1ad69388ec2a507550ba'


def hold(api):
    ds, _, nodes = api.snapshot()
    ownership = Ownership(api, DS_UID, {
        n['metadata']['name']: n['metadata']['uid'] for n in nodes})
    ds = ownership.observed()
    template = ds['spec']['template']
    require(hashlib.sha256(encoded(template).encode()).hexdigest() == TEMPLATE_SHA,
            'Kured template changed; review before holding')
    now = datetime.now(timezone.utc)
    require(datetime(2026, 10, 26, tzinfo=timezone.utc) <= now < EXPIRES,
            'this one-night operation is outside its authorized date')
    annotations = ds['metadata'].get('annotations', {})
    require('homelab.eaglepass.io/maintenance-owner' not in annotations,
            'active maintenance owner exists; do not replace it')
    if LOCK in annotations:
        lock = json.loads(annotations[LOCK])
        require(lock.get('nodeID') == OWNER, 'another reboot owner holds the lock')
        created = datetime.fromisoformat(lock['created'].replace('Z', '+00:00'))
        require(lock['TTL'] > 0 and
                abs((EXPIRES - created).total_seconds() - lock['TTL'] / 1_000_000_000) < 0.001,
                'existing lock expiry differs; do not overwrite it')
    else:
        # Kured 1.21 reads the holder's TTL in nanoseconds, including manual locks.
        delta = EXPIRES - now
        ttl = ((delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds) * 1000
        lock = {'nodeID': OWNER, 'created': now.isoformat().replace('+00:00', 'Z'),
                'metadata': {'unschedulable': True}, 'TTL': ttl}
        ownership.patch(ds, {LOCK: encoded(lock)})
    after = ownership.observed()
    require(json.loads(after['metadata']['annotations'][LOCK]) == lock,
            'lock readback differs; inspect before retrying')
    require(after['spec'] == ds['spec'], 'Kured desired runtime changed')
    return {'owner': OWNER, 'expires_utc': EXPIRES.isoformat(),
            'schedule_unchanged': True, 'template_sha256': TEMPLATE_SHA,
            'daemonset_uid': DS_UID, 'lock': lock}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kubectl', required=True)
    args = parser.parse_args()
    print(encoded(hold(Kubectl(args.kubectl))))


if __name__ == '__main__':
    main()
