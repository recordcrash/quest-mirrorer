import ast
import os
import re
import sys
from pathlib import Path

import discord
from dotenv import load_dotenv

from discord_core import install_safety_guards, MirrorClient
from sitegen import regenerate_site_from_channel

# config
load_dotenv(os.getenv("ENV_FILE") or ".env")

TOKEN = os.getenv("DISCORD_TOKEN")
CHANNELS_RAW = os.getenv("CHANNELS", "")
OUTPUT_DIR = os.getenv("OUTPUT_DIR") or "site"
HISTORY_LIMIT = int(os.getenv("HISTORY_LIMIT") or 500)
STORY_TITLE = os.getenv("STORY_TITLE") or "Story"
MAX_IMAGE_MB = float(os.getenv("MAX_IMAGE_MB") or 25.0)
ABSOLUTE_URL = os.getenv("ABSOLUTE_URL")
SITE_NAME = os.getenv("SITE_NAME") or "Site"
PAGE_OFFSET_RAW = os.getenv("PAGE_OFFSET") or "0"
CHECK_FOR_UPDATES_RAW = os.getenv("CHECK_FOR_UPDATES", "1")

def _parse_channels(raw: str) -> list[int]:
    raw = raw.strip()
    if not raw:
        return []
    try:
        value = ast.literal_eval(raw)
    except Exception:
        value = raw
    if isinstance(value, (list, tuple, set)):
        items = list(value)
    elif isinstance(value, str):
        items = [p for p in re.split(r"[,\s]+", value) if p]
    else:
        items = [value]
    channels: list[int] = []
    for item in items:
        try:
            channels.append(int(item))
        except (TypeError, ValueError):
            raise ValueError(f"CHANNELS must be integers; got {item!r}")
    return channels


def _parse_bool(raw: str, default: bool) -> bool:
    if raw is None:
        return default
    val = str(raw).strip().lower()
    if val in {"1", "true", "yes", "y", "on"}:
        return True
    if val in {"0", "false", "no", "n", "off"}:
        return False
    return default


if not TOKEN:
    print("DISCORD_TOKEN is missing")
    sys.exit(1)

try:
    CHANNELS = _parse_channels(CHANNELS_RAW)
except ValueError as e:
    print(str(e))
    sys.exit(1)

if not CHANNELS:
    print("CHANNELS is missing")
    sys.exit(1)

try:
    PAGE_OFFSET = int(PAGE_OFFSET_RAW)
except ValueError:
    print("PAGE_OFFSET must be an integer")
    sys.exit(1)
if PAGE_OFFSET < 0:
    print("PAGE_OFFSET cannot be negative")
    sys.exit(1)

CHECK_FOR_UPDATES = _parse_bool(CHECK_FOR_UPDATES_RAW, True)

install_safety_guards()


async def regen(chans: list[discord.abc.Messageable], out_dir: Path):
    await regenerate_site_from_channel(
        chans=chans,
        out_dir=out_dir,
        story_title=STORY_TITLE,
        history_limit=HISTORY_LIMIT,
        max_image_mb=MAX_IMAGE_MB,
        absolute_url=ABSOLUTE_URL,
        site_name=SITE_NAME,
        page_offset=PAGE_OFFSET,
        channel_ids=CHANNELS,
    )


def main():
    out_dir = Path(OUTPUT_DIR).resolve()
    client = MirrorClient(
        channel_ids=CHANNELS,
        out_dir=out_dir,
        regen_callable=regen,
        exit_after_regen=not CHECK_FOR_UPDATES,
    )
    try:
        client.run(TOKEN)
    except KeyboardInterrupt:
        print("Shutting down")
    except Exception as e:
        print(f"Client error: {e}")


if __name__ == "__main__":
    main()
