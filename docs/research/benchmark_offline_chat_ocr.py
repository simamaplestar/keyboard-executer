"""Offline chat-only OCR comparison. Downloads are separate from timed inference.

Use the isolated research venv for download and rapid candidates; use the app's
existing Windows Python for paddle. No GUI input, AI requests, or user config.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import socket
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / 'packaging/build/diagnostics/offline-ocr'
sys.path.insert(0, str(ROOT / 'src'))

MODELS = [
    ('PP-OCRv4', 'cls', 'ch_ppocr_mobile_v2.0_cls_mobile'),
    ('PP-OCRv5', 'det', 'ch_PP-OCRv5_det_mobile'),
    ('PP-OCRv5', 'rec', 'ch_PP-OCRv5_rec_mobile'),
    ('PP-OCRv5', 'rec', 'ch_PP-OCRv5_rec_server'),
    ('PP-OCRv6', 'det', 'multi_PP-OCRv6_det_tiny'),
    ('PP-OCRv6', 'rec', 'multi_PP-OCRv6_rec_tiny'),
    ('PP-OCRv6', 'det', 'multi_PP-OCRv6_det_small'),
    ('PP-OCRv6', 'rec', 'multi_PP-OCRv6_rec_small'),
]


def download():
    import concurrent.futures
    import requests
    import rapidocr
    import yaml
    registry_path = Path(rapidocr.__file__).parent / 'default_models.yaml'
    registry = yaml.safe_load(registry_path.read_text(encoding='utf-8'))
    destination = WORK / 'models'
    destination.mkdir(parents=True, exist_ok=True)

    def fetch(spec):
        version, task, name = spec
        info = registry['onnxruntime'][version][task][name]
        path = destination / Path(info['model_dir']).name
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != info['SHA256']:
            response = requests.get(info['model_dir'], timeout=(20, 120))
            response.raise_for_status()
            content = response.content
            assert hashlib.sha256(content).hexdigest() == info['SHA256'], name
            path.write_bytes(content)
        row = dict(name=name, filename=path.name, bytes=path.stat().st_size,
                   sha256=info['SHA256'], source=info['model_dir'])
        print(json.dumps(row), flush=True)
        return row

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        rows = list(pool.map(fetch, MODELS))
    (WORK / 'models.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')


def disable_network():
    def deny(*args, **kwargs):
        raise RuntimeError('Network disabled during offline OCR benchmark')
    socket.socket.connect = deny
    socket.socket.connect_ex = deny
    socket.create_connection = deny
    os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK'] = 'True'
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['OMP_NUM_THREADS'] = '2'


def build_rapid(candidate):
    from rapidocr import EngineType, ModelType, OCRVersion, RapidOCR
    version = 6 if candidate.startswith('v6') else 5
    model = 'tiny' if 'tiny' in candidate else ('small' if version == 6 else 'mobile')
    rec = 'server' if 'server' in candidate else model
    backend = EngineType.OPENVINO if candidate.endswith('-ov') else EngineType.ONNXRUNTIME
    models = WORK / 'models'
    prefix = '' if version == 6 else 'ch_'
    params = {
        'Global.log_level': 'warning',
        'Global.use_cls': False,
        'Global.text_score': 0.0,
        'Global.width_height_ratio': -1,
        'Global.min_height': 1,
        'Global.min_side_len': 1,
        'Global.max_side_len': 4000,
        'Global.model_root_dir': str(models),
        'EngineConfig.onnxruntime.intra_op_num_threads': 2,
        'EngineConfig.onnxruntime.inter_op_num_threads': 1,
        'EngineConfig.openvino.inference_num_threads': 2,
        'EngineConfig.openvino.num_streams': 1,
        'EngineConfig.openvino.performance_hint': 'LATENCY',
        'Det.engine_type': backend,
        'Rec.engine_type': backend,
        'Det.ocr_version': OCRVersion.PPOCRV6 if version == 6 else OCRVersion.PPOCRV5,
        'Rec.ocr_version': OCRVersion.PPOCRV6 if version == 6 else OCRVersion.PPOCRV5,
        'Det.model_type': ModelType(model),
        'Rec.model_type': ModelType(rec),
        'Det.model_path': str(models / f'{prefix}PP-OCRv{version}_det_{model}.onnx'),
        'Rec.model_path': str(models / f'{prefix}PP-OCRv{version}_rec_{rec}.onnx'),
        'Cls.model_path': str(models / 'ch_ppocr_mobile_v2.0_cls_mobile.onnx'),
        'Det.limit_type': 'min',
        'Det.limit_side_len': 64,
        'Det.box_thresh': .6,
        'Det.unclip_ratio': 1.5,
        'Det.use_dilation': False,
        'Rec.rec_batch_num': 1,
    }
    if version == 5:
        # v6 defaults are not the preprocessing used to train v5.
        params.update({'Det.mean': [.485, .456, .406], 'Det.std': [.229, .224, .225]})
    return RapidOCR(params=params), params


def run(candidate, repeats):
    disable_network()
    import cv2
    import numpy as np
    import psutil
    from keyboard_executor.core.chat_observer import ChatObserver, _group_boxes
    from keyboard_executor.platforms.base import TextBox
    cv2.setNumThreads(1)
    versions = {}
    for name in ('paddleocr', 'paddlepaddle', 'rapidocr', 'onnxruntime', 'openvino'):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            pass
    started = time.perf_counter()
    if candidate == 'paddle':
        from keyboard_executor.platforms.common import ocr_paddle
        model_root = Path.home() / '.paddlex' / 'official_models'
        ocr_paddle._bundled_model_dir = lambda name, base=None: str(model_root / name)
        engine = ocr_paddle.PaddleOcrEngine(cpu_threads=2)
        # Explicitly separate model load from first prediction.
        ocr_paddle._get_engine('ch', 2)
        config = {'threads': 2, 'recognition_batch': 1, 'mkldnn': False}
        read = engine.recognize_chat
    else:
        engine, config = build_rapid(candidate)

        def read(image):
            result = engine(image, use_cls=False)
            if result.boxes is None or result.txts is None:
                return []
            boxes = []
            for polygon, text, score in zip(result.boxes, result.txts, result.scores):
                x, y = polygon.min(axis=0)
                right, bottom = polygon.max(axis=0)
                boxes.append(TextBox(text, int(x), int(y), int(right-x), int(bottom-y), float(score)))
            return boxes
    load_seconds = time.perf_counter() - started
    print(json.dumps({'candidate': candidate, 'phase': 'model_ready',
                      'load_seconds': load_seconds}), flush=True)
    report = {'candidate': candidate, 'python': platform.python_version(),
              'numpy': np.__version__, 'opencv': cv2.__version__, 'packages': versions,
              'load_seconds': load_seconds, 'config': config, 'network_disabled': True,
              'images': []}
    inputs = json.loads((WORK / 'inputs.json').read_text(encoding='utf-8'))
    # Warm one full frame once, then measure repeated calls on preloaded arrays.
    for entry in inputs:
        image = cv2.imread(str(WORK / 'images' / entry['filename']))
        assert image is not None, entry
        measurements, output_hashes = [], []
        for index in range(repeats + 1):
            started = time.perf_counter()
            boxes = read(image)
            seconds = time.perf_counter() - started
            print(json.dumps({'candidate': candidate, 'image': entry['name'],
                              'iteration': index, 'seconds': seconds}), flush=True)
            measurements.append(seconds)
            output_hashes.append(hashlib.sha256(json.dumps([asdict(b) for b in boxes],
                                                          ensure_ascii=False).encode()).hexdigest())
        observer = ChatObserver('測試角色')
        parsed = [asdict(observer._parse(image, row)) for row in _group_boxes(boxes)]
        row = {'name': entry['name'], 'shape': list(image.shape),
               'first_seconds': measurements[0], 'warm_seconds': measurements[1:],
               'median_seconds': statistics.median(measurements[1:]),
               'max_seconds': max(measurements[1:]), 'stable_results': len(set(output_hashes)) == 1,
               'boxes': [asdict(b) for b in boxes], 'parsed': parsed,
               'rss_mb': psutil.Process().memory_info().rss / 1048576}
        report['images'].append(row)
        print(json.dumps({'candidate': candidate, 'image': entry['name'],
                          'median_seconds': row['median_seconds'], 'boxes': len(boxes),
                          'eligible': [r['sender'] for r in parsed if r['eligible']]}), flush=True)
        (WORK / f'{candidate}.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('candidate')
    parser.add_argument('--repeats', type=int, default=3)
    args = parser.parse_args()
    download() if args.candidate == 'download' else run(args.candidate, args.repeats)
