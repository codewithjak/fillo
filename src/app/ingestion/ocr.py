import asyncio
import base64
import io
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

import pytesseract
from anthropic import AsyncAnthropic
from PIL import Image

from app.config import settings


@dataclass
class OCRResult:
    text: str
    confidence: float | None = None      # 0..1, when the engine provides it


class OCREngine(Protocol):
    async def read_image(self, png: bytes) -> OCRResult: ...


class TesseractEngine:
    """Local and private. Good on clean printed text; weak on handwriting."""

    def __init__(self, lang: str):
        self.lang = lang

    async def read_image(self, png: bytes) -> OCRResult:
        return await asyncio.to_thread(self._run, png)

    def _run(self, png: bytes) -> OCRResult:
        img = Image.open(io.BytesIO(png))
        try:
            text = pytesseract.image_to_string(img, lang=self.lang).strip()
            data = pytesseract.image_to_data(
                img, lang=self.lang, output_type=pytesseract.Output.DICT
            )
        except pytesseract.TesseractNotFoundError as e:
            raise RuntimeError(
                "Tesseract is not installed. Run: sudo apt install tesseract-ocr"
            ) from e

        confs = [
            float(c)
            for w, c in zip(data["text"], data["conf"])
            if w.strip() and float(c) >= 0
        ]
        confidence = sum(confs) / len(confs) / 100 if confs else None
        return OCRResult(text, confidence)


class ClaudeVisionEngine:
    """Reads layout, tables, stamps, and handwriting. Sends page images to the API."""

    MAX_EDGE = 1568

    def __init__(self):
        if not settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is not set (required when OCR_ENGINE=claude)")
        self.client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def read_image(self, png: bytes) -> OCRResult:
        png = await asyncio.to_thread(self._shrink, png)
        msg = await self.client.messages.create(
            model=settings.ocr_model,
            max_tokens=4096,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {
                    "type": "base64", "media_type": "image/png",
                    "data": base64.b64encode(png).decode()}},
                {"type": "text", "text": (
                    "Transcribe all text in this image exactly as written. "
                    "Keep the reading order, table rows, stamps and handwriting. "
                    "Write [illegible] for unreadable parts. Output only the text.")},
            ]}],
        )
        text = "".join(b.text for b in msg.content if b.type == "text").strip()
        return OCRResult(text)

    def _shrink(self, png: bytes) -> bytes:
        img = Image.open(io.BytesIO(png))
        if max(img.size) > self.MAX_EDGE:
            img.thumbnail((self.MAX_EDGE, self.MAX_EDGE))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()


@lru_cache
def get_engine() -> OCREngine:
    """Created once and reused for every file."""
    if settings.ocr_engine == "claude":
        return ClaudeVisionEngine()
    return TesseractEngine(settings.ocr_lang)