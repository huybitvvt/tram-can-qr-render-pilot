"""Pinned RapidOCR PP-OCRv6 ONNX CPU adapter with explicit offline models."""

from dataclasses import astuple
from importlib.metadata import version
import hashlib
import json
from pathlib import Path
import time

import cv2
import numpy as np

from .decision import Observation,Reading,decide
from .regions import recognition_variants,red_display_regions
from .parsing import parse_weight


def sha256(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def _create_engine(root: Path, size: str, threads: int, *, paths: dict | None = None):
    import onnxruntime
    onnxruntime.disable_telemetry_events()
    from rapidocr import EngineType,ModelType,OCRVersion,RapidOCR
    if size not in {'small','medium'}:
        raise ValueError('Model size must be small or medium')
    params = {
        'Global.model_root_dir':str(root.resolve()),'Global.use_cls':False,
        'Global.text_score':0.,'Global.log_level':'warning',
        'Global.use_preprocess_img':False,'Global.use_vertical_padding':False,
        'Det.ocr_version':OCRVersion.PPOCRV6,'Rec.ocr_version':OCRVersion.PPOCRV6,
        'Det.model_type':ModelType.SMALL,'Rec.model_type':ModelType(size),
        'Det.engine_type':EngineType.ONNXRUNTIME,'Rec.engine_type':EngineType.ONNXRUNTIME,
        'Det.limit_side_len':960,'Det.limit_type':'max',
        'EngineConfig.onnxruntime.intra_op_num_threads':threads,
        'EngineConfig.onnxruntime.inter_op_num_threads':1,
    }
    if paths:
        params.update({'Det.model_path':str(root/paths['det']['file']),
                       'Rec.model_path':str(root/paths['rec']['file'])})
    return RapidOCR(params=params)


def prepare_models(root: Path, size: str, threads: int = 2) -> dict:
    """Only this explicit setup operation may download model files."""
    root.mkdir(parents=True,exist_ok=True)
    from .download import download
    download(root,'det-small')
    download(root,'rec-'+size)
    supplied = {'det':{'file':'PP-OCRv6_det_small.onnx'},'rec':{'file':f'PP-OCRv6_rec_{size}.onnx'}}
    engine = _create_engine(root,size,threads,paths=supplied)
    image = np.zeros((64,256,3),dtype=np.uint8)
    engine(image,use_det=False,use_cls=False)
    engine(image,use_det=True,use_cls=False)
    paths = {}
    for task,model_size in [('det','small'),('rec',size)]:
        matches = [p for p in root.rglob('*.onnx') if p.name==f'PP-OCRv6_{task}_{model_size}.onnx']
        if len(matches)!=1:
            raise RuntimeError(f'Expected exactly one PP-OCRv6 {task} {model_size} model, got {matches}')
        path = matches[0]
        paths[task] = {'file':str(path.relative_to(root)),'sha256':sha256(path),'bytes':path.stat().st_size}
    info = {'ocr_version':'PP-OCRv6','rec_size':size,'det_size':'small',
            'runtime':'CPUExecutionProvider','rapidocr':version('rapidocr'),
            'onnxruntime':version('onnxruntime'),'models':paths,
            'source':'https://www.modelscope.cn/models/RapidAI/RapidOCR',
            'upstream_license':'Apache-2.0'}
    (root/f'manifest-{size}.json').write_text(json.dumps(info,indent=2),encoding='utf-8')
    return info


class ScaleReader:
    def __init__(self, root: Path, size: str = 'small', *, threads: int = 2, min_confidence: float = .85, decimal_policy: str = 'explicit'):
        if not 0 <= min_confidence <= 1 or threads<1:
            raise ValueError('Invalid confidence or CPU thread count')
        manifest = root/f'manifest-{size}.json'
        if not manifest.is_file():
            raise FileNotFoundError(f'Run download-models --size {size} first. Missing {manifest}')
        self.model_info = json.loads(manifest.read_text(encoding='utf-8'))
        if self.model_info['ocr_version']!='PP-OCRv6' or self.model_info['rec_size']!=size:
            raise ValueError('Model manifest does not match the requested PP-OCRv6 profile')
        sources = json.loads(Path(__file__).with_name('model_sources.json').read_text())['models']
        for task,model in self.model_info['models'].items():
            expected = sources[f'{task}-{size if task=="rec" else "small"}']
            if model['file']!=expected['file'] or model['sha256']!=expected['sha256']:
                raise ValueError('Manifest differs from the pinned upstream model identity')
            path = (root/model['file']).resolve()
            if not path.is_relative_to(root.resolve()) or not path.is_file() or sha256(path)!=model['sha256']:
                raise ValueError(f'Model missing or checksum mismatch: {model["file"]}')
        self.engine = _create_engine(root,size,threads,paths=self.model_info['models'])
        self.min_confidence = min_confidence
        if decimal_policy not in {'explicit','fixed-2'}:
            raise ValueError('Unknown decimal policy')
        self.fixed_digits = decimal_policy=='fixed-2'

    def _recognize(self, crop: np.ndarray, region: tuple | None) -> list[Observation]:
        observations = []
        for name,image in recognition_variants(crop):
            result = self.engine(image,use_det=False,use_cls=False,text_score=0.)
            for text,score in zip(result.txts if result.txts is not None else [],result.scores if result.scores is not None else [],strict=True):
                observations.append(Observation(str(text),float(score),name,region))
        return observations

    def read_crop(self, crop: np.ndarray) -> Reading:
        started = time.perf_counter()
        reading = decide(self._recognize(crop,None),min_confidence=self.min_confidence,fixed_digits=self.fixed_digits)
        reading.elapsed_ms = (time.perf_counter()-started)*1000
        return reading

    def read(self, frame: np.ndarray) -> Reading:
        started = time.perf_counter()
        regions = red_display_regions(frame)
        observations = []
        for region in regions:
            observations.extend(self._recognize(region.crop(frame),astuple(region)))
        reading = decide(observations,min_confidence=self.min_confidence,fixed_digits=self.fixed_digits)
        if not regions:
            reading.reason = 'display-region-not-found'
        reading.elapsed_ms = (time.perf_counter()-started)*1000
        return reading

    def read_text_detector(self, frame: np.ndarray) -> Reading:
        """Let PP-OCRv6 detect text and rectify its perspective before reading."""
        started = time.perf_counter()
        result = self.engine(frame,use_det=True,use_cls=False,text_score=0.)
        candidates = []
        if result.boxes is not None and result.txts is not None:
            for box,text,score in zip(result.boxes,result.txts,result.scores,strict=True):
                if parse_weight(str(text),fixed_digits=self.fixed_digits) is None:
                    continue
                points = np.asarray(box)
                x1,y1 = np.maximum(0,np.floor(points.min(axis=0)).astype(int))
                x2,y2 = np.minimum([frame.shape[1],frame.shape[0]],np.ceil(points.max(axis=0)).astype(int))
                crop = frame[y1:y2,x1:x2]
                if not crop.size:
                    continue
                hsv = cv2.cvtColor(crop,cv2.COLOR_BGR2HSV)
                red = cv2.inRange(hsv,(0,80,100),(16,255,255)) | cv2.inRange(hsv,(164,80,100),(179,255,255))
                if np.mean(red>0)<.025:
                    continue
                candidates.append(Observation(str(text),float(score),'ppocrv6-text-det',(int(x1),int(y1),int(x2),int(y2))))
        top = []
        for item in candidates:
            x1,y1,x2,y2 = item.region
            w,h = x2-x1,y2-y1
            below = any(other is not item and .5 <= (other.region[2]-other.region[0])/w <= 2
                and abs((other.region[0]+other.region[2]-x1-x2)/2)<w*.35
                and h*.35 < y1-other.region[1] < h*3.5 for other in candidates)
            if not below:
                top.append(item)
        reading = decide(top,min_confidence=self.min_confidence,fixed_digits=self.fixed_digits)
        reading.elapsed_ms = (time.perf_counter()-started)*1000
        return reading
