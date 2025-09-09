from pathlib import Path
from datetime import timezone
import time
import discord
from jinja2 import Environment, FileSystemLoader, select_autoescape
from zoneinfo import ZoneInfo

BOSTON_TZ = ZoneInfo("America/New_York")


from parsing import (
    parse_pages_from_messages,
    rewrite_images_to_local,
)


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


def title_for_page(i: int, pages: list[dict]) -> str:
    if i == 1:
        return ""
    prev_cmd = pages[i - 2].get("command_text")
    return prev_cmd or ""


def atomic_write(path: Path, data: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(data, encoding="utf-8")
    tmp.replace(path)


def _render_page_html(
    *,
    env: Environment,
    css: str,
    story_title: str,
    page_number: int,
    total_pages: int,
    page: dict,
    pages: list[dict],
    absolute_url: str | None,
    site_name: str,
    log_items: list[dict],
) -> str:
    visible_title = title_for_page(page_number, pages)
    images = page["images"]
    paragraphs = page["paragraphs"]
    command_text = page["command_text"]
    command_href = f"{page_number + 1}.html" if command_text else None
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
    )


async def regenerate_site_from_channel(
    *,
    chan: discord.abc.Messageable,
    out_dir: Path,
    story_title: str,
    history_limit: int,
    max_image_mb: float,
    absolute_url: str | None,
    site_name: str,
) -> int:
    t0 = time.perf_counter()

    print("Fetching history: ", end="", flush=True)
    t_fetch = time.perf_counter()
    msgs = []
    count = 0
    step = 50
    async for m in chan.history(limit=history_limit, oldest_first=True):
        msgs.append(m)
        count += 1
        if count % step == 0:
            print(f"{count}..", end="", flush=True)
    print(f"{count} messages. ({time.perf_counter() - t_fetch:.2f}s)")

    t_parse = time.perf_counter()
    pages = parse_pages_from_messages(msgs)
    total_pages = len(pages)
    print(f"Parsed {total_pages} pages. ({time.perf_counter() - t_parse:.2f}s)")

    tmp = []
    for i, p in enumerate(pages, start=1):
        tmp.append((p.get("last_ts"), i, p))
    tmp.sort(key=lambda t: (t[0], t[1]), reverse=True)

    log_items = []
    for ts, i, p in tmp:
        title = title_for_page(i, pages) or story_title
        date_str = format_short_date(ts)
        log_items.append(
            {
                "num": i,
                "href": f"{i}.html",
                "title": title,
                "date": date_str,
            }
        )

    env = _tpl_env()
    css = _load_css()

    out_dir.mkdir(parents=True, exist_ok=True)

    t_write = time.perf_counter()
    total_images = 0
    if total_pages > 0:
        print("Writing pages: ", end="", flush=True)

    for i, page in enumerate(pages, start=1):
        local_imgs = rewrite_images_to_local(
            out_dir=out_dir,
            page_number=i,
            urls=page["images"],
            max_image_mb=max_image_mb,
        )
        total_images += len(local_imgs)
        if i > 1:
            print(" ", end="", flush=True)
        print(f"{i}*[{len(local_imgs)}i]", end="", flush=True)

        page_for_render = {
            "images": local_imgs,
            "paragraphs": page["paragraphs"],
            "command_text": page["command_text"],
        }
        html_str = _render_page_html(
            env=env,
            css=css,
            story_title=story_title,
            page_number=i,
            total_pages=total_pages,
            page=page_for_render,
            pages=pages,
            absolute_url=absolute_url,
            site_name=site_name,
            log_items=log_items,
        )
        atomic_write(out_dir / f"{i}.html", html_str)

    if total_pages > 0:
        print(f" ({time.perf_counter() - t_write:.2f}s)")

    if pages:
        first = (out_dir / "1.html").read_text(encoding="utf-8")
        atomic_write(out_dir / "index.html", first)

    keep = {f"{i}.html" for i in range(1, total_pages + 1)} | {"index.html"}
    for p in out_dir.glob("*.html"):
        name = p.name
        if name not in keep and name[:-5].isdigit():
            try:
                p.unlink()
            except Exception:
                pass

    print(
        f"Summary: wrote {total_pages} page(s), downloaded {total_images} image(s). "
        f"Total {time.perf_counter() - t0:.2f}s"
    )
    return total_pages
