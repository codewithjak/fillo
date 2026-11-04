import asyncio
import io
from dataclasses import dataclass
from pathlib import Path

import pymupdf
from docx import Document
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener

from app.ingestion.ocr import get_engine

register_heif_opener()                 # lets Pillow open .heic photos

MIN_TEXT_CHARS = 30                    # fewer characters than this → treat the PDF page as scanned
MAX_PDF_PAGES = 100                    # refuse very long PDFs instead of running hundreds of OCR calls
MAX_IMAGE_EDGE = 3000                  # downscale huge photos so OCR stays fast
PDF_RENDER_DPI = 300

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heic"}


@dataclass
class PageContent:
    page: int
    text: str
    method: str                        # "text-layer" | "ocr" | "docx" | "plain"
    confidence: float | None = None


async def read_document(path: Path) -> list[PageContent]:
    ext = path.suffix.lower()
    if ext == ".pdf":
        return await _read_pdf(path)
    if ext in IMAGE_EXTS:
        return await _read_image(path)
    if ext == ".docx":
        return await asyncio.to_thread(_read_docx, path)
    if ext == ".txt":
        text = await asyncio.to_thread(path.read_text, "utf-8", "replace")
        return [PageContent(1, text.strip(), "plain")]
    raise ValueError(f"No reader for {ext}")


# ---------- PDF ----------
def _pdf_text_layers(path: Path) -> list[str]:
    with pymupdf.open(path) as pdf:
        if pdf.needs_pass:
            raise ValueError("PDF is password protected")
        if pdf.page_count > MAX_PDF_PAGES:
            raise ValueError(f"PDF has {pdf.page_count} pages (limit {MAX_PDF_PAGES})")
        return [page.get_text(sort=True).strip() for page in pdf]


def _render_page(path: Path, index: int, dpi: int = PDF_RENDER_DPI) -> bytes:
    with pymupdf.open(path) as pdf:
        return pdf[index].get_pixmap(dpi=dpi).tobytes("png")


async def _read_pdf(path: Path) -> list[PageContent]:
    engine = get_engine()
    layers = await asyncio.to_thread(_pdf_text_layers, path)
    pages: list[PageContent] = []
    for i, text in enumerate(layers):
        if len(text) >= MIN_TEXT_CHARS:                        # real text: no OCR needed
            pages.append(PageContent(i + 1, text, "text-layer"))
            continue
        png = await asyncio.to_thread(_render_page, path, i)   # scanned page → OCR
        r = await engine.read_image(png)
        pages.append(PageContent(i + 1, r.text, "ocr", r.confidence))
    return pages


# ---------- Images ----------
def _image_to_png(path: Path) -> bytes:
    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")      # fix phone-photo rotation
        if max(img.size) > MAX_IMAGE_EDGE:
            img.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()


async def _read_image(path: Path) -> list[PageContent]:
    png = await asyncio.to_thread(_image_to_png, path)
    r = await get_engine().read_image(png)
    return [PageContent(1, r.text, "ocr", r.confidence)]


# ---------- DOCX ----------
def _read_docx(path: Path) -> list[PageContent]:
    doc = Document(str(path))
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text.strip() for cell in row.cells))
    return [PageContent(1, "\n".join(parts), "docx")]