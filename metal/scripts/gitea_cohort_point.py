"""Protect the joint recovery descriptor and existing Secret bytes on Pikachu."""

import base64
import hashlib
from pathlib import Path
import re

import gitea_postgres_cold_point as cold
import gitea_shared_guarded_source as shared
import valkey_cohort_point as valkey


common = cold.common
FORMAT = 'gitea-three-store-recovery-103-v1'


def validate(value):
    try:
        if (set(value) != {'format', 'cluster_uid', 'profile_revision', 'ordinary_revision',
                          'points', 'proofs', 'secrets', 'source_holds_reverified', 'normal_postgres_verified'} or
                value['format'] != FORMAT or value['cluster_uid'] != common.CLUSTER_UID or
                not re.fullmatch('[a-f0-9]{40}', value['profile_revision']) or
                not re.fullmatch('[a-f0-9]{40}', value['ordinary_revision']) or
                value['source_holds_reverified'] is not True or value['normal_postgres_verified'] is not True or
                set(value['points']) != {'postgres', 'shared', 'valkey'} or
                set(value['proofs']) != {'postgres', 'shared', 'valkey'} or
                set(value['secrets']) != {'gitea', 'gitea-init', 'gitea-inline-config', 'gitea-postgresql'}):
            raise ValueError()
        for name, point in value['points'].items():
            if (not {'point', 'manifest_sha256'} <= set(point) or Path(point['point']).parent != common.ROOT or
                    not re.fullmatch('[a-f0-9]{64}', point['manifest_sha256']) or
                    value['proofs'][name]['accepted'] is not True or
                    value['proofs'][name]['manifest_sha256'] != point['manifest_sha256']):
                raise ValueError()
        pg, files, cache = (value['proofs'][name] for name in ('postgres', 'shared', 'valkey'))
        if (pg['independent_copies'] != 2 or len(pg['copies']) != 2 or
                any(c['administrator_authentication'] is not True or c['full_logical_data_equal'] is not True or
                    c['unchanged_hba'] is not True or c['clean_shutdown'] is not True for c in pg['copies']) or
                pg['copies'][0]['full_dump_sha256'] != pg['copies'][1]['full_dump_sha256'] or
                files['independent_restores'] != 2 or len(files['copies']) != 2 or
                files['copies'][0] != files['copies'][1] or files['copied_data_read_only'] is not True or
                cache['source_quiesced'] is not True or cache['cross_shard_atomic'] is not False or
                cache['original_replica_map'] != {1: 5, 2: 3, 4: 0} and
                cache['original_replica_map'] != {'1': 5, '2': 3, '4': 0} or
                [s['version'] for s in cache['stages']] != ['8.1.3', '8.1.10', '8.1.3'] or
                any(s['complete_six_node_data'] is not True or s['complete_aof_checked'] is not True for s in cache['stages'])):
            raise ValueError()
        for proof in (pg, files, cache):
            cleanup = proof['cleanup']
            if cleanup['scratch_absent'] is not True or not (
                    cleanup.get('containers_absent') is True or cleanup.get('owned_containers_absent') is True):
                raise ValueError()
        for secret in value['secrets'].values():
            if (set(secret) != {'uid', 'data'} or
                    not re.fullmatch('[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}', secret['uid']) or not secret['data']):
                raise ValueError()
            for key, raw in secret['data'].items():
                if not re.fullmatch('[a-zA-Z0-9._-]+', key) or not isinstance(raw, str):
                    raise ValueError()
                base64.b64decode(raw, validate=True)
    except (ValueError, KeyError, TypeError, AttributeError):
        raise RuntimeError('joint Gitea recovery descriptor differs; private details withheld') from None
    return value


def store(run_id, value):
    common.require_host('pikachu')
    common.private_root()
    common.run_identifier(run_id)
    validate(value)
    refs = value['points']
    pg = cold.verify(Path(refs['postgres']['point']), refs['postgres']['manifest_sha256'])
    files = cold.verify(Path(refs['shared']['point']), refs['shared']['manifest_sha256'], validator=shared.validate)
    path, cache = valkey.verify(refs['valkey']['run_id'], refs['valkey']['manifest_sha256'])
    if 'source_aof' in refs['valkey']:
        import valkey_source_aof as aof
        source_aof = refs['valkey']['source_aof']
        aof_path, aof_manifest = aof.verify(refs['valkey']['run_id'], source_aof['manifest_sha256'])
        if (str(aof_path) != source_aof['point'] or aof_manifest['rdb_manifest_sha256'] != refs['valkey']['manifest_sha256'] or
                value['proofs']['valkey'].get('actual_source_aofs_complete_before_replication') is not True or
                value['proofs']['valkey'].get('source_aof_manifest_sha256') != source_aof['manifest_sha256']):
            raise RuntimeError('joint actual source AOF provenance or independent recovery differs')
    if (pg['format'] not in (cold.GUARDED_FORMAT, cold.MAINTAINED_FORMAT) or
            not Path(refs['postgres']['point']).name.startswith('gitea-postgres-guarded-') or
            not Path(refs['shared']['point']).name.startswith('gitea-shared-guarded-') or str(path) != refs['valkey']['point'] or
            {pg['source']['revision'], files['source']['revision']} |
            {s['revision'] for s in cache['sources'].values()} != {value['profile_revision']}):
        raise RuntimeError('joint Gitea recovery points are not the same guarded candidate')
    destination = common.ROOT / ('gitea-cohort-' + run_id + '.json')
    encoded = common.canonical(value)
    checksum = hashlib.sha256(encoded).hexdigest()
    valkey.recovery.protected.write_json(destination, value)
    record, _identity = common.source_record(destination.name, destination)
    if record['sha256'] != checksum:
        raise RuntimeError('joint Gitea protected descriptor readback differs')
    return {'point': str(destination), 'manifest_sha256': checksum, 'accepted': True,
            'secret_values_in_response': False, 'cross_shard_atomic': False}
