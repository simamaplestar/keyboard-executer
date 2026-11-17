"""List key entries inside the onefile exe to verify bundled assets."""
import sys
from PyInstaller.archive.readers import CArchiveReader

exe = sys.argv[1]
archive = CArchiveReader(exe)
names = [entry[0] for entry in archive.toc.items()] if hasattr(archive.toc, "items") else list(archive.toc)
flat = [str(n) for n in names]
models = [n for n in flat if "ocr_models" in n]
opencc = [n for n in flat if "opencc" in n.lower()][:5]
old = [n for n in flat if any(k in n.lower() for k in ("paddle", "paddleocr", "paddlex"))]
print("models:", models)
print("opencc (first 5):", opencc)
print("old ocr leftovers:", old)
missing = [m for m in ("PP-OCRv6_det_tiny.onnx", "PP-OCRv6_rec_tiny.onnx",
                       "ch_ppocr_mobile_v2.0_cls_mobile.onnx")
           if not any(m in n for n in models)]
print("missing models:", missing)
sys.exit(1 if missing or old else 0)
