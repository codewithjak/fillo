from pathlib import Path

SUPPORTED = {".pdf", ".jpg", ".jpeg", ".png", ".heic", ".docx", ".txt",
             ".mp3", ".m4a", ".wav", ".ogg"}

def scan_folder(root: Path) -> list[dict]:
    files = []
    for p in sorted(root.rglob("*")):
        try:
            rel = p.relative_to(root)
            if p.is_symlink() or not p.is_file():
                continue
            if any(part.startswith(".") for part in rel.parts):
                continue
            st = p.stat()
        except OSError:
            continue
        ext = p.suffix.lower()
        files.append({
            "name": p.name,
            "path": str(p),
            "rel_path": str(rel),
            "ext": ext,
            "size": st.st_size,
            "mtime": st.st_mtime,
            "status": "pending" if ext in SUPPORTED else "skipped",
        })
    return files