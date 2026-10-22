"""Restore complete clean PostgreSQL points twice without modifying their source.

The returned catalog contains role verifiers: keep it in RAM, never reports/logs.
"""

import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile

import gitea_postgres_account_recovery as recovery
import gitea_postgres_cold_point as cold


common = recovery.common
retained = recovery.retained


def restore_copies(point, checksum, work, volumes, run_id, image_id, credentials, hba):
    manifest = cold.verify(point, checksum)
    copies, catalogs = [], []
    for number in range(2):
        if cold.verify(point, checksum) != manifest:
            raise RuntimeError('protected point changed before independent restore')
        child = work / ('cold-copy-' + str(number))
        child.mkdir(mode=0o700)
        retained.materialize(point, child / 'copy', manifest)
        if (child / 'copy/data/postmaster.pid').exists():
            raise RuntimeError('clean point unexpectedly contains a postmaster PID; never remove it')
        for source in recovery.mounts(child, volumes).values():
            if source != str(child / 'copy'):
                Path(source).mkdir(mode=0o755)
        container = None
        try:
            container = common.docker(*recovery.arguments(child, volumes, run_id)).stdout.decode().strip()
            if not re.fullmatch('[a-f0-9]{64}', container):
                raise RuntimeError('fresh-copy container identity missing')
            recovery.require_container(common.inspect(container), child, volumes, run_id, image_id)
            common.docker('start', container)
            value = common.inspect(container)
            recovery.require_container(value, child, volumes, run_id, image_id)
            net = ['nsenter', '-t', str(value['State']['Pid']), '-n', '--']
            common.require_network(json.loads(common.command([*net, 'ip', '-j', 'address']).stdout),
                                   sum((json.loads(common.command([*net, 'ip', family, '-j', 'route', 'show', 'table', 'all']).stdout)
                                        for family in ('-4', '-6')), []))
            if common.command([*net, 'ip', 'route', 'get', '10.0.20.50'], check=False).returncode == 0:
                raise RuntimeError('fresh-copy restore can route to production')
            state = cold.control.parse_control(recovery.execute(container, cold.control.ENTRY, recovery.DATA).stdout)
            if state != manifest['control']:
                raise RuntimeError('restored native control fingerprint differs before startup')
            recovery.execute(container, '/bin/sh', '-ceu',
                             'umask 077; cat > /tmp/source-hba.conf; : > /tmp/fixture.conf', input=hba)
            if hashlib.sha256(recovery.execute(container, '/bin/cat', recovery.NSS_LIBRARY).stdout).hexdigest() != recovery.NSS_SHA256:
                raise RuntimeError('fresh-copy native NSS library differs')
            expected_tree = retained.snapshot(child / 'copy')[0]
            preparation = recovery.prepare_standalone_directory(lambda *args: recovery.execute(container, *args))
            expected_tree['data']['mode'] = int(preparation['mode_after'], 8)
            if retained.snapshot(child / 'copy')[0] != expected_tree:
                raise RuntimeError('vendor directory preparation changed more than the copied PGDATA root mode')
            before = recovery.parse_catalog(recovery.single(container, recovery.catalog_sql().encode()).stdout)
            declared_verifier = 'md5' + hashlib.md5((credentials['admin'] + 'postgres').encode()).hexdigest()
            administrator_matches = next(r for r in before['roles'] if r['rolname'] == 'postgres')['rolpassword'] == declared_verifier
            recovery.normal_start(container, credentials, hba)
            dumps = recovery.dumps(container, credentials['app'], 'gitea')
            if administrator_matches and recovery.dumps(container, credentials['admin'], 'postgres') != dumps:
                raise RuntimeError('fresh-copy normal administrator authentication or complete dumps differ')
            hashes = {k: hashlib.sha256(v).hexdigest() for k, v in dumps.items()}
            del dumps
            state = recovery.stop(container)
            catalog = recovery.parse_catalog(recovery.single(container, recovery.catalog_sql().encode()).stdout)
            if catalog != before:
                raise RuntimeError('fresh-copy ordinary startup changed authorization or database metadata')
            catalogs.append(catalog)
            copies.append({'normal_start_and_tcp_auth': True, 'full_dump_sha256': hashes,
                           'catalog_sha256': hashlib.sha256(common.canonical(catalog)).hexdigest(),
                           'administrator_authentication': administrator_matches,
                           'native_directory_preparation': preparation,
                           'full_logical_data_equal': True,
                           'clean_shutdown': state['cluster_state'] == 'shut down', 'unchanged_hba': True})
        finally:
            if container:
                recovery.require_container(common.inspect(container), child, volumes, run_id, image_id)
                common.docker('rm', '-f', container)
                if common.docker('inspect', container, check=False).returncode == 0:
                    raise RuntimeError('owned fresh-copy container remains')
    if (copies[0]['full_dump_sha256'] != copies[1]['full_dump_sha256'] or catalogs[0] != catalogs[1] or
            cold.verify(point, checksum) != manifest):
        raise RuntimeError('independent fresh-copy restores disagree or protected point changed')
    return copies, catalogs[0]


def restore(point, checksum, credentials, hba, run_id):
    common.run_identifier(run_id)
    common.require_host('pikachu')
    common.private_root()
    if (point.parent != common.ROOT or not point.name.startswith('gitea-postgres-guarded-') or
            set(credentials) != {'admin', 'app'} or hashlib.sha256(hba).hexdigest() !=
            '625018986f8ca9e5f4bff3b1e4ffcdc29d4d96d3cd55ed07f02aa514a30f7e05'):
        raise RuntimeError('fresh production restore point or existing credential/HBA contract differs')
    manifest = cold.verify(point, checksum)
    if manifest['format'] != cold.GUARDED_FORMAT:
        raise RuntimeError('fresh production restore requires actual guarded-source provenance')
    retained.require_capacity(common.ROOT, manifest['tree'], 2)
    if common.docker('ps', '-aq', '--filter=label=' + recovery.LABEL).stdout.strip():
        raise RuntimeError('another owned PostgreSQL copy qualification is active')
    images = set(common.docker('image', 'ls', '-q', '--no-trunc').stdout.decode().split())
    scratch = Path(tempfile.mkdtemp(prefix='gitea-postgres-fresh-copy-', dir=common.ROOT))
    scratch.chmod(0o700)
    image_id = None
    result = {'accepted': False, 'manifest_sha256': checksum, 'production_mutated': False}
    catalog = None
    try:
        common.docker('pull', cold.control.IMAGE)
        image = json.loads(common.docker('image', 'inspect', cold.control.IMAGE).stdout)[0]
        image_id = image['Id']
        volumes = sorted((image['Config'].get('Volumes') or {}).keys())
        if (image['Architecture'] != 'amd64' or image['Os'] != 'linux' or
                not {cold.control.IMAGE, cold.control.IMAGE.removeprefix('docker.io/')}.intersection(image.get('RepoDigests', [])) or
                set(volumes) != {'/bitnami/postgresql', '/docker-entrypoint-initdb.d', '/docker-entrypoint-preinitdb.d'}):
            raise RuntimeError('exact fresh-restore PostgreSQL image differs')
        copies, catalog = restore_copies(point, checksum, scratch, volumes, run_id, image_id, credentials, hba)
        result.update(accepted=True, copies=copies, independent_copies=2, protected_point_unchanged=True)
    finally:
        if common.docker('ps', '-aq', '--filter=label=' + recovery.LABEL).stdout.strip():
            raise RuntimeError('owned fresh-copy container remains; preserve scratch')
        allocated = sum(p.lstat().st_blocks * 512 for p in scratch.rglob('*'))
        shutil.rmtree(scratch)
        if image_id and image_id not in images and not common.docker('ps', '-aq', '--filter=ancestor=' + image_id).stdout.strip():
            common.docker('image', 'rm', cold.control.IMAGE)
            if common.docker('image', 'inspect', image_id, check=False).returncode == 0:
                raise RuntimeError('new unused fresh-copy image remains')
        cold.verify(point, checksum)
        result['cleanup'] = {'scratch_absent': not scratch.exists(), 'containers_absent': True,
                             'allocated_bytes_removed': allocated}
    return result, catalog
