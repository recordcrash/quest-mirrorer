from pathlib import Path
from urllib.parse import urlparse
import ast
import mimetypes
import os
import re
import requests
import discord

image_exts = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff"}
video_exts = {".mp4", ".webm", ".mov", ".m4v", ".ogv", ".ogg", ".avi", ".mkv"}


def _load_env_list(name: str) -> list[object]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return []
    try:
        value = ast.literal_eval(raw)
    except Exception:
        return [v.strip() for v in raw.split(",") if v.strip()]
    if isinstance(value, dict):
        return list(value.items())
    if isinstance(value, (list, tuple, set)):
        return list(value)
    if isinstance(value, (str, int, float)):
        return [value]
    return []


def _load_shill_replacements() -> list[tuple[str, str]]:
    items = _load_env_list("SHILLWORDS")
    replacements: list[tuple[str, str]] = []
    for item in items:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            src, dst = item
            if isinstance(src, str) and isinstance(dst, str) and src:
                replacements.append((src, dst))
        elif isinstance(item, str) and item:
            replacements.append((item, ""))
    return replacements


def _load_user_ids() -> set[int]:
    raw = os.getenv("USER_IDS", "").strip()
    if not raw:
        return set()
    parts = [p for p in re.split(r"[,\s]+", raw) if p]
    allowed: set[int] = set()
    for part in parts:
        try:
            allowed.add(int(part))
        except (TypeError, ValueError):
            continue
    return allowed


def _filter_shill_words(text: str, replacements: list[tuple[str, str]]) -> str:
    if not text or not replacements:
        return text
    t = text
    for src, dst in replacements:
        if not src:
            continue
        t = re.sub(re.escape(src), dst, t, flags=re.IGNORECASE)
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
    shill_replacements = _load_shill_replacements()
    allowed_user_ids = _load_user_ids()
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
        if allowed_user_ids:
            author_id = getattr(getattr(m, "author", None), "id", None)
            if author_id not in allowed_user_ids:
                continue
        raw_text = m.content or ""
        t = _filter_shill_words(raw_text, shill_replacements).strip() if raw_text else ""

        # Extract command from text first. This prevents a common failure mode where
        # attachments are processed before the command in the same message, which can
        # incorrectly push the command onto the next page (staggering).
        cmd = None
        if t:
            for raw_line in t.replace("\r\n", "\n").split("\n"):
                s = raw_line.strip()
                if s.startswith(">") and len(s) > 1:
                    cmd = s[1:].strip()
                elif s.lower().startswith("==>") and len(s) > 3:
                    cmd = s[3:].strip()

        current_has_content = bool(
            current["images"] or current["videos"] or current["paragraphs"]
        )
        if cmd is not None:
            # Treat a command as an end-of-page marker when it appears after content:
            # attach it to the current page, then start a new page for subsequent content.
            if current_has_content:
                current["command_text"] = cmd
                current["last_ts"] = m.created_at
                start_new()
            else:
                # Command with no content: start a new page only if we already had a
                # command queued (multiple command-only messages in a row).
                if current["command_text"] is not None:
                    start_new()
                current["command_text"] = cmd
                current["last_ts"] = m.created_at

        if t:
            paras = normalize_paragraphs(t)
            if paras:
                current["paragraphs"].extend(paras)
                current["last_ts"] = m.created_at

        # Media belongs to the current page, including when it's in the same message
        # as the command text.
        if m.attachments:
            for att in m.attachments:
                if is_image_attachment(att):
                    current["images"].append(att.url)
                    current["last_ts"] = m.created_at
                elif is_video_attachment(att):
                    current["videos"].append(att.url)
                    current["last_ts"] = m.created_at

        if m.embeds:
            for e in m.embeds:
                u_img = getattr(getattr(e, "image", None), "url", None)
                u_th = getattr(getattr(e, "thumbnail", None), "url", None)
                u_vid = getattr(getattr(e, "video", None), "url", None)
                for u in (u_img, u_th):
                    if u:
                        current["images"].append(u)
                        current["last_ts"] = m.created_at
                if u_vid:
                    current["videos"].append(u_vid)
                    current["last_ts"] = m.created_at

    if (
        current["images"]
        or current["videos"]
        or current["paragraphs"]
        or current["command_text"]
    ):
        pages.append(current)

    return pages
