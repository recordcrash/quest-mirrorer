from pathlib import Path
from urllib.parse import urlparse
import mimetypes
import os
import re
import requests
import discord

image_exts = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff"}
video_exts = {".mp4", ".webm", ".mov", ".m4v", ".ogv", ".ogg", ".avi", ".mkv"}


def _load_shill_words() -> list[str]:
    raw = os.getenv("SHILLWORDS", "")
    if not raw:
        return []
    return [w.strip() for w in raw.split(",") if w.strip()]


_SHILL_WORDS = _load_shill_words()


def _filter_shill_words(text: str) -> str:
    if not text or not _SHILL_WORDS:
        return text
    t = text
    for w in _SHILL_WORDS:
        t = re.sub(re.escape(w), "", t, flags=re.IGNORECASE)
    return t


_END_UPDATE_BRACKET_RE = re.compile(
    r"^\[\s*(?=[^\]]*\bend\b)(?=[^\]]*\bupdate(?:s)?\b)[^\]]*\]\s*$",
    re.IGNORECASE,
)


def is_image_attachment(att: discord.Attachment) -> bool:
    ct = (att.content_type or "").lower()
    if ct.startswith("image/"):
        return True
    name = (att.filename or "").lower()
    return any(name.endswith(ext) for ext in image_exts)


def is_video_attachment(att: discord.Attachment) -> bool:
    ct = (att.content_type or "").lower()
    if ct.startswith("video/"):
        return True
    name = (att.filename or "").lower()
    return any(name.endswith(ext) for ext in video_exts)


def guess_ext(url: str, content_type: str | None) -> str:
    path = urlparse(url).path or ""
    ext = Path(path).suffix.lower()
    if ext in image_exts or ext in video_exts:
        return ext
    if content_type:
        ext2 = mimetypes.guess_extension(content_type.split(";")[0].strip())
        if ext2:
            return ".jpg" if ext2 == ".jpe" else ext2
    return ".bin"


def download_image(url: str, dest: Path, max_mb: float) -> bool:
    if urlparse(url).scheme not in {"http", "https"}:
        return False
    try:
        with requests.get(url, stream=True, timeout=20) as r:
            r.raise_for_status()
            ext = guess_ext(url, r.headers.get("Content-Type"))
            dest = dest.with_suffix(ext)
            limit_bytes = int(max_mb * 1024 * 1024)
            written = 0
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=131072):
                    if not chunk:
                        continue
                    written += len(chunk)
                    if written > limit_bytes:
                        try:
                            f.close()
                            dest.unlink(missing_ok=True)
                        except Exception:
                            pass
                        print(f"image too large, skipped: {url}")
                        return False
                    f.write(chunk)
            return True
    except Exception as e:
        print(f"image download failed: {url} ({e})")
        return False


def clean_page_images(out_dir: Path, page_number: int) -> None:
    prefix = f"page{page_number}_"
    for p in out_dir.glob(f"{prefix}*"):
        try:
            p.unlink()
        except Exception:
            pass


def rewrite_images_to_local(
    *, out_dir: Path, page_number: int, urls: list[str], max_image_mb: float
) -> list[str]:
    clean_page_images(out_dir, page_number)
    local_names: list[str] = []
    for idx, url in enumerate(urls, start=1):
        if urlparse(url).scheme not in {"http", "https"}:
            continue
        base_name = f"page{page_number}_{idx}"
        dest = out_dir / base_name
        ok = download_image(url, dest, max_image_mb)
        if ok:
            saved = next(out_dir.glob(base_name + ".*"), None)
            if saved:
                local_names.append(saved.name)
    return local_names


def normalize_paragraphs(text: str) -> list[str]:
    if not text:
        return []
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = []
    buf = []
    for line in t.split("\n"):
        s = line.strip()
        if s == "~" or s == "":
            if buf:
                blocks.append(" ".join(buf).strip())
                buf = []
        elif s.startswith(">"):
            continue
        else:
            buf.append(s)
    if buf:
        blocks.append(" ".join(buf).strip())
    return [b for b in blocks if b and not _END_UPDATE_BRACKET_RE.match(b)]


def parse_pages_from_messages(messages: list[discord.Message]) -> list[dict]:
    pages: list[dict] = []
    current = {
        "images": [],
        "videos": [],
        "paragraphs": [],
        "command_text": None,
        "last_ts": None,
    }

    def start_new():
        nonlocal current
        pages.append(current)
        current = {
            "images": [],
            "videos": [],
            "paragraphs": [],
            "command_text": None,
            "last_ts": None,
        }

    for m in messages:
        if m.attachments:
            for att in m.attachments:
                if is_image_attachment(att):
                    if current["command_text"] and (
                        current["images"] or current["videos"] or current["paragraphs"]
                    ):
                        start_new()
                    current["images"].append(att.url)
                    current["last_ts"] = m.created_at
                elif is_video_attachment(att):
                    if current["command_text"] and (
                        current["images"] or current["videos"] or current["paragraphs"]
                    ):
                        start_new()
                    current["videos"].append(att.url)
                    current["last_ts"] = m.created_at

        if m.embeds:
            for e in m.embeds:
                u_img = getattr(getattr(e, "image", None), "url", None)
                u_th = getattr(getattr(e, "thumbnail", None), "url", None)
                u_vid = getattr(getattr(e, "video", None), "url", None)
                for u in (u_img, u_th):
                    if u:
                        if current["command_text"] and (
                            current["images"]
                            or current["videos"]
                            or current["paragraphs"]
                        ):
                            start_new()
                        current["images"].append(u)
                        current["last_ts"] = m.created_at
                if u_vid:
                    if current["command_text"] and (
                        current["images"] or current["videos"] or current["paragraphs"]
                    ):
                        start_new()
                    current["videos"].append(u_vid)
                    current["last_ts"] = m.created_at

        raw_text = m.content or ""
        if raw_text:
            t = _filter_shill_words(raw_text).strip()

            cmd = None
            for raw_line in t.replace("\r\n", "\n").split("\n"):
                s = raw_line.strip()
                if s.startswith(">") and len(s) > 1:
                    cmd = s[1:].strip()
            if cmd is not None:
                if current["command_text"] and (
                    current["images"] or current["videos"] or current["paragraphs"]
                ):
                    start_new()
                current["command_text"] = cmd

            paras = normalize_paragraphs(t)
            if paras:
                if current["command_text"] and (
                    current["images"] or current["videos"] or current["paragraphs"]
                ):
                    start_new()
                current["paragraphs"].extend(paras)
                current["last_ts"] = m.created_at

    if (
        current["images"]
        or current["videos"]
        or current["paragraphs"]
        or current["command_text"]
    ):
        pages.append(current)

    return pages
