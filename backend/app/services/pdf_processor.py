"""PDF validation, text extraction (native text first, OCR fallback per page) and page rendering."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF

from app.core.config import Settings
from app.services import ocr_service


class PdfError(Exception):
    """A document-level failure. `user_message` is safe to show to non-technical users."""

    def __init__(self, code: str, user_message: str):
        super().__init__(user_message)
        self.code = code
        self.user_message = user_message


@dataclass
class PageText:
    page: int
    method: str  # TEXT | OCR
    chars: int
    lines: list[str]
    ocr_confidence: float | None = None

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


@dataclass
class PdfDocument:
    page_count: int
    pages: list[PageText] = field(default_factory=list)

    @property
    def method(self) -> str:
        methods = {p.method for p in self.pages}
        if methods == {"TEXT"}:
            return "TEXT"
        if methods == {"OCR"}:
            return "OCR"
        return "MIXED"

    @property
    def ocr_confidence(self) -> float | None:
        confs = [p.ocr_confidence for p in self.pages if p.ocr_confidence is not None]
        return round(sum(confs) / len(confs), 4) if confs else None

    @property
    def full_text(self) -> str:
        return "\n".join(f"[page {p.page}]\n{p.text}" for p in self.pages)

    @property
    def total_chars(self) -> int:
        return sum(p.chars for p in self.pages)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def group_words_into_lines(words: list[tuple], native: bool = False) -> list[str]:
    """Rebuild visual rows from text boxes (x0, y0, x1, y1, text[, baseline]).

    * native PDF text carries a true baseline (6th element): only text on the same baseline shares a row, which
      keeps side-by-side blocks (vendor block next to the invoice meta block) from being interleaved;
    * OCR boxes have no baseline, so vertical centres are compared.
    A wide horizontal gap becomes a double space so table columns stay distinguishable for the parsers.
    """
    def key(w):
        return w[5] if native else (w[1] + w[3]) / 2

    items = sorted(words, key=key)
    rows: list[list[tuple]] = []
    cur: list[tuple] = []
    cur_y = 0.0
    for w in items:
        h = max(w[3] - w[1], 1.0)
        tol = 1.6 if native else 0.45 * h
        if cur and abs(key(w) - cur_y) > tol:
            rows.append(cur)
            cur = []
        cur_y = key(w) if not cur else (cur_y * len(cur) + key(w)) / (len(cur) + 1)
        cur.append(w)
    if cur:
        rows.append(cur)

    lines: list[str] = []
    for row in rows:
        row.sort(key=lambda w: w[0])
        out = row[0][4]
        for prev, w in zip(row, row[1:]):
            gap = w[0] - prev[2]
            h = max(w[3] - w[1], prev[3] - prev[1], 1.0)
            out += ("  " if gap > 0.9 * h else " ") + w[4]
        line = out.strip()
        if line:
            lines.append(line)
    return lines


def _native_spans(page) -> list[tuple]:
    """Text spans with their baseline. Spans are split on wide internal gaps so columns stay separate."""
    out = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            for sp in line["spans"]:
                text = sp["text"].strip()
                if text:
                    x0, y0, x1, y1 = sp["bbox"]
                    out.append((x0, y0, x1, y1, text, sp["origin"][1]))
    return out


def validate_pdf(path: Path, settings: Settings) -> dict:
    """Step 1: is this a real, readable, unencrypted PDF within limits?"""
    if not path.exists():
        raise PdfError("FILE_MISSING", "The uploaded file could not be found on the server.")
    size = path.stat().st_size
    if size == 0:
        raise PdfError("EMPTY_FILE", "The uploaded file is empty.")
    if size > settings.max_upload_mb * 1024 * 1024:
        raise PdfError("FILE_TOO_LARGE", f"The file is larger than the {settings.max_upload_mb} MB limit.")
    with open(path, "rb") as fh:
        head = fh.read(1024)
    if b"%PDF-" not in head:
        raise PdfError("NOT_A_PDF", "This file is not a PDF document (missing PDF signature).")
    try:
        doc = fitz.open(path)
    except Exception:
        raise PdfError("CORRUPTED_PDF", "The PDF appears to be corrupted and could not be opened.") from None
    try:
        if doc.needs_pass or doc.is_encrypted:
            raise PdfError("ENCRYPTED_PDF", "The PDF is password-protected. Please upload an unlocked copy.")
        pages = doc.page_count
        if pages < 1:
            raise PdfError("NO_PAGES", "The PDF contains no pages.")
        if pages > settings.max_pages:
            raise PdfError("TOO_MANY_PAGES", f"The PDF has {pages} pages; the limit is {settings.max_pages}.")
        # Force a parse of the first page to catch structurally broken files.
        try:
            doc.load_page(0).get_text("words")
        except Exception:
            raise PdfError("CORRUPTED_PDF", "The PDF appears to be corrupted and could not be read.") from None
    finally:
        doc.close()
    return {"pages": pages, "size_bytes": size, "sha256": sha256_file(path), "encrypted": False}


def extract_document(path: Path, settings: Settings) -> PdfDocument:
    """Step 2: native text where available; OCR only for pages without a usable text layer."""
    doc = fitz.open(path)
    result = PdfDocument(page_count=doc.page_count)
    try:
        for i in range(doc.page_count):
            page = doc.load_page(i)
            spans = _native_spans(page)
            chars = sum(len(s[4]) for s in spans)
            if chars >= settings.ocr_min_chars_per_page:
                result.pages.append(PageText(i + 1, "TEXT", chars, group_words_into_lines(spans, native=True)))
                continue
            # No usable text layer: scanned / image-only page -> OCR.
            if not ocr_service.ocr_available():
                raise PdfError(
                    "OCR_UNAVAILABLE",
                    "This looks like a scanned document but the OCR engine is not installed on the server.",
                )
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            try:
                ocr_words, conf = ocr_service.ocr_image(pix.tobytes("png"))
            except Exception:
                raise PdfError("OCR_FAILED", "Text recognition (OCR) failed on a scanned page.") from None
            lines = group_words_into_lines(ocr_words)
            result.pages.append(PageText(i + 1, "OCR", sum(len(w[4]) for w in ocr_words), lines, conf))
    finally:
        doc.close()
    if result.total_chars < settings.ocr_min_chars_per_page:
        raise PdfError("EMPTY_EXTRACTION", "No readable text could be found in this document.")
    return result


def render_page_png(path: Path, page_no: int, zoom: float = 1.5) -> bytes:
    doc = fitz.open(path)
    try:
        if page_no < 1 or page_no > doc.page_count:
            raise PdfError("BAD_PAGE", "Page out of range.")
        pix = doc.load_page(page_no - 1).get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        return pix.tobytes("png")
    finally:
        doc.close()


def safe_filename(name: str) -> str:
    name = Path(name or "invoice.pdf").name
    name = re.sub(r"[^A-Za-z0-9._\- ]", "_", name).strip(" .") or "invoice.pdf"
    return name[:120]
