"""Execute one checked CUDA kernel without a compiler, image build or retained cache."""

import ctypes as C
import hashlib
import os
from pathlib import Path
import socket
import tempfile

from maintenance_coordination import require


# PTX ISA 7.1 introduced the original RTX 3090's sm_86 target.
PTX = b'''.version 7.1
.target sm_86
.address_size 64
.visible .entry increment(.param .u64 output) {
 .reg .b64 %rd<2>;
 .reg .b32 %r<2>;
 ld.param.u64 %rd1, [output];
 ld.global.u32 %r1, [%rd1];
 add.u32 %r1, %r1, 1;
 st.global.u32 [%rd1], %r1;
 ret;
}
'''


def execute(driver, capability=(8, 6)):
    """The caller owns this context, module and four-byte allocation, including failures."""
    def call(name, types, *args):
        function = getattr(driver, name)
        function.argtypes = types; function.restype = C.c_int
        result = function(*args)
        require(result == 0, name + ' failed with CUDA status ' + str(result))
    require(capability in ((8, 6), (7, 5)), 'unreviewed CUDA target')
    ptx = PTX if capability == (8, 6) else PTX.replace(b'.target sm_86', b'.target sm_75')
    pointer, size, integer = C.c_void_p, C.c_size_t, C.c_int
    context, module, device_pointer = pointer(), pointer(), C.c_uint64()
    output = C.c_uint32(41)
    try:
        call('cuInit', [C.c_uint], 0)
        count = integer(); call('cuDeviceGetCount', [C.POINTER(integer)], C.byref(count))
        require(count.value == 1, 'CUDA device count differs')
        device = integer(); call('cuDeviceGet', [C.POINTER(integer), integer], C.byref(device), 0)
        observed_capability = []
        for attribute in (75, 76):
            value = integer()
            call('cuDeviceGetAttribute', [C.POINTER(integer), integer, integer], C.byref(value), attribute, device)
            observed_capability.append(value.value)
        require(observed_capability == list(capability), 'original GPU compute capability differs')
        call('cuCtxCreate_v2', [C.POINTER(pointer), C.c_uint, integer], C.byref(context), 0, device)
        call('cuMemAlloc_v2', [C.POINTER(C.c_uint64), size], C.byref(device_pointer), 4)
        call('cuMemcpyHtoD_v2', [C.c_uint64, pointer, size], device_pointer, C.byref(output), 4)
        text = C.create_string_buffer(ptx)
        call('cuModuleLoadData', [C.POINTER(pointer), pointer], C.byref(module), C.cast(text, pointer))
        kernel = pointer()
        call('cuModuleGetFunction', [C.POINTER(pointer), pointer, C.c_char_p], C.byref(kernel), module, b'increment')
        parameters = (pointer * 1)(C.cast(C.byref(device_pointer), pointer))
        call('cuLaunchKernel', [pointer, *([C.c_uint] * 7), pointer, pointer, pointer],
             kernel, 1, 1, 1, 1, 1, 1, 0, None, C.cast(parameters, pointer), None)
        call('cuCtxSynchronize', [])
        call('cuMemcpyDtoH_v2', [pointer, C.c_uint64, size], C.byref(output), device_pointer, 4)
        require(output.value == 42, 'CUDA kernel result differs')
    finally:
        errors = []
        for name, types, handle in (
                ('cuModuleUnload', [pointer], module), ('cuMemFree_v2', [C.c_uint64], device_pointer),
                ('cuCtxDestroy_v2', [pointer], context)):
            if handle.value:
                try:call(name, types, handle)
                except Exception as error:errors.append(str(error))
        require(not errors, 'CUDA owned resource cleanup failed: ' + '; '.join(errors))
    return {'input': 41, 'result': output.value, 'threads': 1, 'device_bytes': 4,
            'ptx_sha256': hashlib.sha256(ptx).hexdigest(), 'owned_gpu_resources_released': True}


def compute(node='arcanine'):
    profiles = {
        'arcanine': ('d877c676fcc2434f9a169f8dc0594676', (8, 6)),
        'sprigatito': ('e5796c3018b6448eae0c69405926317e', (7, 5)),
    }
    require(node in profiles, 'unreviewed CUDA host')
    machine, capability = profiles[node]
    require(os.geteuid() == 0 and socket.gethostname() == node and
            Path('/etc/machine-id').read_text().strip() == machine,
            'CUDA acceptance target identity differs')
    names = ('CUDA_CACHE_PATH', 'CUDA_CACHE_DISABLE')
    original = {name: os.environ.get(name) for name in names}
    try:
        with tempfile.TemporaryDirectory(prefix='maintenance103-cuda-', dir='/var/tmp') as directory:
            os.environ['CUDA_CACHE_PATH'] = directory; os.environ['CUDA_CACHE_DISABLE'] = '1'
            result = execute(C.CDLL('libcuda.so.1'), capability)
        require(not Path(directory).exists(), 'CUDA native cache cleanup failed')
        return {**result, 'native_scratch_removed': True}
    finally:
        for name, value in original.items():
            if value is None:os.environ.pop(name, None)
            else:os.environ[name] = value
