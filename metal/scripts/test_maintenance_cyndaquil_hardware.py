"""Reject changed SSD identity, unsupported assumptions and real SMART failures."""

import copy
import unittest
import maintenance_cyndaquil_hardware as hardware


def fixture():
    table = [{'id': n, 'name': name, 'raw': {'value': 0}, 'value': 100,
              'worst': 100, 'thresh': 10, 'when_failed': ''}
             for n, name in hardware.ERROR_ATTRIBUTES.items()]
    for n, name, raw, normalized in ((173, 'Wear_Leveling_Count', 321, 84),
                                    (174, 'Unexpect_Power_Loss_Ct', 25, 99),
                                    (180, 'Unused_Rsvd_Blk_Cnt_Tot', 1568, 100)):
        table.append({'id': n, 'name': name, 'raw': {'value': raw}, 'value': normalized,
                      'worst': normalized, 'thresh': 5, 'when_failed': ''})
    return {'model_name': 'SAMSUNG MZ7LN512HCHP-000L1', 'firmware_version': 'EMT04L0Q',
            'serial_number': 'S1ZKNXAGB03370', 'user_capacity': {'bytes': 512110190592},
            'rotation_rate': 0, 'smart_status': {'passed': True},
            'ata_smart_error_log': {'summary': {'count': 0}},
            'ata_smart_attributes': {'table': table}}


class HardwareAcceptanceTests(unittest.TestCase):
    def test_supported_schema_preserves_historical_observations(self):
        result = hardware.validate_smart(fixture())
        self.assertEqual(result['unsupported_attributes'], [197, 198])
        self.assertEqual(result['historical_unexpected_power_losses'], 25)
        self.assertEqual(result['wear_leveling_normalized'], 84)
        self.assertEqual(result['unused_reserved_blocks'], 1568)
        self.assertFalse(result['self_test_performed_by_observer'])

    def test_every_error_counter_and_schema_is_required(self):
        for number in hardware.ERROR_ATTRIBUTES:
            for change in ('missing', 'nonzero', 'renamed'):
                with self.subTest(number=number, change=change):
                    smart = fixture()
                    table = smart['ata_smart_attributes']['table']
                    row = next(a for a in table if a['id'] == number)
                    if change == 'missing':
                        table.remove(row)
                    elif change == 'nonzero':
                        row['raw']['value'] = 1
                    else:
                        row['name'] = 'unknown'
                    with self.assertRaises(AssertionError):
                        hardware.validate_smart(smart)

    def test_identity_threshold_and_device_failure_are_refused(self):
        original = fixture()
        mutations = [lambda s: s.update(model_name='other'),
                     lambda s: s.update(serial_number='other'),
                     lambda s: s.update(firmware_version='other'),
                     lambda s: s['smart_status'].update(passed=False),
                     lambda s: s['ata_smart_error_log']['summary'].update(count=1),
                     lambda s: s['ata_smart_attributes']['table'][0].update(value=10),
                     lambda s: s['ata_smart_attributes']['table'][0].update(worst=10),
                     lambda s: s['ata_smart_attributes']['table'][0].update(when_failed='past')]
        for mutate in mutations:
            smart = copy.deepcopy(original)
            mutate(smart)
            with self.assertRaises(AssertionError):
                hardware.validate_smart(smart)


if __name__ == '__main__':
    unittest.main()
