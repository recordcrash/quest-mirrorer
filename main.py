import os
import sys
from pathlib import Path
import html as _html
from urllib.parse import urlparse
import mimetypes

import requests
import discord
from dotenv import load_dotenv
from jinja2 import Environment, BaseLoader, select_autoescape
from markupsafe import Markup

# config
load_dotenv(os.getenv("ENV_FILE") or ".env")

TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID_RAW = os.getenv("CHANNEL_ID")
OUTPUT_DIR = os.getenv("OUTPUT_DIR") or "site"
HISTORY_LIMIT = int(os.getenv("HISTORY_LIMIT") or 500)
STORY_TITLE = os.getenv("STORY_TITLE") or "Story"
MAX_IMAGE_MB = float(os.getenv("MAX_IMAGE_MB") or 25.0)

if not TOKEN:
    print("DISCORD_TOKEN is missing")
    sys.exit(1)
if not CHANNEL_ID_RAW:
    print("CHANNEL_ID is missing")
    sys.exit(1)
try:
    CHANNEL_ID = int(CHANNEL_ID_RAW)
except ValueError:
    print("CHANNEL_ID must be an integer")
    sys.exit(1)

# prevent any outgoing actions
def install_safety_guards():
    try:
        from discord import abc as dabc
    except Exception:
        dabc = None

    async def _disabled_send(self, *args, **kwargs):
        raise RuntimeError("Sending is disabled in this mirror script.")
    async def _disabled_reply(self, *args, **kwargs):
        raise RuntimeError("Reply is disabled in this mirror script.")
    async def _disabled_trigger_typing(self, *args, **kwargs):
        return

    try:
        if dabc and hasattr(dabc.Messageable, "send"):
            dabc.Messageable.send = _disabled_send
    except Exception:
        pass
    try:
        if hasattr(discord.Message, "reply"):
            discord.Message.reply = _disabled_reply
    except Exception:
        pass
    try:
        if dabc and hasattr(dabc.Messageable, "trigger_typing"):
            dabc.Messageable.trigger_typing = _disabled_trigger_typing
    except Exception:
        pass

install_safety_guards()

CSS_MIN = r"""
@font-face {
    font-family: "Arial";
    font-weight: 700;
    src: local("Arial Bold"), url("arialbd.ttf") format("truetype");
}

@font-face {
    font-family: "Courier New";
    font-weight: 700;
    src: local("Courier New Bold"), url("courbd.ttf") format("truetype");
}

@font-face {
    font-family: "Courier New";
    font-weight: 700;
    font-style: italic;
    src: local("Courier New Bold Italic"), url("courbi.ttf") format("truetype");
}

@font-face {
    font-family: "Verdana";
    font-weight: 400;
    src: local("Verdana"), url("verdana.ttf") format("truetype");
}

@font-face {
    font-family: "Verdana";
    font-weight: 700;
    src: local("Verdana Bold"), url("verdanab.ttf") format("truetype");
}

@font-face {
    font-family: "Verdana";
    font-weight: 400;
    font-style: italic;
    src: local("Verdana Italic"), url("verdanai.ttf") format("truetype");
}

@font-face {
    font-family: "Verdana";
    font-weight: 700;
    font-style: italic;
    src: local("Verdana Bold Italic"), url("verdanaz.ttf") format("truetype");
}

@font-face {
    font-family: "Comic Sans MS";
    font-weight: 400;
    src: local("Comic Sans MS"), url("comic.ttf") format("truetype");
}

@font-face {
    font-family: "Comic Sans MS";
    font-weight: 700;
    src: local("Comic Sans MS Bold"), url("comicbd.ttf") format("truetype");
}

@font-face {
    font-family: "OpenDyslexic";
    font-weight: 400;
    src: local("OpenDyslexic Regular"), url("OpenDyslexic-Regular.otf") format("opentype");
}

@font-face {
    font-family: "OpenDyslexic";
    font-weight: 700;
    src: local("OpenDyslexic Bold"), url("OpenDyslexic-Bold.otf") format("opentype");
}

@font-face {
    font-family: "OpenDyslexic";
    font-weight: 400;
    font-style: italic;
    src: local("OpenDyslexic Italic"), url("OpenDyslexic-Italic.otf") format("opentype");
}

@font-face {
    font-family: "OpenDyslexic";
    font-weight: 700;
    font-style: italic;
    src: local("OpenDyslexic Bold Italic"), url("OpenDyslexic-Bold-Italic.otf") format("opentype");
}

:root{
  --page-bg:#535353;
  --page-color:#000000;
  --card-bg:#efefef;
  --card-bg-dark:#c6c6c6;
  --comic-font:"Courier New", Courier, monospace;
  --text-font:Verdana, Arial, Helvetica, sans-serif;
}
*{ image-rendering: pixelated; }
html,body{ margin:0; }
body{ background:var(--page-bg); color:var(--page-color); font-family:var(--text-font); font-size:18px; display:flex; flex-direction:column; }
#page-wrapper{ display:flex; flex-direction:column; margin:0 auto; }
#page-outer{ background:var(--card-bg-dark); display:flex; flex-direction:column; justify-content:center; padding-top:7px; padding-bottom:23px; }
#page{ background:var(--card-bg); margin:0 auto; width:auto; }
#title{ margin:0; padding:20px 0; font-size:32px; font-family:var(--comic-font); font-weight:700; text-align:center; margin:0 5%; overflow:hidden; overflow-wrap:break-word; }
#media{ display:flex; flex-direction:column; }
#media img{ display:block; max-width:100%; height:auto; margin:0 auto 20px auto; }
#content{ width:90%; margin:0 auto; }
.comic-text{
  font-family:var(--comic-font);
  font-weight:700;
  text-align:center;
  margin:0;
  padding-top:calc(12px + .6em);
  padding-bottom:calc(10px + .6em);
  overflow:hidden;
  overflow-wrap:break-word;
  max-width:100%;
}
.commands{ padding-bottom:38px; font-size:26px; }
#page-footer{ padding-bottom:17px; font-size:.75em; font-weight:700; display:flex; flex-direction:row; justify-content:space-between; width:90%; margin:0 auto; }
#page-footer ul{ list-style:none; margin:0; padding:0; display:flex; flex-direction:row; }
#page-footer li{ display:flex; flex-direction:row; }
#page-footer li:not(:last-child)::after{ content:"|"; font-weight:400; margin:0 .4em; }
@media (min-width: 900px){
  #page-wrapper{ width:950px; }
  #page{ min-width:650px; max-width:950px; }
  #title{ max-width:600px; padding:14px 0; margin:0 auto; }
  #content{ width:600px; }
  .commands{ font-size:24px; }
}
"""

# static header you provided
SITE_HEADER_HTML = Markup("""
<nav class="site-header py-1">
  <div class="container d-flex flex-column flex-md-row justify-content-between">
    <a class="navbar-spiro py-2" href="/index.html" aria-label="Homestuck.net">
      <img class="bd-placeholder-img mr-2 rounded" height="25" xmlns="http://www.w3.org/2000/svg" preserveaspectratio="xMidYMid slice" focusable="false" role="img" src="/img/templogowhite.png">
    </a>
    <a class="py-2 d-none d-md-inline-block" href="/games">Games</a>
    <a class="py-2 d-none d-md-inline-block" href="/music">Music</a>
    <a class="py-2 d-none d-md-inline-block" href="/resources">Resources</a>
    <a class="py-2 d-none d-md-inline-block" href="/tools">Tools</a>
    <a class="py-2 d-none d-md-inline-block" href="/meta">Meta</a>
    <a class="py-2 d-none d-md-inline-block" href="/fanworks">Fanworks</a>
    <a class="py-2 d-none d-md-inline-block" href="/official">Official</a>
  </div>
</nav>
""".strip())

# Jinja environment with autoescape
env = Environment(
    loader=BaseLoader(),
    autoescape=select_autoescape(enabled_extensions=("html",))
)

PAGE_TMPL_STR = r"""<!DOCTYPE html>
<html lang="en" class="font-size-1">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ doc_title }}</title>
<meta property="og:title" content="{{ doc_title }}">
<meta property="og:description" content="{{ og_description }}">
<style>{{ css | safe }}</style>
<link href="css/index.css" rel="stylesheet">
</head>
<body>
  {{ site_header }}
  <div id="page-wrapper">
    <div id="page-outer">
      <div id="page">
        {% if visible_title %}
        <h2 id="title">{{ visible_title }}</h2>
        {% endif %}
        <div id="media">
          {% for u in images %}
          <img src="{{ u }}" alt="{{ alts[loop.index0] }}">
          {% endfor %}
        </div>
        <div id="content" data-s="jq" data-p="{{ "%06d"|format(page_number) }}">
          {% for p in paragraphs %}
          <p class="comic-text">{{ p }}</p>
          {% endfor %}
          {% if command_text %}
          <div class="commands">
            &gt; <a href="{{ command_href }}">{{ command_text }}</a>
          </div>
          {% endif %}
          <div id="page-footer">
            <ul id="page-footer-left">
              <li><a id="start-over" href="{{ start_over_href }}">Start Over</a></li>
              <li><a id="go-back" href="{{ go_back_href }}">Go Back</a></li>
              <li><a href="https://github.com/recordcrash/quest-mirrorer">Unofficial Mirror by homestuck.net</a></li>
            </ul>
            <ul id="page-footer-right"></ul>
          </div>
        </div>
      </div>
    </div>
  </div>

  <script>
  (function(){
    var page = {{ page_number }};
    var total = {{ total_pages }};
    function go(n){
      if (n < 1) n = 1;
      if (n > total) return;
      var href = (n === 1) ? "1.html" : String(n) + ".html";
      window.location.href = href;
    }
    document.addEventListener("keydown", function(e){
      if (e.target && (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.isContentEditable)) return;
      if (e.key === "ArrowLeft"){ if (page > 1) go(page - 1); }
      else if (e.key === "ArrowRight"){ if (page < total) go(page + 1); }
    });
  })();
  </script>
</body>
</html>"""
PAGE_TMPL = env.from_string(PAGE_TMPL_STR)

image_exts = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff"}

def is_image_attachment(att: discord.Attachment) -> bool:
    ct = (att.content_type or "").lower()
    if ct.startswith("image/"):
        return True
    name = (att.filename or "").lower()
    return any(name.endswith(ext) for ext in image_exts)

def guess_ext(url: str, content_type: str | None) -> str:
    path = urlparse(url).path or ""
    ext = Path(path).suffix.lower()
    if ext in image_exts:
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
                for chunk in r.iter_content(chunk_size=1024 * 128):
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

def alt_for(url_or_name: str) -> str:
    name = url_or_name.rsplit("/", 1)[-1]
    return name.split("?", 1)[0] or "image"

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
    return [b for b in blocks if b]

def parse_pages_from_messages(messages: list[discord.Message]) -> list[dict]:
    pages: list[dict] = []
    current = {"images": [], "paragraphs": [], "command_text": None}

    def start_new():
        nonlocal current
        pages.append(current)
        current = {"images": [], "paragraphs": [], "command_text": None}

    for m in messages:
        for att in m.attachments:
            if is_image_attachment(att):
                if current["command_text"] and (current["images"] or current["paragraphs"]):
                    start_new()
                current["images"].append(att.url)

        for e in m.embeds:
            u1 = getattr(getattr(e, "image", None), "url", None)
            u2 = getattr(getattr(e, "thumbnail", None), "url", None)
            for u in [u1, u2]:
                if u:
                    if current["command_text"] and (current["images"] or current["paragraphs"]):
                        start_new()
                    current["images"].append(u)

        text = m.content or ""
        if text:
            for raw_line in text.replace("\r\n", "\n").split("\n"):
                s = raw_line.strip()
                if not s:
                    continue
                if s.startswith(">"):
                    cmd = s[1:].strip()
                    if current["command_text"] and (current["images"] or current["paragraphs"]):
                        start_new()
                    current["command_text"] = cmd
            paras = normalize_paragraphs(text)
            if paras:
                if current["command_text"] and (current["images"] or current["paragraphs"]):
                    start_new()
                current["paragraphs"].extend(paras)

    if current["images"] or current["paragraphs"] or current["command_text"]:
        pages.append(current)

    return pages

def title_for_page(i: int, pages: list[dict]) -> str:
    if i == 1:
        return ""
    prev_cmd = pages[i - 2].get("command_text")
    return prev_cmd or ""

def atomic_write(path: Path, data: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(data, encoding="utf-8")
    tmp.replace(path)

def render_page_html(*, story_title: str, page_number: int, total_pages: int, page: dict, pages: list[dict]) -> str:
    visible_title = title_for_page(page_number, pages)
    images = page["images"]
    paragraphs = page["paragraphs"]
    command_text = page["command_text"]
    command_href = f"{page_number + 1}.html" if command_text else None
    start_over_href = "1.html"
    go_back_href = f"{page_number - 1}.html" if page_number > 1 else start_over_href
    doc_title = f"{story_title}: {visible_title}" if visible_title else f"{story_title}: Page {page_number}"
    og_description = _html.escape(paragraphs[0][:180] + ("…" if paragraphs and len(paragraphs[0]) > 180 else "")) if paragraphs else ""

    return PAGE_TMPL.render(
        css=CSS_MIN,
        site_header=SITE_HEADER_HTML,
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
    )

def clean_page_images(out_dir: Path, page_number: int) -> None:
    prefix = f"page{page_number}_"
    for p in out_dir.glob(f"{prefix}*"):
        try:
            p.unlink()
        except Exception:
            pass

def rewrite_images_to_local(*, out_dir: Path, page_number: int, urls: list[str]) -> list[str]:
    clean_page_images(out_dir, page_number)
    local_names: list[str] = []
    for idx, url in enumerate(urls, start=1):
        if urlparse(url).scheme not in {"http", "https"}:
            continue
        base_name = f"page{page_number}_{idx}"
        dest = out_dir / base_name
        ok = download_image(url, dest, MAX_IMAGE_MB)
        if ok:
            saved = next(out_dir.glob(base_name + ".*"), None)
            if saved:
                local_names.append(saved.name)
    return local_names

async def regenerate_site_from_channel(chan: discord.abc.Messageable, out_dir: Path) -> int:
    msgs = []
    async for m in chan.history(limit=HISTORY_LIMIT, oldest_first=True):
        msgs.append(m)
    pages = parse_pages_from_messages(msgs)
    total_pages = len(pages)

    out_dir.mkdir(parents=True, exist_ok=True)

    for i, page in enumerate(pages, start=1):
        local_imgs = rewrite_images_to_local(out_dir=out_dir, page_number=i, urls=page["images"])
        page_for_render = {
            "images": local_imgs,
            "paragraphs": page["paragraphs"],
            "command_text": page["command_text"],
        }
        html_str = render_page_html(
            story_title=STORY_TITLE,
            page_number=i,
            total_pages=total_pages,
            page=page_for_render,
            pages=pages
        )
        atomic_write(out_dir / f"{i}.html", html_str)

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

    print(f"Wrote {total_pages} page files to {out_dir}")
    return total_pages

class MirrorClient(discord.Client):
    def __init__(self, *, channel_id: int, out_dir: Path):
        super().__init__()
        self.channel_id = channel_id
        self.out_dir = out_dir

    async def on_ready(self):
        print(f"Logged in as {self.user} (id {self.user.id})")
        try:
            await self.change_presence(status=getattr(discord.Status, "invisible", None))
        except Exception:
            pass
        try:
            chan = await self.fetch_channel(self.channel_id)
        except Exception as e:
            print(f"Could not fetch channel {self.channel_id}: {e}")
            await self.close()
            return
        await regenerate_site_from_channel(chan, Path(self.out_dir))

    async def on_message(self, message: discord.Message):
        if getattr(message.channel, "id", None) != self.channel_id:
            return
        await regenerate_site_from_channel(message.channel, Path(self.out_dir))

    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if getattr(after.channel, "id", None) != self.channel_id:
            return
        await regenerate_site_from_channel(after.channel, Path(self.out_dir))

    async def on_message_delete(self, message: discord.Message):
        if getattr(message.channel, "id", None) != self.channel_id:
            return
        await regenerate_site_from_channel(message.channel, Path(self.out_dir))

def main():
    out_dir = Path(OUTPUT_DIR).resolve()
    client = MirrorClient(channel_id=CHANNEL_ID, out_dir=out_dir)
    try:
        client.run(TOKEN)
    except KeyboardInterrupt:
        print("Shutting down")
    except Exception as e:
        print(f"Client error: {e}")

if __name__ == "__main__":
    main()
