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
CHANNEL_ID_RAW = os.getenv("CHANNEL_ID")
OUTPUT_DIR = os.getenv("OUTPUT_DIR") or "site"
HISTORY_LIMIT = int(os.getenv("HISTORY_LIMIT") or 500)
STORY_TITLE = os.getenv("STORY_TITLE") or "Story"
MAX_IMAGE_MB = float(os.getenv("MAX_IMAGE_MB") or 25.0)
ABSOLUTE_URL = os.getenv("ABSOLUTE_URL")
SITE_NAME = os.getenv("SITE_NAME") or "Site"

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

install_safety_guards()


async def regen(chan: discord.abc.Messageable, out_dir: Path):
    await regenerate_site_from_channel(
        chan=chan,
        out_dir=out_dir,
        story_title=STORY_TITLE,
        history_limit=HISTORY_LIMIT,
        max_image_mb=MAX_IMAGE_MB,
        absolute_url=ABSOLUTE_URL,
        site_name=SITE_NAME,
    )


def main():
    out_dir = Path(OUTPUT_DIR).resolve()
    client = MirrorClient(
        channel_id=CHANNEL_ID,
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
