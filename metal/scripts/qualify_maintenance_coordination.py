#!/usr/bin/env python3
"""Run native upstream Kured interoperability against a synthetic loopback API.

The caller builds the exact upstream version and routes/cleans all disposable
Go caches, source and binary. This is wire-protocol proof, not a real cluster.
"""

import argparse
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import subprocess
import threading
from urllib.parse import parse_qs, urlsplit

import maintenance_coordination as owner
from test_maintenance_coordination import API


PATH = '/apis/apps/v1/namespaces/kured/daemonsets/kured'


def qualify(binary):
    api = API()
    api.ds.update(apiVersion='apps/v1', kind='DaemonSet')
    api.ds['metadata']['annotations']['fixture-provenance'] = 'synthetic-only'
    original = copy.deepcopy(api.ds)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def answer(self, code, value):
            body = json.dumps(value).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def valid_path(self):
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query, strict_parsing=True)
            if parsed.path != PATH or query not in ({}, {'timeout': ['15s']}):
                self.answer(400, {'apiVersion': 'v1', 'kind': 'Status', 'status': 'Failure',
                                  'reason': 'BadRequest', 'message': 'Unexpected fixture path: ' + self.path[:200], 'code': 400})
                return False
            return True

        def do_GET(self):
            if not self.valid_path():
                return
            self.answer(200, api.snapshot()[0])

        def do_PUT(self):
            if not self.valid_path():
                return
            size = int(self.headers['Content-Length'])
            assert 0 < size < 100000
            desired = json.loads(self.rfile.read(size))
            with api.mutex:
                if (desired['metadata']['uid'] != api.ds['metadata']['uid'] or
                        desired['metadata']['resourceVersion'] != api.ds['metadata']['resourceVersion']):
                    self.answer(409, {'apiVersion': 'v1', 'kind': 'Status', 'status': 'Failure',
                                      'reason': 'Conflict', 'code': 409})
                    return
                for key, value in api.ds['spec']['template']['spec']['containers'][0].items():
                    assert desired['spec']['template']['spec']['containers'][0][key] == value
                desired['metadata']['resourceVersion'] = str(int(api.ds['metadata']['resourceVersion']) + 1)
                api.ds = desired
                api.writes += 1
                self.answer(200, copy.deepcopy(api.ds))

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    endpoint = 'http://127.0.0.1:' + str(server.server_port)
    result = {}

    def native(operation, holder):
        child = subprocess.Popen([str(binary), endpoint, operation, holder],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            stdout, stderr = child.communicate()
        finally:
            if child.poll() is None:
                child.terminate()
                child.wait()
            child.stdout.close()
            child.stderr.close()
        assert child.returncode == 0, 'native upstream fixture failed: ' + stderr.decode()[:500]
        return json.loads(stdout)

    try:
        first = native('acquire', 'fixture-b')
        assert first == {'acquired': True, 'holder': 'fixture-b'}
        try:
            api.controller().acquire('fixture-a', 39, 41, 'a' * 40)
        except RuntimeError:
            result['maintenance_refused_existing_kured_owner'] = True
        else:
            raise AssertionError('maintenance stole the native Kured lock')
        assert native('release', 'fixture-b') == {'released': True}
        original = copy.deepcopy(api.ds)
        journal = api.controller().acquire('fixture-a', 39, 41, 'a' * 40)
        assert native('acquire', 'fixture-b') == {'acquired': False, 'holder': journal['owner']}
        result['native_kured_refused_maintenance_owner'] = True
        assert 'error' in native('release', 'fixture-b')
        assert api.controller().resume(journal['owner']) == journal
        result['foreign_release_refused_and_controller_resume_passed'] = True
        try:
            api.controller().release(journal['owner'], lambda _: False)
        except RuntimeError:
            pass
        else:
            raise AssertionError('unsafe release passed')
        assert native('acquire', 'fixture-b') == {'acquired': False, 'holder': journal['owner']}
        result['failed_release_kept_native_kured_excluded'] = True
        api.controller().release(journal['owner'], lambda _: True)
        assert native('acquire', 'fixture-b') == {'acquired': True, 'holder': 'fixture-b'}
        assert native('release', 'fixture-b') == {'released': True}
        result['explicit_release_restored_native_kured_ownership'] = True
        assert api.ds['metadata']['annotations'] == original['metadata']['annotations']
        assert api.ds['spec'] == original['spec']
        result['unrelated_annotations_and_pod_template_unchanged'] = True
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        assert not thread.is_alive()
    result['loopback_server_closed_and_thread_reaped'] = True
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True)
    args = parser.parse_args()
    print(json.dumps(qualify(args.binary), indent=2))
