"""Exercise real ctypes argument widths and cleanup with a synthetic CUDA driver."""

import ctypes as C
import unittest

import maintenance_cuda as cuda


class Function:
    def __init__(self, name, driver):self.name, self.driver = name, driver
    def __call__(self, *args):
        self.driver.calls.append(self.name)
        if self.name == self.driver.failure:return 999
        if self.name in ('cuDeviceGetCount', 'cuDeviceGetAttribute'):
            value = 1 if self.name == 'cuDeviceGetCount' else self.driver.capability[0 if args[1] == 75 else 1]
            C.cast(args[0], C.POINTER(C.c_int))[0] = value
        if self.name in ('cuCtxCreate_v2', 'cuModuleLoadData', 'cuModuleGetFunction'):
            C.cast(args[0], C.POINTER(C.c_void_p))[0] = 123
        if self.name == 'cuMemAlloc_v2':C.cast(args[0], C.POINTER(C.c_uint64))[0] = 456
        if self.name == 'cuMemcpyDtoH_v2':C.cast(args[0], C.POINTER(C.c_uint32))[0] = self.driver.output
        return 0


class Driver:
    def __init__(self, failure=None, output=42, capability=(8, 6)):
        self.failure, self.output, self.calls = failure, output, []
        self.capability = capability
    def __getattr__(self, name):return Function(name, self)


class CUDATests(unittest.TestCase):
    def test_turing_requires_its_own_capability_and_ptx(self):
        result = cuda.execute(Driver(capability=(7, 5)), (7, 5))
        self.assertEqual(result['result'], 42)
        self.assertNotEqual(result['ptx_sha256'], cuda.execute(Driver())['ptx_sha256'])
        with self.assertRaisesRegex(RuntimeError, 'compute capability'):
            cuda.execute(Driver(capability=(7, 5)))
        with self.assertRaisesRegex(RuntimeError, 'unreviewed CUDA'):
            cuda.execute(Driver(), (9, 0))

    def test_kernel_result_and_every_owned_resource_are_verified(self):
        driver = Driver(); result = cuda.execute(driver)
        self.assertEqual(result['result'], 42)
        self.assertTrue(result['owned_gpu_resources_released'])
        self.assertEqual(driver.calls[-3:], ['cuModuleUnload', 'cuMemFree_v2', 'cuCtxDestroy_v2'])

    def test_bad_kernel_and_launch_failure_still_release_every_owned_resource(self):
        for driver in (Driver(output=41), Driver(failure='cuLaunchKernel')):
            with self.assertRaises(RuntimeError):cuda.execute(driver)
            self.assertEqual(driver.calls[-3:], ['cuModuleUnload', 'cuMemFree_v2', 'cuCtxDestroy_v2'])

    def test_partial_allocation_and_cleanup_failure_are_not_hidden(self):
        driver = Driver(failure='cuModuleLoadData')
        with self.assertRaisesRegex(RuntimeError, 'cuModuleLoadData'):cuda.execute(driver)
        self.assertEqual(driver.calls[-2:], ['cuMemFree_v2', 'cuCtxDestroy_v2'])
        driver = Driver(failure='cuModuleUnload')
        with self.assertRaisesRegex(RuntimeError, 'cleanup failed'):cuda.execute(driver)
        self.assertEqual(driver.calls[-3:], ['cuModuleUnload', 'cuMemFree_v2', 'cuCtxDestroy_v2'])


if __name__ == '__main__':
    unittest.main()
