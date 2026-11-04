import asyncio
import sys
from pathlib import Path

from app.ingestion.readers import read_document


async def main(files: list[str]) -> None:
    for f in files:
        path = Path(f)
        try:
            pages = await read_document(path)
        except Exception as e:
            print(f"{path.name:36} FAILED  {type(e).__name__}: {e}")
            continue
        chars = sum(len(p.text) for p in pages)
        methods = ",".join(sorted({p.method for p in pages}))
        confs = [p.confidence for p in pages if p.confidence is not None]
        conf = f"{sum(confs) / len(confs):.2f}" if confs else "-"
        preview = " ".join(pages[0].text.split())[:70] if pages else ""
        print(f"{path.name:36} pages={len(pages):<3} {methods:<10} chars={chars:<6} conf={conf:<5} {preview!r}")


asyncio.run(main(sys.argv[1:]))