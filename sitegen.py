from pathlib import Path
from datetime import datetime, timezone
import os
import time
import json
import re
from urllib.parse import urlsplit, urlunsplit
import discord
from jinja2 import Environment, FileSystemLoader, select_autoescape
from zoneinfo import ZoneInfo

from parsing import (
    parse_pages_from_messages,
    download_image,
)
from feeds import render_atom

BOSTON_TZ = ZoneInfo("America/New_York")
# Manual tuning for known command quirks
# If commands are shifted by one page, you can compensate here.
# -1 means "pull command_text from the next page".
def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


MANUAL_COMMAND_SHIFT_START_PAGE = _env_int("MANUAL_COMMAND_SHIFT_START_PAGE", 92)
MANUAL_COMMAND_SHIFT = _env_int("MANUAL_COMMAND_SHIFT", 0)


def _tpl_env():
    tpl_dir = Path(__file__).resolve().parent / "templates"
    return Environment(
        loader=FileSystemLoader(str(tpl_dir)),
        autoescape=select_autoescape(enabled_extensions=("html", "j2")),
    )


def _load_css() -> str:
    css_path = Path(__file__).resolve().parent / "templates" / "style.css"
    return css_path.read_text(encoding="utf-8")


def alt_for(url_or_name: str) -> str:
    name = url_or_name.rsplit("/", 1)[-1]
    return name.split("?", 1)[0] or "image"


def format_short_date(dt) -> str:
    if not dt:
        return ""
    return dt.astimezone(BOSTON_TZ).strftime("%m/%d/%y")


def _parse_rfc3339(s: str) -> datetime | None:
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        return None


def title_for_page(page_number: int, pages: list[dict], page_offset: int) -> str:
    rel_idx = page_number - page_offset
    if rel_idx <= 1 or rel_idx > len(pages):
        return ""
    prev_cmd = pages[rel_idx - 2].get("command_text")
    return prev_cmd or ""


def atomic_write(path: Path, data: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(data, encoding="utf-8")
    tmp.replace(path)


def write_if_changed(path: Path, data: str) -> bool:
    try:
        old = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        atomic_write(path, data)
        return True
    if old == data:
        return False
    atomic_write(path, data)
    return True


def _cache_dir(out_dir: Path) -> Path:
    d = out_dir / ".cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _images_cache_path(out_dir: Path) -> Path:
    return _cache_dir(out_dir) / "images.json"


def _videos_cache_path(out_dir: Path) -> Path:
    return _cache_dir(out_dir) / "videos.json"


def _load_cache(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")


def _canonical_media_key(url: str) -> str:
    s = urlsplit(url)
    host = s.netloc.lower()
    if (
        host.endswith("discordapp.net")
        or host.endswith("discordapp.com")
        or host.endswith("discord.com")
    ):
        return urlunsplit((s.scheme, s.netloc, s.path, "", ""))
    return url


def rewrite_images_to_local_cached(
    *,
    out_dir: Path,
    page_number: int,
    urls: list[str],
    max_image_mb: float,
) -> tuple[list[str], int, int]:
    cache = _load_cache(_images_cache_path(out_dir))
    local_names: list[str] = []
    reused = 0
    downloaded = 0
    seen_rels: set[str] = set()

    for idx, url in enumerate(urls, start=1):
        key = _canonical_media_key(url)
        rel = cache.get(key)
        expected_base = f"page{page_number}_{idx}"

        can_reuse = False
        if rel:
            p = out_dir / rel
            if p.exists() and rel not in seen_rels:
                can_reuse = True

        if can_reuse:
            local_names.append(rel)
            seen_rels.add(rel)
            reused += 1
            continue

        dest = out_dir / expected_base
        ok = download_image(url, dest, max_image_mb)
        if ok:
            saved = next(out_dir.glob(expected_base + ".*"), None)
            if saved:
                cache[key] = saved.name
                local_names.append(saved.name)
                seen_rels.add(saved.name)
                downloaded += 1
            else:
                if rel and (out_dir / rel).exists() and rel not in seen_rels:
                    local_names.append(rel)
                    seen_rels.add(rel)
                    reused += 1
        else:
            if rel and (out_dir / rel).exists() and rel not in seen_rels:
                local_names.append(rel)
                seen_rels.add(rel)
                reused += 1

    _save_cache(_images_cache_path(out_dir), cache)
    return local_names, reused, downloaded


def rewrite_videos_to_local_cached(
    *,
    out_dir: Path,
    page_number: int,
    urls: list[str],
    max_image_mb: float,  # reuse same size limit for simplicity
) -> tuple[list[str], int, int]:
    cache = _load_cache(_videos_cache_path(out_dir))
    local_names: list[str] = []
    reused = 0
    downloaded = 0
    seen_rels: set[str] = set()

    for idx, url in enumerate(urls, start=1):
        key = _canonical_media_key(url)
        rel = cache.get(key)
        expected_base = f"page{page_number}_v{idx}"

        can_reuse = False
        if rel:
            p = out_dir / rel
            if p.exists() and rel not in seen_rels:
                can_reuse = True

        if can_reuse:
            local_names.append(rel)
            seen_rels.add(rel)
            reused += 1
            continue

        dest = out_dir / expected_base
        ok = download_image(url, dest, max_image_mb)
        if ok:
            saved = next(out_dir.glob(expected_base + ".*"), None)
            if saved:
                cache[key] = saved.name
                local_names.append(saved.name)
                seen_rels.add(saved.name)
                downloaded += 1
            else:
                if rel and (out_dir / rel).exists() and rel not in seen_rels:
                    local_names.append(rel)
                    seen_rels.add(rel)
                    reused += 1
        else:
            if rel and (out_dir / rel).exists() and rel not in seen_rels:
                local_names.append(rel)
                seen_rels.add(rel)
                reused += 1

    _save_cache(_videos_cache_path(out_dir), cache)
    return local_names, reused, downloaded


def _load_existing_atom(out_dir: Path) -> tuple[list[str], datetime | None, list[dict]]:
    atom_path = out_dir / "atom.xml"
    if not atom_path.exists():
        return [], None, []
    try:
        from xml.etree import ElementTree as ET
    except Exception:
        return [], None, []

    try:
        tree = ET.parse(atom_path)
        root = tree.getroot()
    except Exception:
        return [], None, []

    ns = {"a": "http://www.w3.org/2005/Atom"}
    entries_xml: list[str] = []
    log_items: list[dict] = []

    updated_dt: datetime | None = None
    updated_el = root.find("a:updated", ns)
    if updated_el is not None and updated_el.text:
        updated_dt = _parse_rfc3339(updated_el.text)

    for entry in root.findall("a:entry", ns):
        try:
            entries_xml.append(ET.tostring(entry, encoding="unicode"))
        except Exception:
            pass
        title = entry.findtext("a:title", default="", namespaces=ns) or ""
        link_el = entry.find("a:link", ns)
        href = link_el.get("href") if link_el is not None else ""
        num = None
        m = re.search(r"(\d+)\.html", href)
        if m:
            try:
                num = int(m.group(1))
            except Exception:
                num = None
        entry_updated = _parse_rfc3339(entry.findtext("a:updated", default="", namespaces=ns) or "")
        log_items.append(
            {
                "num": num if num is not None else 0,
                "href": href,
                "title": title,
                "date": format_short_date(entry_updated) if entry_updated else "",
                "ts": entry_updated,
            }
        )

    return entries_xml, updated_dt, log_items


def _linkify_previous_page(out_dir: Path, last_old_page_num: int) -> None:
    """
    Ensure the given page links forward to the next page.
    """
    if last_old_page_num <= 0:
        return
    prev_path = out_dir / f"{last_old_page_num}.html"
    next_href = f"{last_old_page_num + 1}.html"
    if not prev_path.exists():
        return

    try:
        data = prev_path.read_text(encoding="utf-8")
    except Exception:
        return

    changed = False

    # Update an existing command link href
    cmd_link_re = re.compile(
        r'(<div class="commands">[\s\S]*?&gt;\s*<a href=")([^"]*)(">)',
        re.MULTILINE,
    )
    new_data, n = cmd_link_re.subn(r'\g<1>' + next_href + r'\g<3>', data, count=1)
    if n > 0:
        data = new_data
        changed = True
    else:
        # Replace the placeholder with a Next link if there was no command link
        placeholder_re = re.compile(r'(<div class="commands">\s*)(<span class="placeholder"[^>]*>&gt;</span>)', re.MULTILINE)
        new_data, n = placeholder_re.subn(
            rf'\1&gt; <a href="{next_href}">Next</a>',
            data,
            count=1,
        )
        if n > 0:
            data = new_data
            changed = True

    if changed:
        atomic_write(prev_path, data)


def _ensure_next_link(out_dir: Path, page_num: int, next_num: int) -> None:
    """
    Ensure the commands block on the given page links to the provided next page.
    """
    path = out_dir / f"{page_num}.html"
    if not path.exists():
        return
    next_href = f"{next_num}.html"
    try:
        data = path.read_text(encoding="utf-8")
    except Exception:
        return
    block_re = re.compile(r'(<div class="commands">)([\s\S]*?)(</div>)', re.MULTILINE)
    m = block_re.search(data)
    if not m:
        return
    replaced = m.group(1) + "&gt; " + f'<a href="{next_href}">Next</a>' + m.group(3)
    new_data = data[: m.start()] + replaced + data[m.end() :]
    if new_data != data:
        atomic_write(path, new_data)


def _render_page_html(
    *,
    env: Environment,
    css: str,
    story_title: str,
    page_number: int,
    total_pages: int,
    page: dict,
    prev_command_text: str | None,
    absolute_url: str | None,
    site_name: str,
    log_items: list[dict],
) -> str:
    visible_title = prev_command_text or page.get("command_text") or ""
    if page_number == 1:
        visible_title = ""

    images = page["images"]
    videos = page.get("videos") or []
    paragraphs = page["paragraphs"]
    command_text = page.get("command_text")
    if not command_text and page_number > 1 and page_number < total_pages:
        command_text = "Next."
    command_href = None
    if command_text and page_number < total_pages:
        command_href = f"{page_number + 1}.html"
    start_over_href = "1.html"
    go_back_href = f"{page_number - 1}.html" if page_number > 1 else start_over_href
    doc_title = f"{story_title}: {visible_title}" if visible_title else f"{story_title}"
    og_description = (
        paragraphs[0][:180] + ("…" if paragraphs and len(paragraphs[0]) > 180 else "")
        if paragraphs
        else ""
    )
    og_image = images[-1] if images else None

    tmpl = env.get_template("page.html.j2")
    return tmpl.render(
        css=css,
        doc_title=doc_title,
        visible_title=visible_title if visible_title else None,
        story_title=story_title,
        page_number=page_number,
        total_pages=total_pages,
        images=images,
        videos=videos,
        alts=[alt_for(u) for u in images],
        paragraphs=paragraphs,
        command_text=command_text if command_text else None,
        command_href=command_href,
        start_over_href=start_over_href,
        go_back_href=go_back_href,
        og_description=og_description,
        og_image=og_image,
        absolute_url=absolute_url,
        site_name=site_name,
        log_items=log_items,
        atom_href="atom.xml",
        feed_icon="📡",
    )


async def regenerate_site_from_channel(
    *,
    chans: list[discord.abc.Messageable],
    out_dir: Path,
    story_title: str,
    history_limit: int,
    max_image_mb: float,
    absolute_url: str | None,
    site_name: str,
    page_offset: int = 0,
    channel_ids: list[int],
) -> int:
    chan_map = {getattr(c, "id", None): c for c in chans}
    selected = [chan_map.get(cid) for cid in channel_ids if chan_map.get(cid)]
    if not selected:
        print("No visible channels; skipping regen")
        return 0

    t0 = time.perf_counter()

    async def _fetch_history(c: discord.abc.Messageable, label: str) -> list[discord.Message]:
        msgs: list[discord.Message] = []
        count = 0
        step = 50
        print(f"Fetching history [{label}]: ", end="", flush=True)
        t_fetch = time.perf_counter()
        async for m in c.history(limit=history_limit, oldest_first=True):
            msgs.append(m)
            count += 1
            if count % step == 0:
                print(f"{count}..", end="", flush=True)
        print(f"{count} messages. ({time.perf_counter() - t_fetch:.2f}s)")
        return msgs

    all_msgs: list[discord.Message] = []
    for idx, chan in enumerate(selected, start=1):
        label = (
            str(getattr(chan, "id", None))
            if len(selected) > 1
            else "main"
        )
        try:
            msgs = await _fetch_history(chan, label)
            all_msgs.extend(msgs)
        except Exception as e:
            print(f"Error fetching channel {getattr(chan, 'id', None)}: {e}")

    if not all_msgs:
        print("No messages found; skipping regen")
        return 0

    def _msg_key(m: discord.Message):
        ts = getattr(m, "created_at", None)
        if ts is None:
            ts = datetime.min.replace(tzinfo=timezone.utc)
        return (ts, getattr(m, "id", 0))

    all_msgs.sort(key=_msg_key)

    t_parse = time.perf_counter()
    pages = parse_pages_from_messages(all_msgs)
    pages = [
        p
        for p in pages
        if p.get("images") or p.get("videos") or p.get("paragraphs") or p.get("command_text")
    ]
    total_pages = len(pages)
    print(f"Parsed {total_pages} page(s). ({time.perf_counter() - t_parse:.2f}s)")

    env = _tpl_env()
    css = _load_css()
    out_dir.mkdir(parents=True, exist_ok=True)

    total_images_downloaded = 0
    total_images_reused = 0
    total_videos_downloaded = 0
    total_videos_reused = 0
    pages_written = 0
    pages_unchanged = 0

    processed_pages: dict[int, dict] = {}
    log_items: list[dict] = []
    feed_items: list[tuple] = []

    if pages:
        print("Writing pages: ", end="", flush=True)
    t_write = time.perf_counter()
    for idx, page in enumerate(pages, start=1):
        cmd = page.get("command_text")
        if not cmd and idx > 1 and idx < total_pages:
            cmd = "Next."
        local_imgs, img_reused, img_downloaded = rewrite_images_to_local_cached(
            out_dir=out_dir,
            page_number=idx,
            urls=page["images"],
            max_image_mb=max_image_mb,
        )
        local_vids, vid_reused, vid_downloaded = rewrite_videos_to_local_cached(
            out_dir=out_dir,
            page_number=idx,
            urls=page.get("videos") or [],
            max_image_mb=max_image_mb,
        )
        total_images_downloaded += img_downloaded
        total_images_reused += img_reused
        total_videos_downloaded += vid_downloaded
        total_videos_reused += vid_reused

        if idx > 1:
            print(" ", end="", flush=True)
        print(f"{idx}*[{len(local_imgs)}i,{len(local_vids)}v]", end="", flush=True)

        page_for_render = {
            "images": local_imgs,
            "videos": local_vids,
            "paragraphs": page["paragraphs"],
            "command_text": cmd,
        }
        processed_pages[idx] = page_for_render

        title = title_for_page(idx, pages, page_offset) or cmd or story_title
        date_str = format_short_date(page.get("last_ts"))
        log_items.append(
            {
                "num": idx,
                "href": f"{idx}.html",
                "title": title,
                "date": date_str,
                "ts": page.get("last_ts"),
            }
        )
        feed_items.append((page.get("last_ts"), idx, page_for_render, title))
    if pages:
        print(f" ({time.perf_counter() - t_write:.2f}s)")

    # Optional manual correction: shift commands on/after a page number.
    if MANUAL_COMMAND_SHIFT == -1 and processed_pages:
        start = max(MANUAL_COMMAND_SHIFT_START_PAGE, 1)
        for n in range(start, total_pages):
            nxt = processed_pages.get(n + 1, {}).get("command_text")
            if nxt:
                processed_pages[n]["command_text"] = nxt

    original_commands = {num: processed_pages[num].get("command_text") for num in processed_pages}
    first_page_title = story_title
    # Rebuild log/feed titles based on previous page command
    ts_by_num: dict[int, datetime | None] = {num: ts for (ts, num, _p, _t) in feed_items}
    rebuilt_log: list[dict] = []
    rebuilt_feed: list[tuple] = []
    for num in sorted(processed_pages.keys()):
        if num == 1:
            title = first_page_title
        else:
            prev_cmd = original_commands.get(num - 1) or ""
            cur_cmd = processed_pages[num].get("command_text") or ""
            title = prev_cmd or cur_cmd or story_title
        ts = ts_by_num.get(num)
        rebuilt_log.append(
            {
                "num": num,
                "href": f"{num}.html",
                "title": title,
                "date": format_short_date(ts),
                "ts": ts,
            }
        )
        rebuilt_feed.append((ts, num, processed_pages[num], title))

    log_items = rebuilt_log
    feed_items = rebuilt_feed

    # Sort log items newest first by timestamp then page num
    log_items.sort(
        key=lambda item: (
            item.get("ts") or datetime.min.replace(tzinfo=timezone.utc),
            item.get("num") or 0,
        ),
        reverse=True,
    )

    # Render HTML now that full log is built
    if processed_pages:
        all_numbers = sorted(processed_pages.keys())
        for num in all_numbers:
            prev_cmd = original_commands.get(num - 1) if num > 1 else None
            html_str = _render_page_html(
                env=env,
                css=css,
                story_title=story_title,
                page_number=num,
                total_pages=total_pages,
                page=processed_pages[num],
                prev_command_text=prev_cmd,
                absolute_url=absolute_url,
                site_name=site_name,
                log_items=log_items,
            )
            wrote = write_if_changed(out_dir / f"{num}.html", html_str)
            if wrote:
                pages_written += 1
            else:
                pages_unchanged += 1

        first = (out_dir / "1.html").read_text(encoding="utf-8")
        write_if_changed(out_dir / "index.html", first)

    feed_items.sort(
        key=lambda item: (
            item[0] or datetime.min.replace(tzinfo=timezone.utc),
            item[1],
        ),
        reverse=True,
    )

    atom_xml = render_atom(
        story_title=story_title,
        site_name=site_name,
        absolute_url=absolute_url,
        sorted_items=feed_items,
        pages=pages,
        page_offset=page_offset,
        existing_entries=[],
        existing_updated=None,
        limit=None,
    )
    write_if_changed(out_dir / "atom.xml", atom_xml)

    print(
        f"Summary: wrote {pages_written} page(s), {pages_unchanged} unchanged, "
        f"downloaded {total_images_downloaded} image(s), reused {total_images_reused} image(s), "
        f"downloaded {total_videos_downloaded} video(s), reused {total_videos_reused} video(s). "
        f"Total {time.perf_counter() - t0:.2f}s"
    )
    return pages_written
