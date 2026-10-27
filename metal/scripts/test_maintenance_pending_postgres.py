#!/usr/bin/env python3
"""The temporary database outage cannot authorize unrelated maintenance failures."""

import unittest

from maintenance_production_node import pending_postgres_dependent


class NoApi:
    def call(self, *unused):
        raise AssertionError('unreviewed requests must not reach the API')


class PendingDatabaseTest(unittest.TestCase):
    def test_unrelated_or_released_owner_is_not_an_exception(self):
        item = {'kind': 'Deployment', 'metadata': {'namespace': 'versa', 'name': 'versa'}}
        self.assertIsNone(pending_postgres_dependent(NoApi(), item, {'owner': 'foreign'}))
        owner = {'owner': 'homelab-maintenance-103-1c844363-2bac-4e15-90f5-6139f5624d5c'}
        item['metadata']['namespace'] = 'unrelated'
        self.assertIsNone(pending_postgres_dependent(NoApi(), item, owner))

    def test_changed_approved_deployment_fails_closed(self):
        item = {'kind': 'Deployment', 'metadata': {'namespace': 'versa', 'name': 'versa',
                'uid': 'replacement', 'generation': 40}, 'spec': {}}
        owner = {'owner': 'homelab-maintenance-103-1c844363-2bac-4e15-90f5-6139f5624d5c'}
        with self.assertRaisesRegex(RuntimeError, 'approved dependent deployment changed'):
            pending_postgres_dependent(NoApi(), item, owner)


if __name__ == '__main__':
    unittest.main()
