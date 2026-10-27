"""Production drain and acceptance share CORE's exact completed CUDA contract."""

import copy
import unittest
from unittest.mock import patch

import maintenance_production_node as production


class ArcanineGPUTests(unittest.TestCase):
    def fixture(self):
        owner = {'apiVersion': 'nvidia.com/v1', 'kind': 'ClusterPolicy',
                 'name': 'cluster-policy', 'uid': 'policy', 'controller': True}
        pod = {'metadata': {'namespace': 'gpu-operator', 'name': 'nvidia-cuda-validator-fixture',
                           'uid': 'completed-cuda', 'labels': {'app': 'nvidia-cuda-validator'},
                           'ownerReferences': [owner]},
               'spec': {'nodeName': 'arcanine', 'restartPolicy': 'OnFailure',
                        'serviceAccountName': 'nvidia-operator-validator',
                        'containers': [{'name': 'nvidia-cuda-validator'}],
                        'initContainers': [{'name': 'cuda-validation'}]},
               'status': {'phase': 'Succeeded',
                          'containerStatuses': [{'name': 'nvidia-cuda-validator', 'ready': False,
                              'state': {'terminated': {'exitCode': 0}}}],
                          'initContainerStatuses': [{'name': 'cuda-validation', 'ready': False,
                              'state': {'terminated': {'exitCode': 0}}}]}}
        validator = {'metadata': {'namespace': 'gpu-operator', 'name': 'nvidia-operator-validator',
                                 'uid': 'validator', 'generation': 3, 'ownerReferences': [copy.deepcopy(owner)]},
                     'status': {'observedGeneration': 3, 'desiredNumberScheduled': 2,
                                'currentNumberScheduled': 2, 'updatedNumberScheduled': 2,
                                'numberReady': 2, 'numberAvailable': 2}}
        resources = {'node': {'metadata': {'uid': 'node'}},
                     'daemonsets': {'items': [validator]}, 'clusterpolicy': {'metadata': {'uid': 'policy'}}}
        class API:
            def call(self, *args):return resources[args[1]]
        return pod, validator, resources, API()

    def test_only_exact_successful_cuda_policy_and_healthy_daemonset_are_accepted(self):
        with patch.object(production, 'NODE', 'arcanine'), patch.object(production, 'UID', 'node'):
            pod, validator, resources, api = self.fixture()
            self.assertEqual(production.completed_job_pod(api, pod), {
                'pod_uid': 'completed-cuda', 'cluster_policy_uid': 'policy'})
            faults = (
                lambda p, d, r: p['status'].update(phase='Running'),
                lambda p, d, r: p['metadata'].update(deletionTimestamp='now'),
                lambda p, d, r: p['spec'].update(nodeName='sprigatito'),
                lambda p, d, r: p['metadata']['labels'].update(app='other'),
                lambda p, d, r: p['status']['initContainerStatuses'][0]['state']['terminated'].update(exitCode=1),
                lambda p, d, r: d['status'].update(numberReady=1),
                lambda p, d, r: d['metadata']['ownerReferences'][0].update(uid='foreign'),
                lambda p, d, r: r['node']['metadata'].update(uid='replacement'),
                lambda p, d, r: r['clusterpolicy']['metadata'].update(uid='replacement'),
                lambda p, d, r: r['clusterpolicy']['metadata'].update(deletionTimestamp='now'),
            )
            for index, fault in enumerate(faults):
                pod, validator, resources, api = self.fixture(); fault(pod, validator, resources)
                with self.subTest(index=index), self.assertRaises((RuntimeError, ValueError)):
                    production.completed_job_pod(api, pod)


if __name__ == '__main__':
    unittest.main()
