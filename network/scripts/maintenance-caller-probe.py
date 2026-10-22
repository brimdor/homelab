#!/usr/bin/env python3
"""Read-only public path checks; caller location must be established independently."""

import argparse
import hashlib
import http.client
import json
from pathlib import Path
import socket
import ssl
import subprocess
import sys


TARGETS = (
    ('gitea', 'git.eaglepass.io', '/api/v1/version'),
    ('grafana', 'grafana.eaglepass.io', '/api/health'),
    ('dex', 'dex.eaglepass.io', '/.well-known/openid-configuration'),
)


def require_body(name, value):
    if not isinstance(value, dict):
        raise ValueError('unexpected JSON shape')
    if name == 'gitea':
        accepted = isinstance(value.get('version'), str) and bool(value['version'].strip())
    elif name == 'grafana':
        accepted = value.get('database') == 'ok'
    elif name == 'dex':
        accepted = value.get('issuer') == 'https://dex.eaglepass.io' and all(
            value.get(key) == expected for key, expected in {
                'authorization_endpoint': 'https://dex.eaglepass.io/auth',
                'token_endpoint': 'https://dex.eaglepass.io/token',
                'jwks_uri': 'https://dex.eaglepass.io/keys',
            }.items())
    else:
        accepted = False
    if not accepted:
        raise ValueError('endpoint contract differs')


def probe(name, host, path):
    if (name, host, path) not in TARGETS:
        raise ValueError('unreviewed endpoint')
    connection = http.client.HTTPSConnection(host, timeout=20, context=ssl.create_default_context())
    result = {'name': name, 'accepted': False}
    try:
        connection.connect()
        certificate = connection.sock.getpeercert(binary_form=True)
        connection.request('GET', path, headers={'Accept': 'application/json', 'Connection': 'close'})
        response = connection.getresponse()
        if response.status != 200:
            result['failure'] = 'redirect_refused' if 300 <= response.status < 400 else 'http_status'
            return result
        raw = response.read(1048577)
        if len(raw) > 1048576 or response.headers.get_content_type() != 'application/json':
            raise ValueError('response size or type differs')
        require_body(name, json.loads(raw))
        return dict(result, accepted=True, verified_tls=True, certificate_sha256=hashlib.sha256(certificate).hexdigest())
    except ssl.SSLError:
        result['failure'] = 'tls_validation'
    except (TimeoutError, socket.timeout):
        result['failure'] = 'request_timeout'
    except (OSError, http.client.HTTPException):
        result['failure'] = 'connection_failure'
    except (ValueError, UnicodeError):
        result['failure'] = 'response_contract'
    finally:
        connection.close()
    return result


def tailnet():
    try:
        response = subprocess.run(['tailscale', 'status', '--json'], capture_output=True, timeout=20)
        value = json.loads(response.stdout)
        return (response.returncode == 0 and value.get('BackendState') == 'Running' and
                value.get('MagicDNSSuffix') == 'tail18136a.ts.net')
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin', choices=('collector', 'outside-lan', 'tailnet'), required=True)
    args = parser.parse_args()
    result = {'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'claimed_origin': args.origin, 'origin_independently_verified': False,
              'authenticated_application_behavior_verified': False,
              'private_tailnet_data_path_verified': False}
    if args.origin == 'tailnet':
        result['expected_tailnet_running'] = tailnet()
        if not result['expected_tailnet_running']:
            print(json.dumps(dict(result, accepted=False, failure='existing_tailnet_state_unverified')))
            return 1
    result['checks'] = [probe(*target) for target in TARGETS]
    result['accepted'] = all(check['accepted'] for check in result['checks'])
    print(json.dumps(result, sort_keys=True))
    return 0 if result['accepted'] else 1


if __name__ == '__main__':
    sys.exit(main())
