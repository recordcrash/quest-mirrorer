import re
from datetime import datetime, timezone
from xml.sax.saxutils import escape as xml_escape


def _rfc3339_utc(dt: datetime | None) -> str:
    if not dt:
        dt = datetime.now(tz=timezone.utc)
    d = dt.astimezone(timezone.utc).replace(microsecond=0)
    # RFC 3339 UTC form
    return d.isoformat().replace("+00:00", "Z")


def _title_for_page(i: int, pages: list[dict]) -> str:
    if i == 1:
        return ""
    prev_cmd = pages[i - 2].get("command_text")
    return prev_cmd or ""


def _summary_from_paragraphs(paragraphs: list[str], limit: int = 400) -> str:
    if not paragraphs:
        return ""
    s = " ".join(paragraphs[0].split())
    if len(s) <= limit:
        return s
    cut = s.rfind(".", 0, limit)
    if cut == -1:
        cut = s.rfind(" ", 0, limit)
    if cut == -1:
        cut = limit
    return s[:cut].rstrip() + "..."


def _alt_for(url_or_name: str) -> str:
    # keep it simple and stable
    base = url_or_name.rsplit("/", 1)[-1]
    name = base.split("?", 1)[0]
    return name or "image"


def _slug(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "story"


def _page_link(base: str, page_num: int) -> str:
    href = f"{page_num}.html"
    return f"{base}{href}" if base else href


def _img_src(base: str, name: str) -> str:
    return f"{base}{name}" if base else name


def _entry_xhtml(images: list[str], paragraphs: list[str], base: str) -> str:
    # Build strict XHTML content tree as a string
    parts: list[str] = []
    parts.append('<content type="xhtml">')
    parts.append('<div xmlns="http://www.w3.org/1999/xhtml">')

    if images:
        parts.append('<div class="media">')
        for u in images:
            src = _img_src(base, u)
            alt = _alt_for(u)
            parts.append(f'<img src="{xml_escape(src)}" alt="{xml_escape(alt)}" />')
        parts.append("</div>")

    # paragraphs
    if paragraphs:
        parts.append('<div class="content">')
        for p in paragraphs:
            parts.append(f'<p class="comic-text">{xml_escape(p)}</p>')
        parts.append("</div>")

    parts.append("</div>")
    parts.append("</content>")
    return "".join(parts)


def render_atom(
    *,
    story_title: str,
    site_name: str | None,
    absolute_url: str | None,
    sorted_items: list[tuple],  # (timestamp, page_num, page_dict) newest first
    pages: list[dict],
    limit: int | None = 50,
) -> str:
    """
    Atom 1.0 feed.

    feed: title, id, updated, link rel="self", link rel="alternate", author
    entry: title, id, updated, link, summary, content(xhtml)
    """
    channel_title = f"{story_title} — Adventure Log"
    base = (absolute_url.rstrip("/") + "/") if absolute_url else ""
    site_link = absolute_url or "index.html"
    self_href = f"{base}atom.xml" if base else "atom.xml"

    # stable feed id
    feed_id = absolute_url or f"urn:quest-mirror:{_slug(story_title)}"

    items = sorted_items if limit is None else sorted_items[:limit]

    last_updated: datetime | None = None
    entries_xml: list[str] = []

    for ts, idx, page in items:
        when = ts or datetime.now(tz=timezone.utc)
        if last_updated is None or when > last_updated:
            last_updated = when
        updated = _rfc3339_utc(when)

        link = _page_link(base, idx)
        entry_id = link  # stable perma URL is fine for atom:id

        title = _title_for_page(idx, pages) or story_title
        summary = _summary_from_paragraphs(page.get("paragraphs") or [])

        entry_content = _entry_xhtml(
            page.get("images") or [],
            page.get("paragraphs") or [],
            base,
        )

        entries_xml.append(
            "".join(
                [
                    " <entry>\n",
                    f"  <title>{xml_escape(title)}</title>\n",
                    f"  <id>{xml_escape(entry_id)}</id>\n",
                    f'  <link href="{xml_escape(link)}" />\n',
                    f"  <updated>{xml_escape(updated)}</updated>\n",
                    f'  <summary type="text">{xml_escape(summary)}</summary>\n',
                    f"{entry_content}\n",
                    " </entry>\n",
                ]
            )
        )

    if last_updated is None:
        last_updated = datetime.now(tz=timezone.utc)

    xml: list[str] = []
    xml.append('<?xml version="1.0" encoding="utf-8"?>\n')
    xml.append('<feed xmlns="http://www.w3.org/2005/Atom" xml:lang="en">\n')
    xml.append(f" <title>{xml_escape(channel_title)}</title>\n")
    xml.append(f" <id>{xml_escape(feed_id)}</id>\n")
    xml.append(f" <updated>{xml_escape(_rfc3339_utc(last_updated))}</updated>\n")
    xml.append(
        f' <link rel="self" type="application/atom+xml" href="{xml_escape(self_href)}" />\n'
    )
    xml.append(f' <link rel="alternate" href="{xml_escape(site_link)}" />\n')
    if site_name:
        xml.append(" <author>\n")
        xml.append(f"  <name>{xml_escape(site_name)}</name>\n")
        xml.append(" </author>\n")
    xml.extend(entries_xml)
    xml.append("</feed>\n")
    return "".join(xml)
