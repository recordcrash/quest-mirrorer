import os
import sys
from pathlib import Path

import discord
from dotenv import load_dotenv

from discord_core import install_safety_guards, MirrorClient
from sitegen import regenerate_site_from_channel

# config
load_dotenv(os.getenv("ENV_FILE") or ".env")

TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID_OLD_RAW = os.getenv("CHANNEL_ID") or os.getenv("CHANNEL_ID_OLD")
CHANNEL_ID_NEW_RAW = os.getenv("CHANNEL_ID_NEW")
OUTPUT_DIR = os.getenv("OUTPUT_DIR") or "site"
HISTORY_LIMIT = int(os.getenv("HISTORY_LIMIT") or 500)
STORY_TITLE = os.getenv("STORY_TITLE") or "Story"
MAX_IMAGE_MB = float(os.getenv("MAX_IMAGE_MB") or 25.0)
ABSOLUTE_URL = os.getenv("ABSOLUTE_URL")
SITE_NAME = os.getenv("SITE_NAME") or "Site"
PAGE_OFFSET_RAW = os.getenv("PAGE_OFFSET") or "0"

if not TOKEN:
    print("DISCORD_TOKEN is missing")
    sys.exit(1)
if not CHANNEL_ID_OLD_RAW:
    print("CHANNEL_ID (old) is missing")
    sys.exit(1)
if not CHANNEL_ID_NEW_RAW:
    print("CHANNEL_ID_NEW is missing")
    sys.exit(1)
try:
    CHANNEL_ID_OLD = int(CHANNEL_ID_OLD_RAW)
    CHANNEL_ID_NEW = int(CHANNEL_ID_NEW_RAW)
except ValueError:
    print("CHANNEL_ID values must be integers")
    sys.exit(1)
try:
    PAGE_OFFSET = int(PAGE_OFFSET_RAW)
except ValueError:
    print("PAGE_OFFSET must be an integer")
    sys.exit(1)
if PAGE_OFFSET < 0:
    print("PAGE_OFFSET cannot be negative")
    sys.exit(1)

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
        old_channel_id=CHANNEL_ID_OLD,
        new_channel_id=CHANNEL_ID_NEW,
    )


def main():
    out_dir = Path(OUTPUT_DIR).resolve()
    client = MirrorClient(
        channel_ids=[CHANNEL_ID_OLD, CHANNEL_ID_NEW],
        out_dir=out_dir,
        regen_callable=regen,
    )
    try:
        client.run(TOKEN)
    except KeyboardInterrupt:
        print("Shutting down")
    except Exception as e:
        print(f"Client error: {e}")


if __name__ == "__main__":
    main()
