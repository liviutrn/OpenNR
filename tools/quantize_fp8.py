"""Calibrate a fixed-shape student ONNX graph for explicit TensorRT FP8.

Calibration is deliberately training-only.  The resulting ONNX file is an
experimental deployment artifact and must pass TensorRT build, numerical
parity, and native-resource checks before it can replace the FP16 fallback.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import onnx
from onnxruntime.quantization import CalibrationDataReader


class FullEyeReader(CalibrationDataReader):
    def __init__(self, cache: Path, guides: Path, eyes: int, color_size=None):
        self.cache = cache.resolve()
        self.guides_root = guides.resolve()
        meta = json.loads((self.cache / 'complete.json').read_text())
        guide_meta = json.loads((self.guides_root / 'complete.json').read_text())
        if guide_meta['rows_sha256'] != meta['rows_sha256'] or not guide_meta['training_only']:
            raise ValueError('Calibration guide cache must be training-only and match the student cache')
        self.rows = json.loads((self.cache / 'rows.json').read_text())
        self.context = np.load(self.cache / 'context.npy', mmap_mode='r')
        self.row_ids = json.loads((self.guides_root / 'row_ids.json').read_text())
        train = [i for i, row in enumerate(self.rows) if row['split'] == 'train']
        self.guides = {}
        self.guide_locs = {}
        groups = guide_meta.get('groups')
        if groups:
            # Dynamic guide caches keep one array per native input resolution.
            # The row_ids file is the sorted union; each group carries the local
            # row mapping for its own memory-mapped array.
            all_group_ids = []
            for group in groups:
                size = tuple(int(v) for v in group['color_size'])
                group_ids = [int(v) for v in group['row_ids']]
                path = self.guides_root / group['file']
                array = np.load(path, mmap_mode='r')
                if array.shape[0] != len(group_ids):
                    raise ValueError(
                        f'Guide group length mismatch for {path}: '
                        f'{array.shape[0]} != {len(group_ids)}'
                    )
                if size in self.guides:
                    raise ValueError(f'Duplicate guide color size group: {size}')
                self.guides[size] = array
                for local_index, row_index in enumerate(group_ids):
                    if row_index in self.guide_locs:
                        raise ValueError(f'Duplicate guide row mapping: {row_index}')
                    self.guide_locs[row_index] = (size, local_index)
                all_group_ids.extend(group_ids)
            if sorted(all_group_ids) != train:
                raise ValueError('Guide row groups are not the canonical training mapping')
            if sorted(self.row_ids) != train:
                raise ValueError('Guide row mapping is not the canonical training mapping')
        else:
            legacy = self.guides_root / 'guides.npy'
            if not legacy.exists():
                raise FileNotFoundError(
                    f'No grouped guide arrays or legacy guides.npy under {self.guides_root}'
                )
            array = np.load(legacy, mmap_mode='r')
            if self.row_ids != train or array.shape[0] != len(self.row_ids):
                raise ValueError('Guide row mapping is not the canonical training mapping')
            self.guides[None] = array
            self.guide_locs = {row_index: (None, local_index)
                               for local_index, row_index in enumerate(self.row_ids)}

        calibration_pool = train
        if color_size is not None:
            color_size = tuple(int(v) for v in color_size)
            calibration_pool = [
                i for i in train if tuple(int(v) for v in self.rows[i]['color_size']) == color_size
            ]
            if not calibration_pool:
                raise ValueError(
                    f'No training rows match ONNX color size {color_size}; '
                    f'available sizes: {sorted({tuple(r["color_size"]) for r in self.rows if r["split"] == "train"})}'
                )
        if eyes < 1 or eyes > len(calibration_pool):
            raise ValueError(f'Calibration eye count must be in [1,{len(calibration_pool)}]')
        # Evenly spread calibration rows over the training set.  The held-out
        # sequence split and crash-tail exclusions are inherited from rows.json.
        positions = np.linspace(0, len(calibration_pool) - 1, eyes, dtype=np.int64)
        self.indices = [calibration_pool[int(i)] for i in positions]
        self._items = [self._load(i) for i in self.indices]
        self._cursor = 0

    def _load(self, row_index: int):
        row = self.rows[row_index]
        w, h = row['color_size']
        path = Path(row['paths']['input']).with_suffix('.raw.bin')
        if path.stat().st_size != w * h * 4:
            raise ValueError(f'Raw color size changed: {path}')
        rgba = np.memmap(path, mode='r', dtype=np.uint8, shape=(h, w, 4))
        rgb = np.ascontiguousarray(rgba[:, :, :3].transpose(2, 0, 1), dtype=np.float32)[None] / 255.0
        try:
            guide_group, guide_j = self.guide_locs[row_index]
        except KeyError as exc:
            raise ValueError(f'Missing dynamic guide for training row {row_index}') from exc
        guide = np.ascontiguousarray(np.asarray(self.guides[guide_group][guide_j], dtype=np.float32)[None])
        context = np.ascontiguousarray(np.asarray(self.context[row_index], dtype=np.float32)[None])
        return {'rgb': rgb, 'guides': guide, 'context': context}

    def get_next(self):
        if self._cursor >= len(self._items):
            return None
        item = self._items[self._cursor]
        self._cursor += 1
        return item

    def rewind(self):
        self._cursor = 0

    def get_first(self):
        """ModelOpt uses one sample to infer intermediate MatMul shapes."""
        self.rewind()
        item = self.get_next()
        self.rewind()
        return item


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--onnx', type=Path, required=True)
    p.add_argument('--cache', type=Path, required=True)
    p.add_argument('--guides', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--calibration-eyes', type=int, default=16)
    p.add_argument('--method', choices=('max', 'entropy'), default='max')
    p.add_argument('--quantize-add', action='store_true', help='Also quantize residual Add nodes; default protects them in FP16')
    p.add_argument('--matmul-only', action='store_true', help='Quantize only MatMul nodes for a conservative parity control')
    a = p.parse_args()
    for field in ('onnx', 'cache', 'guides'):
        setattr(a, field, getattr(a, field).resolve())
    a.output = a.output.resolve()
    source_sha = hashlib.sha256(a.onnx.read_bytes()).hexdigest()
    model = onnx.load(str(a.onnx), load_external_data=True)
    onnx.checker.check_model(model)
    rgb_dims = model.graph.input[0].type.tensor_type.shape.dim
    if len(rgb_dims) != 4 or not rgb_dims[2].dim_value or not rgb_dims[3].dim_value:
        raise ValueError('FP8 calibration requires a fixed-shape RGB ONNX input')
    onnx_color_size = (int(rgb_dims[3].dim_value), int(rgb_dims[2].dim_value))
    reader = FullEyeReader(a.cache, a.guides, a.calibration_eyes, onnx_color_size)
    from modelopt.onnx.quantization import fp8

    op_types = (['MatMul'] if a.matmul_only else ['Conv', 'MatMul']) + (['Add'] if a.quantize_add else [])
    a.output.parent.mkdir(parents=True, exist_ok=True)
    result = fp8.quantize(
        str(a.onnx),
        calibration_method=a.method,
        calibration_color_size=list(onnx_color_size),
        calibration_data_reader=reader,
        calibration_eps=['cuda:0', 'cpu'],
        op_types_to_quantize=op_types,
        nodes_to_exclude=[],
        high_precision_dtype='fp16',
        log_level='INFO',
    )
    onnx.checker.check_model(result)
    onnx.save(result, str(a.output))
    nodes = [node for node in result.graph.node if node.op_type in ('QuantizeLinear', 'DequantizeLinear')]
    metadata = dict(
        state='calibrated',
        source_onnx=str(a.onnx),
        source_sha256=source_sha,
        output=str(a.output),
        cache=str(a.cache),
        cache_sha256=json.loads((a.cache / 'complete.json').read_text())['rows_sha256'],
        guide_cache=str(a.guides),
        calibration_split='training only',
        calibration_rows=reader.indices,
        calibration_eyes=len(reader.indices),
        calibration_method=a.method,
       quantized_op_types=op_types,
        qdq_nodes=len(nodes),
        quantizer='NVIDIA TensorRT Model Optimizer FP8 ONNX quantizer',
        role='Experimental FP8 artifact; retain the exact FP16 engine as fallback until parity and native runtime gates pass',
    )
    a.output.with_suffix('.json').write_text(json.dumps(metadata, indent=2))
    print(json.dumps(metadata, indent=2), flush=True)


if __name__ == '__main__':
    main()
