#!/usr/bin/env python3
"""Load embedded DLSS-NR CUDA ELFs through the driver without launching them.

This is a read-only compatibility/load test.  It creates a private CUDA
context, loads the embedded ELF bytes directly from memory, resolves the
exported device functions, queries function attributes, and then unloads the
modules.  No game process or NGX runtime is touched.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
from pathlib import Path
from typing import Any


ELF_MAGIC = b"\x7fELF"
CUDA_SUCCESS = 0

CU_FUNC_ATTRIBUTE_MAX_THREADS_PER_BLOCK = 0
CU_FUNC_ATTRIBUTE_SHARED_SIZE_BYTES = 1
CU_FUNC_ATTRIBUTE_CONST_SIZE_BYTES = 2
CU_FUNC_ATTRIBUTE_LOCAL_SIZE_BYTES = 3
CU_FUNC_ATTRIBUTE_NUM_REGS = 4
CU_FUNC_ATTRIBUTE_PTX_VERSION = 5
CU_FUNC_ATTRIBUTE_BINARY_VERSION = 6
CU_FUNC_ATTRIBUTE_CACHE_MODE_CA = 7
CU_FUNC_ATTRIBUTE_MAX_DYNAMIC_SHARED_SIZE_BYTES = 8
CU_FUNC_ATTRIBUTE_PREFERRED_SHARED_MEMORY_CARVEOUT = 9


def find_offsets(data: bytes, needle: bytes) -> list[int]:
    offsets: list[int] = []
    start = 0
    while True:
        offset = data.find(needle, start)
        if offset < 0:
            return offsets
        offsets.append(offset)
        start = offset + 1


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def bind_function(library: Any, name: str, restype: Any, argtypes: list[Any]) -> Any:
    function = getattr(library, name, None)
    if function is None:
        raise RuntimeError(f"nvcuda.dll does not export {name}")
    function.restype = restype
    function.argtypes = argtypes
    return function


def driver_error_name(get_error_name: Any, code: int) -> str:
    name_pointer = ctypes.c_char_p()
    result = get_error_name(code, ctypes.byref(name_pointer))
    if result != CUDA_SUCCESS or not name_pointer.value:
        return f"CUDA_ERROR_{code}"
    return name_pointer.value.decode("ascii", errors="replace")


def driver_error_string(get_error_string: Any, code: int) -> str:
    string_pointer = ctypes.c_char_p()
    result = get_error_string(code, ctypes.byref(string_pointer))
    if result != CUDA_SUCCESS or not string_pointer.value:
        return ""
    return string_pointer.value.decode("utf-8", errors="replace")


def check(
    code: int,
    operation: str,
    get_error_name: Any,
    get_error_string: Any,
) -> None:
    if code != CUDA_SUCCESS:
        raise RuntimeError(
            f"{operation}: {driver_error_name(get_error_name, code)} "
            f"({code}) {driver_error_string(get_error_string, code)}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dll", required=True, type=Path)
    parser.add_argument("--disassembly-summary", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--indices", default="0,1,2,3,4,5")
    args = parser.parse_args()

    dll = args.dll.resolve()
    data = dll.read_bytes()
    offsets = find_offsets(data, ELF_MAGIC)
    disassembly = json.loads(args.disassembly_summary.resolve().read_text(encoding="utf-8"))
    by_index = {int(item["index"]): item for item in disassembly.get("summaries", [])}
    requested = [int(value) for value in args.indices.split(",") if value.strip()]

    report: dict[str, Any] = {
        "analysis": {
            "tool": "test_embedded_cuda_module_load.py",
            "mode": "CUDA driver module/function load and attribute query; no kernel launch",
            "game_or_ngx_touched": False,
        },
        "file": {"path": str(dll), "size": len(data), "sha256": sha256_file(dll)},
        "gpu_context": {},
        "modules": [],
    }

    try:
        cuda = ctypes.WinDLL("nvcuda.dll")
    except OSError as exc:
        report["error"] = f"nvcuda.dll load failed: {exc}"
        args.output.resolve().write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 1

    cu_init = bind_function(cuda, "cuInit", ctypes.c_int, [ctypes.c_uint])
    cu_device_get = bind_function(cuda, "cuDeviceGet", ctypes.c_int, [ctypes.POINTER(ctypes.c_int), ctypes.c_int])
    cu_ctx_create = bind_function(
        cuda,
        "cuCtxCreate_v2",
        ctypes.c_int,
        [ctypes.POINTER(ctypes.c_void_p), ctypes.c_uint, ctypes.c_int],
    )
    cu_ctx_destroy = bind_function(cuda, "cuCtxDestroy_v2", ctypes.c_int, [ctypes.c_void_p])
    cu_module_load_data = bind_function(
        cuda,
        "cuModuleLoadData",
        ctypes.c_int,
        [ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p],
    )
    cu_module_unload = bind_function(cuda, "cuModuleUnload", ctypes.c_int, [ctypes.c_void_p])
    cu_module_get_function = bind_function(
        cuda,
        "cuModuleGetFunction",
        ctypes.c_int,
        [ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.c_char_p],
    )
    cu_func_get_attribute = bind_function(
        cuda,
        "cuFuncGetAttribute",
        ctypes.c_int,
        [ctypes.POINTER(ctypes.c_int), ctypes.c_int, ctypes.c_void_p],
    )
    cu_get_error_name = bind_function(
        cuda,
        "cuGetErrorName",
        ctypes.c_int,
        [ctypes.c_int, ctypes.POINTER(ctypes.c_char_p)],
    )
    cu_get_error_string = bind_function(
        cuda,
        "cuGetErrorString",
        ctypes.c_int,
        [ctypes.c_int, ctypes.POINTER(ctypes.c_char_p)],
    )

    context = ctypes.c_void_p()
    try:
        check(cu_init(0), "cuInit", cu_get_error_name, cu_get_error_string)
        device = ctypes.c_int()
        check(cu_device_get(ctypes.byref(device), 0), "cuDeviceGet", cu_get_error_name, cu_get_error_string)
        check(
            cu_ctx_create(ctypes.byref(context), 0, device.value),
            "cuCtxCreate_v2",
            cu_get_error_name,
            cu_get_error_string,
        )
        report["gpu_context"] = {"device_ordinal": device.value, "context_created": True}

        for index in requested:
            module_record: dict[str, Any] = {
                "index": index,
                "offset": offsets[index] if 0 <= index < len(offsets) else None,
                "module_loaded": False,
                "functions": [],
            }
            if index < 0 or index >= len(offsets):
                module_record["error"] = "ELF index out of range"
                report["modules"].append(module_record)
                continue
            end = offsets[index + 1] if index + 1 < len(offsets) else len(data)
            image = ctypes.create_string_buffer(data[offsets[index] : end])
            module = ctypes.c_void_p()
            load_code = cu_module_load_data(ctypes.byref(module), ctypes.cast(image, ctypes.c_void_p))
            if load_code != CUDA_SUCCESS:
                module_record["load_error"] = {
                    "code": load_code,
                    "name": driver_error_name(cu_get_error_name, load_code),
                    "string": driver_error_string(cu_get_error_string, load_code),
                }
                report["modules"].append(module_record)
                continue
            module_record["module_loaded"] = True
            summary = by_index.get(index, {})
            function_summaries = summary.get("function_summaries", [])
            for function_summary in function_summaries:
                function_name = function_summary.get("name")
                if not isinstance(function_name, str):
                    continue
                function_record: dict[str, Any] = {"name": function_name, "resolved": False}
                function = ctypes.c_void_p()
                function_code = cu_module_get_function(
                    ctypes.byref(function), module, function_name.encode("utf-8")
                )
                if function_code != CUDA_SUCCESS:
                    function_record["error"] = {
                        "code": function_code,
                        "name": driver_error_name(cu_get_error_name, function_code),
                        "string": driver_error_string(cu_get_error_string, function_code),
                    }
                    module_record["functions"].append(function_record)
                    continue
                function_record["resolved"] = True
                attributes: dict[str, int] = {}
                for attribute_name, attribute_id in (
                    ("max_threads_per_block", CU_FUNC_ATTRIBUTE_MAX_THREADS_PER_BLOCK),
                    ("shared_size_bytes", CU_FUNC_ATTRIBUTE_SHARED_SIZE_BYTES),
                    ("const_size_bytes", CU_FUNC_ATTRIBUTE_CONST_SIZE_BYTES),
                    ("local_size_bytes", CU_FUNC_ATTRIBUTE_LOCAL_SIZE_BYTES),
                    ("num_regs", CU_FUNC_ATTRIBUTE_NUM_REGS),
                    ("ptx_version", CU_FUNC_ATTRIBUTE_PTX_VERSION),
                    ("binary_version", CU_FUNC_ATTRIBUTE_BINARY_VERSION),
                    ("cache_mode_ca", CU_FUNC_ATTRIBUTE_CACHE_MODE_CA),
                    ("max_dynamic_shared_size_bytes", CU_FUNC_ATTRIBUTE_MAX_DYNAMIC_SHARED_SIZE_BYTES),
                    ("preferred_shared_memory_carveout", CU_FUNC_ATTRIBUTE_PREFERRED_SHARED_MEMORY_CARVEOUT),
                ):
                    value = ctypes.c_int()
                    attribute_code = cu_func_get_attribute(ctypes.byref(value), attribute_id, function)
                    if attribute_code == CUDA_SUCCESS:
                        attributes[attribute_name] = value.value
                    else:
                        function_record.setdefault("attribute_errors", {})[attribute_name] = {
                            "code": attribute_code,
                            "name": driver_error_name(cu_get_error_name, attribute_code),
                            "string": driver_error_string(cu_get_error_string, attribute_code),
                        }
                function_record["attributes"] = attributes
                module_record["functions"].append(function_record)
            unload_code = cu_module_unload(module)
            module_record["module_unloaded"] = unload_code == CUDA_SUCCESS
            if unload_code != CUDA_SUCCESS:
                module_record["unload_error"] = {
                    "code": unload_code,
                    "name": driver_error_name(cu_get_error_name, unload_code),
                    "string": driver_error_string(cu_get_error_string, unload_code),
                }
            report["modules"].append(module_record)
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if context.value:
            destroy_code = cu_ctx_destroy(context)
            report["gpu_context"]["context_destroyed"] = destroy_code == CUDA_SUCCESS
            if destroy_code != CUDA_SUCCESS:
                report["gpu_context"]["context_destroy_error"] = destroy_code

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "sha256": report["file"]["sha256"],
        "error": report.get("error"),
        "context": report["gpu_context"],
        "modules": [
            {
                "index": item.get("index"),
                "loaded": item.get("module_loaded"),
                "unloaded": item.get("module_unloaded"),
                "functions": len(item.get("functions", [])),
                "resolved": sum(1 for function in item.get("functions", []) if function.get("resolved")),
                "load_error": item.get("load_error"),
            }
            for item in report["modules"]
        ],
    }, indent=2))
    return 0 if "error" not in report else 1


if __name__ == "__main__":
    raise SystemExit(main())
