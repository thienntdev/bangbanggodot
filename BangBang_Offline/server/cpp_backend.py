"""Optional, verified C++ accelerators for the live gameplay server.

Immutable rectangle indexes and checkpoint graph construction use C++.
Combat state, event ordering, Decimal damage, actor eligibility, water walls,
checkpoint JSON format and durable writes retain their existing Python rules.
No compilation, downloads or database access occur at import/startup.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.util
import json
import logging
import math
import os
from pathlib import Path
import platform
import struct
import sys
import threading
import weakref


_log = logging.getLogger(__name__)
_directory = Path(__file__).resolve().parent / 'native'
_lock = threading.RLock()
_initialized = False
_library = None
_loaded_library = None
_checkpoint_module = None
_mode = None
_status = {'requested': None, 'active': 'uninitialized', 'abi_version': 1,
           'checkpoint': 'uninitialized',
           'scope': 'map rectangle queries, native nine-cell walking, checkpoint graph construction'}


class NativeGeometryError(RuntimeError):
    pass


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _regular(name):
    path = _directory / name
    if not path.is_file() or path.is_symlink() or path.resolve().parent != _directory.resolve():
        raise NativeGeometryError('Missing or unsafe native file: ' + name)
    return path


def _bind(lib):
    lib.bb_geometry_abi_version.argtypes = []
    lib.bb_geometry_abi_version.restype = ctypes.c_uint32
    lib.bb_geometry_source_sha256.argtypes = []
    lib.bb_geometry_source_sha256.restype = ctypes.c_char_p
    lib.bb_geometry_last_error.argtypes = []
    lib.bb_geometry_last_error.restype = ctypes.c_char_p
    lib.bb_geometry_create.argtypes = [ctypes.POINTER(ctypes.c_double), ctypes.c_size_t]
    lib.bb_geometry_create.restype = ctypes.c_uint64
    lib.bb_geometry_destroy.argtypes = [ctypes.c_uint64]
    lib.bb_geometry_destroy.restype = ctypes.c_int
    lib.bb_geometry_contact.argtypes = [ctypes.c_uint64] + [ctypes.c_double] * 5
    lib.bb_geometry_contact.restype = ctypes.c_double
    lib.bb_geometry_live_handles.argtypes = []
    lib.bb_geometry_live_handles.restype = ctypes.c_uint64


def _native_error(lib, operation):
    detail = lib.bb_geometry_last_error()
    return NativeGeometryError(operation + ': ' + (detail.decode('utf-8', 'replace') if detail else 'unknown error'))


def _self_test(lib):
    """Reject wrong ABI/FP behavior before accepting any game requests."""
    before = lib.bb_geometry_live_handles()
    data = (ctypes.c_double * 8)(0, 0, 24, 24, 80, 40, 100, 60)
    handle = lib.bb_geometry_create(data, 2)
    if not handle:
        raise _native_error(lib, 'startup create')
    try:
        cases = [
            ((-10, 12, 50, 12, 0), 10 / 60),
            ((50, 12, -10, 12, 0), 26 / 60),
            ((12, 12, 12, 12, 0), 0.0),
            ((-1, -1, -1, -1, 0), -1.0),
            ((-1, -1, -1, -1, 1), 0.0),
            ((-10, 24, 50, 24, 0), 10 / 60),
            ((0, -0.0, 0, -0.0, 0), 0.0),
            ((25, 25, 25, 25, .999), -1.0),
        ]
        for args, expected in cases:
            actual = lib.bb_geometry_contact(handle, *args)
            if struct.pack('<d', actual) != struct.pack('<d', expected):
                raise NativeGeometryError('Native startup geometry/FP self-test failed')
    finally:
        if lib.bb_geometry_destroy(handle) != 1:
            raise _native_error(lib, 'startup destroy')
    if lib.bb_geometry_live_handles() != before:
        raise NativeGeometryError('Native startup handle leak')


def _load_checkpoint(manifest, system):
    if platform.python_implementation() != 'CPython' or sys.version_info < (3, 10):
        raise NativeGeometryError('Native checkpoint builder requires CPython 3.10 or newer')
    source = _regular('checkpoint.cpp')
    digest = _sha(source)
    info = manifest.get('checkpoint', {})
    if (info.get('abi_version') != 1 or info.get('source') != 'checkpoint.cpp'
            or info.get('source_sha256') != digest):
        raise NativeGeometryError('Native checkpoint source/build manifest mismatch')
    name = '_bb_checkpoint.pyd' if system == 'windows' else '_bb_checkpoint.abi3.so'
    entry = info.get('binaries', {}).get(system + '-x86_64', {})
    if entry.get('filename') != name:
        raise NativeGeometryError('Missing native checkpoint build for ' + system)
    binary = _regular(name)
    binary_digest = _sha(binary)
    if entry.get('sha256') != binary_digest:
        raise NativeGeometryError('Native checkpoint binary hash mismatch')
    spec = importlib.util.spec_from_file_location('_bb_checkpoint', binary)
    if spec is None or spec.loader is None:
        raise NativeGeometryError('Cannot load native checkpoint module')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if module.abi_version() != 1 or module.source_sha256() != digest:
        raise NativeGeometryError('Native checkpoint ABI/source fingerprint mismatch')
    from dataclasses import asdict
    from decimal import Decimal
    # The actual combat Shield is passed by each encoder call. Startup also
    # checks identities/cycles and exact graph order without importing combat.
    class NoShield:
        pass
    shared = [Decimal('1.250'), True, None, -0.0]
    value = {'a': shared, 'b': shared}
    graph = module.encode_graph(value, Decimal, NoShield, asdict)
    expected = {'root': {'ref': 0}, 'nodes': [
        ('dict', [('a', {'ref': 1}), ('b', {'ref': 1})]),
        ('list', [{'decimal': '1.250'}, True, None, -0.0])
    ]}
    options = dict(separators=(',', ':'), ensure_ascii=False)
    if json.dumps(graph, **options) != json.dumps(expected, **options):
        raise NativeGeometryError('Native checkpoint startup graph self-test failed')
    cycle = []
    cycle.append(cycle)
    try:
        graph = module.encode_graph(cycle, Decimal, NoShield, asdict)
        if graph != {'root': {'ref': 0}, 'nodes': [('list', [{'ref': 0}])]}:
            raise NativeGeometryError('Native checkpoint startup cycle self-test failed')
    finally:
        cycle.clear()
    _status.update(checkpoint='cpp', checkpoint_source_sha256=digest,
                   checkpoint_binary_sha256=binary_digest, checkpoint_startup_self_test='passed')
    return module


def initialize():
    """Select once per process. Explicit cpp never silently falls back."""
    global _initialized, _library, _loaded_library, _checkpoint_module, _mode, _status
    with _lock:
        if _initialized:
            return status()
        _mode = os.environ.get('BB_ACCELERATION', 'auto').strip().lower()
        if _mode not in ('auto', 'python', 'cpp'):
            raise ValueError('BB_ACCELERATION must be auto, python or cpp')
        _status.update(requested=_mode, active='python', checkpoint='python')
        if _mode == 'python':
            _initialized = True
            _status['reason'] = 'Explicit Python backend'
            return status()
        try:
            machine = platform.machine().lower()
            if machine not in ('amd64', 'x86_64') or ctypes.sizeof(ctypes.c_void_p) != 8:
                raise NativeGeometryError('Bundled backend requires x64 Python')
            system = platform.system().lower()
            if system not in ('linux', 'windows'):
                raise NativeGeometryError('No bundled backend for this operating system')
            name = 'bb_geometry.dll' if system == 'windows' else 'libbb_geometry.so'
            source = _regular('geometry.cpp')
            manifest = json.loads(_regular('build_manifest.json').read_text('utf-8'))
            digest = _sha(source)
            if (manifest.get('schema') != 1 or manifest.get('abi_version') != 1
                    or manifest.get('source') != 'geometry.cpp'
                    or manifest.get('source_sha256') != digest):
                raise NativeGeometryError('Native source/build manifest mismatch; rebuild explicitly')
            entry = manifest.get('binaries', {}).get(system + '-x86_64', {})
            if entry.get('filename') != name:
                raise NativeGeometryError('Missing native build for ' + system + '-x86_64')
            binary = _regular(name)
            binary_digest = _sha(binary)
            if entry.get('sha256') != binary_digest:
                raise NativeGeometryError('Native binary hash mismatch; rebuild explicitly')
            lib = ctypes.CDLL(str(binary))
            _bind(lib)
            compiled_source = lib.bb_geometry_source_sha256()
            if lib.bb_geometry_abi_version() != 1 or compiled_source != digest.encode('ascii'):
                raise NativeGeometryError('Native ABI/embedded source fingerprint mismatch')
            _self_test(lib)
            try:
                _checkpoint_module = _load_checkpoint(manifest, system)
            except (OSError, ImportError, ValueError, TypeError, AttributeError, NativeGeometryError) as exc:
                _status['checkpoint_reason'] = str(exc)
                if _mode == 'cpp':
                    raise NativeGeometryError('Required native checkpoint builder unavailable: ' + str(exc)) from exc
                _log.warning('[combat] Native checkpoint builder unavailable, using Python: %s', exc)
            _library = lib
            _loaded_library = lib
            _status.update(active='cpp', source_sha256=digest, binary_sha256=binary_digest,
                           platform=system + '-x86_64', startup_self_test='passed')
            _status.pop('reason', None)
        except (OSError, ValueError, TypeError, KeyError, AttributeError, NativeGeometryError) as exc:
            _status.update(active='python', reason=str(exc))
            if _mode == 'cpp':
                raise NativeGeometryError('Required C++ gameplay backend unavailable: ' + str(exc)) from exc
            _log.warning('[combat] C++ unavailable, using Python: %s', exc)
        else:
            _log.warning('[combat] C++ map backend active; checkpoint=%s (ABI 1, startup checks passed)', _status['checkpoint'])
        _initialized = True
        return status()


def status():
    """No database/user data or local path is exposed in health output."""
    return dict(_status)


def encode_checkpoint_graph(value, decimal_type, shield_type, asdict):
    """Build the SAME VERSION1 graph; JSON encoding/durable writes unchanged."""
    global _checkpoint_module
    if not _initialized:
        initialize()
    module = _checkpoint_module
    if module is None:
        return NotImplemented
    try:
        return module.encode_graph(value, decimal_type, shield_type, asdict)
    except Exception as exc:
        if _mode == 'cpp':
            raise
        _checkpoint_module = None
        reason = ('Native checkpoint encoder raised ' + type(exc).__name__
                  + '; current error propagated, future calls use Python')
        _status.update(checkpoint='python', checkpoint_reason=reason)
        _log.warning('[combat] %s', reason)
        # A custom iterator/asdict callback may already have been evaluated.
        # Retrying this same input could duplicate side effects or hide a data
        # error. Preserve the current failure exactly; fallback is only used
        # when the caller subsequently requests another checkpoint.
        raise


def _runtime_failure(exc):
    global _library
    if _mode == 'cpp':
        raise exc
    with _lock:
        if _status['active'] == 'cpp':
            _status.update(active='python', reason=str(exc))
            _log.warning('[combat] Native query failed; remaining queries use Python: %s', exc)
        _library = None


def _supported(values):
    # Game coordinates are small int/float values. Other numeric types and
    # extreme diagnostic inputs retain Python's original arithmetic/errors.
    return all(type(v) in (int, float) and abs(v) <= 1e8 and math.isfinite(v) for v in values)


class RectangleIndex:
    """A derived, immutable generation; never serialized in a checkpoint."""
    def __init__(self, lib, rectangles):
        flat = [value for rect in rectangles for value in rect]
        data = (ctypes.c_double * len(flat))(*flat)
        handle = lib.bb_geometry_create(data, len(rectangles))
        if not handle:
            raise _native_error(lib, 'create map index')
        self._library = lib
        self._handle = handle
        self._contact = lib.bb_geometry_contact
        self._finalizer = weakref.finalize(self, lib.bb_geometry_destroy, handle)

    def contact(self, start, end, padding=0):
        if _status['active'] != 'cpp':
            return NotImplemented
        args = (*start, *end, padding)
        if len(args) != 5 or not _supported(args) or padding < 0:
            return NotImplemented
        result = self._contact(self._handle, *args)
        if math.isnan(result):
            _runtime_failure(_native_error(self._library, 'map contact'))
            return NotImplemented
        return None if result == -1.0 else result


def create_index(rectangles):
    initialize()
    lib = _library
    if lib is None:
        return None
    rectangles = tuple(rectangles)
    if any(len(rect) != 4 or not _supported(rect)
           or rect[0] > rect[2] or rect[1] > rect[3] for rect in rectangles):
        return None
    try:
        return RectangleIndex(lib, rectangles)
    except (NativeGeometryError, MemoryError, OverflowError) as exc:
        _runtime_failure(exc)
        return None


def live_handles():
    """Diagnostics only, not part of the simulation state."""
    return int(_loaded_library.bb_geometry_live_handles()) if _loaded_library is not None else 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-cpp', action='store_true')
    args = parser.parse_args()
    if args.require_cpp:
        os.environ['BB_ACCELERATION'] = 'cpp'
    try:
        print(json.dumps(initialize(), ensure_ascii=False, indent=2))
    except (NativeGeometryError, ValueError) as exc:
        parser.exit(1, str(exc) + '\n')
