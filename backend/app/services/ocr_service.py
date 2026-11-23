"""OCR via RapidOCR (ONNX runtime; pure pip install, no system Tesseract needed)."""
from __future__ import annotations

import io
import threading

_engine = None
_lock = threading.Lock()


def ocr_available() -> bool:
    try:
        import rapidocr_onnxruntime  # noqa: F401

        return True
    except Exception:
        return False


def _get_engine():
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR

        _engine = RapidOCR()
    return _engine


def ocr_image(png_bytes: bytes) -> tuple[list[tuple[float, float, float, float, str]], float | None]:
    """Return ([(x0, y0, x1, y1, text)], mean_confidence) for one rendered page image."""
    import numpy as np
    from PIL import Image

    img = np.array(Image.open(io.BytesIO(png_bytes)).convert("RGB"))
    with _lock:
        result, _ = _get_engine()(img, use_cls=False)  # scans are upright; skipping the angle classifier halves the time
    if not result:
        return [], None
    words: list[tuple[float, float, float, float, str]] = []
    scores: list[float] = []
    for box, text, score in result:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        text = str(text).strip()
        if not text:
            continue
        words.append((min(xs), min(ys), max(xs), max(ys), text))
        try:
            scores.append(float(score))
        except (TypeError, ValueError):
            pass
    return words, (sum(scores) / len(scores) if scores else None)
