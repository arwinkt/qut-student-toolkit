"""Private child-process boundary for optional RapidOCR. PNG stdin, JSON stdout.
No provider/network APIs or model downloads. Uses only installed bundled models.
"""
from io import BytesIO
import json
from pathlib import Path
import sys


def main():
    import rapidocr_onnxruntime as package
    from rapidocr_onnxruntime import RapidOCR
    from PIL import Image
    import numpy as np
    root=Path(package.__file__).resolve().parent/'models'
    models={'det_model_path':root/'ch_PP-OCRv4_det_infer.onnx',
            'rec_model_path':root/'ch_PP-OCRv4_rec_infer.onnx',
            'cls_model_path':root/'ch_ppocr_mobile_v2.0_cls_infer.onnx'}
    if not all(p.is_file() for p in models.values()):
        raise RuntimeError('Bundled local OCR models are missing; refusing to download')
    data=sys.stdin.buffer.read(32*1024*1024+1)
    if len(data)>32*1024*1024:raise ValueError('Image input too large')
    with Image.open(BytesIO(data)) as image:
        if image.width*image.height>8_000_000:raise ValueError('Image pixel budget exceeded')
        array=np.asarray(image.convert('RGB'))[:,:,::-1].copy()
    engine=RapidOCR(**{k:str(v) for k,v in models.items()},intra_op_num_threads=1,inter_op_num_threads=1)
    result,_=engine(array)
    rows=result or []
    value={'text':'\n'.join(str(r[1]) for r in rows),'low_confidence':any(float(r[2])<.8 for r in rows)}
    sys.stdout.buffer.write(json.dumps(value,ensure_ascii=False).encode('utf-8'))


if __name__=='__main__':
    try:main()
    except Exception:
        # Do not dump paths, image contents or provider-like exception text.
        sys.stderr.write('Local OCR worker failed; verify installed dependencies/models.\n')
        raise SystemExit(1)
