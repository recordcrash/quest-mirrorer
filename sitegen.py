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
# Manual tuning for known channel quirks
# If the new channel's commands are shifted by one page, you can compensate here.
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
    Ensure the last page from the old channel links forward to the first new page.
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

    images = page["images"]
    videos = page.get("videos") or []
    paragraphs = page["paragraphs"]
    command_text = page.get("command_text")
    if not command_text and page_number > 1:
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
    old_channel_id: int,
    new_channel_id: int,
) -> int:
    # Separate visible channels
    chan_old = next((c for c in chans if getattr(c, "id", None) == old_channel_id), None)
    chan_new = next((c for c in chans if getattr(c, "id", None) == new_channel_id), None)
    if not chan_old and not chan_new:
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

    msgs_old: list[discord.Message] = []
    msgs_new: list[discord.Message] = []
    if chan_old:
        try:
            msgs_old = await _fetch_history(chan_old, "old")
        except Exception as e:
            print(f"Error fetching old channel: {e}")
    if chan_new:
        try:
            msgs_new = await _fetch_history(chan_new, "new")
        except Exception as e:
            print(f"Error fetching new channel: {e}")

    t_parse = time.perf_counter()
    pages_old = parse_pages_from_messages(msgs_old) if msgs_old else []
    pages_new = parse_pages_from_messages(msgs_new) if msgs_new else []
    pages_old = [
        p
        for p in pages_old
        if p.get("images") or p.get("videos") or p.get("paragraphs") or p.get("command_text")
    ]
    pages_new = [
        p
        for p in pages_new
        if p.get("images") or p.get("videos") or p.get("paragraphs") or p.get("command_text")
    ]
    if page_offset > 0 and len(pages_old) > page_offset:
        print(f"Trimming old pages from {len(pages_old)} to {page_offset} to match PAGE_OFFSET")
        pages_old = pages_old[:page_offset]
    print(
        f"Parsed {len(pages_old)} old page(s) and {len(pages_new)} new page(s). "
        f"({time.perf_counter() - t_parse:.2f}s)"
    )

    # Determine numbering
    base_old_count = page_offset if page_offset > 0 else len(pages_old)
    new_start = base_old_count + 1
    overall_total_pages = base_old_count + len(pages_new)

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

    def _process_block(block_pages: list[dict], start_number: int, page_offset_for_titles: int):
        nonlocal total_images_downloaded, total_images_reused, total_videos_downloaded, total_videos_reused
        if not block_pages:
            return
        print("Writing pages: ", end="", flush=True)
        t_write = time.perf_counter()
        for idx, page in enumerate(block_pages, start=start_number):
            cmd = page.get("command_text")
            if not cmd and idx > 1:
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

            if idx > start_number:
                print(" ", end="", flush=True)
            print(f"{idx}*[{len(local_imgs)}i,{len(local_vids)}v]", end="", flush=True)

            page_for_render = {
                "images": local_imgs,
                "videos": local_vids,
                "paragraphs": page["paragraphs"],
                "command_text": cmd,
            }
            processed_pages[idx] = page_for_render

            title = (
                title_for_page(idx, block_pages, page_offset_for_titles)
                or cmd
                or story_title
            )
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
        print(f" ({time.perf_counter() - t_write:.2f}s)")

    _process_block(pages_old, 1, 0)
    _process_block(pages_new, new_start, page_offset or (new_start - 1))

    # Optional manual correction: shift commands on/after a page number.
    if MANUAL_COMMAND_SHIFT == -1 and processed_pages:
        start = max(MANUAL_COMMAND_SHIFT_START_PAGE, new_start)
        for n in range(start, overall_total_pages):
            nxt = processed_pages.get(n + 1, {}).get("command_text")
            if nxt:
                processed_pages[n]["command_text"] = nxt

        # Boundary: set the last old page's command to the first "real" new-section title,
        # so page `new_start` shows that as its top title (MSPA style).
        if pages_new:
            boundary_cmd = processed_pages.get(new_start, {}).get("command_text") or ""
            if not boundary_cmd or boundary_cmd.strip().lower() == "next.":
                for look in range(new_start + 1, min(new_start + 10, overall_total_pages + 1)):
                    c = (processed_pages.get(look, {}).get("command_text") or "").strip()
                    if c and c.lower() != "next.":
                        boundary_cmd = c
                        break
            if boundary_cmd:
                if (new_start - 1) in processed_pages:
                    processed_pages[new_start - 1]["command_text"] = boundary_cmd
                # Don't leave the first new page with the same command as its title.
                if (processed_pages.get(new_start, {}).get("command_text") or "").strip() == boundary_cmd:
                    processed_pages[new_start]["command_text"] = "Next."

    # Rebuild log/feed titles based on previous page command
    ts_by_num: dict[int, datetime | None] = {num: ts for (ts, num, _p, _t) in feed_items}
    rebuilt_log: list[dict] = []
    rebuilt_feed: list[tuple] = []
    for num in sorted(processed_pages.keys()):
        prev_cmd = processed_pages.get(num - 1, {}).get("command_text") if num > 1 else ""
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
            prev_cmd = processed_pages.get(num - 1, {}).get("command_text") if num > 1 else None
            html_str = _render_page_html(
                env=env,
                css=css,
                story_title=story_title,
                page_number=num,
                total_pages=overall_total_pages,
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

        # ensure the boundary page links forward into the new section
        if pages_new:
            _linkify_previous_page(out_dir, new_start - 1)
            _ensure_next_link(out_dir, new_start, new_start + 1 if overall_total_pages >= new_start + 1 else new_start)

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
        pages=pages_new if pages_new else pages_old,
        page_offset=page_offset or (new_start - 1),
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
