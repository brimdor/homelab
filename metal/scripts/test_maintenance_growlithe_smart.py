"""Reject actual faults while preserving unsupported and historical evidence."""

import copy
import unittest

from maintenance_growlithe_smart import validate


def sample():
    sata = {'serial_number': '3C320074050513551212', 'model_name': 'SSD 512GB',
            'firmware_version': 'VE0R6362', 'smartctl': {'exit_status': 0},
            'smart_status': {'passed': True}, 'ata_smart_attributes': {'table': [
                {'id': i, 'raw': {'value': 0}, 'value': 100, 'thresh': 10, 'when_failed': ''}
                for i in (1, 5, 187, 196)]}, 'ata_smart_error_log': {'extended': {'count': 0}},
            'ata_device_statistics': {'pages': [
                {'number': page, 'table': [{'offset': offset, 'value': value, 'flags': {'valid': True}}]}
                for page, offset, value in ((4, 8, 0), (4, 16, 0), (6, 24, 0), (7, 8, 24))]},
            'sata_phy_event_counters': {'table': [{'id': 1, 'value': 0, 'overflow': False}]}}
    nvme = {'serial_number': 'S58SNM0R508184P', 'model_name': 'Samsung SSD 970 EVO Plus 500GB',
            'firmware_version': '2B2QEXM7', 'smartctl': {'exit_status': 0}, 'smart_status': {'passed': True},
            'nvme_smart_health_information_log': {'critical_warning': 0, 'media_errors': 0,
                'available_spare': 100, 'available_spare_threshold': 10, 'percentage_used': 10,
                'num_err_log_entries': 8434}, 'nvme_error_information_log': {'size': 64, 'read': 64,
                'unread': 0, 'table': [{'error_count': 8434, 'submission_queue_id': 0,
                    'lba': {'value': 0}, 'nsid': 1,
                    'status_field': {'status_code_type': 0, 'status_code': 2}}]}}
    return sata, nvme


class SmartTests(unittest.TestCase):
    def test_supported_alternative_counters_preserve_unknown_history(self):
        value = validate(*sample(), [])
        self.assertEqual(value['unsupported_sata_attributes'], [197, 198, 199])
        self.assertEqual(value['nvme_historical_error_count'], 8434)
        self.assertEqual(value['nvme_historical_error_cause'], 'UNKNOWN')

    def test_real_faults_or_missing_current_evidence_are_rejected(self):
        changes = [
            lambda s, n: s.update(serial_number='foreign'),
            lambda s, n: s['smart_status'].update(passed=False),
            lambda s, n: s['ata_smart_attributes']['table'][0]['raw'].update(value=1),
            lambda s, n: s['ata_smart_attributes']['table'][0].update(when_failed='Past'),
            lambda s, n: s['ata_smart_attributes']['table'][0].update(value=10),
            lambda s, n: s['ata_device_statistics']['pages'][0]['table'][0].update(value=1),
            lambda s, n: s['sata_phy_event_counters']['table'][0].update(value=1),
            lambda s, n: s['ata_smart_error_log']['extended'].update(count=1),
            lambda s, n: n['nvme_smart_health_information_log'].update(media_errors=1),
            lambda s, n: n['nvme_smart_health_information_log'].update(critical_warning=1),
            lambda s, n: n['nvme_error_information_log'].update(read=16),
            lambda s, n: n['nvme_error_information_log'].update(table=[]),
            lambda s, n: n['nvme_error_information_log']['table'][0].update(submission_queue_id=1),
            lambda s, n: n['nvme_error_information_log']['table'][0]['status_field'].update(status_code_type=2),
            lambda s, n: n['nvme_error_information_log']['table'][0]['status_field'].update(status_code=1),
            lambda s, n: n['nvme_error_information_log']['table'][0]['lba'].update(value=1),
        ]
        for index, change in enumerate(changes):
            with self.subTest(index=index):
                sata, nvme = copy.deepcopy(sample()); change(sata, nvme)
                with self.assertRaises(RuntimeError):
                    validate(sata, nvme, [])
        with self.assertRaises(RuntimeError):
            validate(*sample(), ['I/O error'])


if __name__ == '__main__':
    unittest.main()
