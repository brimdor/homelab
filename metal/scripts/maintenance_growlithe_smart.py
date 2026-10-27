"""Read-only acceptance for Growlithe's exact drives; retain historical uncertainty."""

from maintenance_coordination import require


def validate(sata, nvme, kernel_findings):
    require(not kernel_findings, 'current boot has storage errors')
    require(sata['serial_number'] == '3C320074050513551212' and
            sata['model_name'] == 'SSD 512GB' and sata['firmware_version'] == 'VE0R6362' and
            sata['smartctl']['exit_status'] == 0 and sata['smart_status']['passed'] is True,
            'SATA identity or SMART health differs')
    rows = sata['ata_smart_attributes']['table']
    attrs = {row['id']: row for row in rows}
    require(len(attrs) == len(rows) and 5 in attrs and all(
        not row['when_failed'] and (not row['thresh'] or row['value'] > row['thresh'])
        for row in rows), 'SATA failed, missing or duplicate attributes')
    checked = (1, 5, 187, 196, 197, 198, 199)
    require(all(attrs[i]['raw']['value'] == 0 for i in checked if i in attrs),
            'SATA reported read, reallocation, uncorrectable or CRC error')
    require(sata['ata_smart_error_log']['extended']['count'] == 0, 'SATA error log is nonempty')
    stats = {(page['number'], row['offset']): row
             for page in sata['ata_device_statistics']['pages'] for row in page['table']}
    for key in ((4, 8), (4, 16), (6, 24)):
        require(stats[key]['flags']['valid'] and stats[key]['value'] == 0,
                'ATA standard uncorrectable, interrupted-command or CRC finding')
    require(stats[(7, 8)]['flags']['valid'] and 0 <= stats[(7, 8)]['value'] < 100,
            'SATA endurance is exhausted or unavailable')
    phy = [row for row in sata['sata_phy_event_counters']['table'] if row['id'] == 1]
    require(len(phy) == 1 and phy[0]['value'] == 0 and not phy[0]['overflow'], 'SATA ICRC finding')
    require(nvme['serial_number'] == 'S58SNM0R508184P' and
            nvme['model_name'] == 'Samsung SSD 970 EVO Plus 500GB' and
            nvme['firmware_version'] == '2B2QEXM7' and nvme['smartctl']['exit_status'] == 0 and
            nvme['smart_status']['passed'] is True, 'NVMe identity or SMART health differs')
    health = nvme['nvme_smart_health_information_log']
    require(health['critical_warning'] == health['media_errors'] == 0 and
            health['available_spare'] >= health['available_spare_threshold'] and
            0 <= health['percentage_used'] < 100, 'NVMe health, media or endurance finding')
    log = nvme['nvme_error_information_log']; errors = log.get('table', [])
    total = health['num_err_log_entries']
    require(log['read'] == log['size'] == 64 and log['unread'] == 0 and total >= 0,
            'complete NVMe retained error log required')
    # Upstream smartd classifies Invalid Field as non-device-related; older entries are not recoverable after resets.
    require((total == 0 and not errors) or total > 0 and errors and
            max(e['error_count'] for e in errors) == total and
            len({e['error_count'] for e in errors}) == len(errors) and all(
                0 < e['error_count'] <= total and e['submission_queue_id'] == 0 and
                e['lba']['value'] == 0 and e['nsid'] in (0, 1) and
                e['status_field']['status_code_type'] == 0 and
                e['status_field']['status_code'] == 2 for e in errors),
            'NVMe retained log contains a device, IO, unknown or unattributed current error')
    return {'sata_smart_passed': True, 'sata_standard_error_counters': 0,
            'sata_endurance_used_percent': stats[(7, 8)]['value'],
            'sata_checked_attributes': {str(i): attrs[i]['raw']['value'] for i in checked if i in attrs},
            'unsupported_sata_attributes': [i for i in (197, 198, 199) if i not in attrs],
            'vendor_specific_raw_values_not_interpreted': True,
            'nvme_smart_passed': True, 'nvme_health': health,
            'nvme_retained_admin_invalid_field_entries': len(errors),
            'nvme_historical_error_count': total, 'nvme_historical_error_cause': 'UNKNOWN',
            'historical_entries_not_claimed_reconstructed': True, 'current_boot_storage_errors': []}
