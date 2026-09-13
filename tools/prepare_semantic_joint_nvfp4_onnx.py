"""Prepare a candidate ONNX graph with selective NVFP4 weight-only Q/DQ.

This is intentionally narrower than a full activation-NVFP4 export.  It
annotates eligible constant-weight MatMul nodes, uses the installed ModelOpt
NVFP4 exporter to compute block scales and pack FP4 weights, and leaves all
other operations—including the recurrent state path—in the source precision.
The output is a candidate only and must pass TensorRT parsing, numerical
comparison, and temporal/stereo checks before it can be considered for a
renderer backend.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
from pathlib import Path

import numpy as np
import onnx
import onnx_graphsurgeon as gs
from onnx import TensorProto, helper

from modelopt.onnx.export.nvfp4_exporter import NVFP4QuantExporter

from semantic_joint_runtime import sha256_file


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--onnx", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-nodes", type=int, default=0)
    parser.add_argument(
        "--node-regex",
        default="",
        help="Only annotate MatMul node names matching this regex.",
    )
    args = parser.parse_args()

    source = args.onnx.resolve()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    model = onnx.load(str(source), load_external_data=True)
    model = copy.deepcopy(model)
    graph = model.graph
    initializer_map = {item.name: item for item in graph.initializer}
    node_pattern = re.compile(args.node_regex) if args.node_regex else None

    selected: list[dict[str, object]] = []
    original_nodes = list(graph.node)
    for node in original_nodes:
        if node.op_type != "MatMul" or len(node.input) < 2:
            continue
        if node_pattern and not node_pattern.search(node.name):
            continue
        weight = initializer_map.get(node.input[1])
        if weight is None or len(weight.dims) != 2:
            continue
        shape = tuple(int(value) for value in weight.dims)
        if shape[-1] % 16 != 0 or shape[0] % 2 != 0:
            continue
        if args.max_nodes > 0 and len(selected) >= args.max_nodes:
            break

        output_name = f"{weight.name}__nvfp4_dequantized"
        if any(value.name == output_name for value in graph.value_info):
            raise RuntimeError(f"value-info name collision: {output_name}")
        graph.value_info.append(
            helper.make_tensor_value_info(output_name, TensorProto.FLOAT, list(shape))
        )
        qdq = helper.make_node(
            "TRT_FP4QDQ",
            inputs=[weight.name],
            outputs=[output_name],
            name=f"{node.name}__nvfp4_weight_qdq",
            block_size=16,
        )
        node.input[1] = output_name
        node_index = list(graph.node).index(node)
        graph.node.insert(node_index, qdq)
        selected.append(
            {
                "node": node.name,
                "weight": weight.name,
                "shape": list(shape),
                "block_size": 16,
            }
        )

    if not selected:
        raise RuntimeError("no eligible MatMul weights selected")

    # Float4E2M1 and block_size on DequantizeLinear require a recent ONNX
    # operator set. TensorRT 10.13 parses this explicit Q/DQ representation.
    for opset in model.opset_import:
        if opset.domain in ("", "ai.onnx"):
            opset.version = max(opset.version, 23)
            break
    else:
        model.opset_import.append(helper.make_opsetid("", 23))

    model = NVFP4QuantExporter.compute_scales(model)
    model = NVFP4QuantExporter.compress_weights(model)
    model = NVFP4QuantExporter.post_process(model)
    sorted_graph = gs.import_onnx(model)
    sorted_graph.toposort()
    model = gs.export_onnx(sorted_graph)
    onnx.checker.check_model(model, full_check=False)
    onnx.save_model(model, str(output), save_as_external_data=False)

    manifest = {
        "format": "opennr-semantic-joint-selective-nvfp4-weight-only-onnx-v1",
        "source_onnx": str(source),
        "source_onnx_sha256": sha256_file(source),
        "output": str(output),
        "output_sha256": sha256_file(output),
        "selected_nodes": selected,
        "quantization": "NVFP4 FP4E2M1 weights, FP8 block scales, block size 16; activations and I/O unchanged",
        "status": "candidate_only",
    }
    output.with_suffix(".json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2), flush=True)


if __name__ == "__main__":
    main()
