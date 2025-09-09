from pathlib import Path
import discord


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


class MirrorClient(discord.Client):
    def __init__(self, *, channel_id: int, out_dir: Path, regen_callable):
        super().__init__()
        self.channel_id = channel_id
        self.out_dir = out_dir
        self._regen = regen_callable

    async def _try_regen_if_visible(self):
        try:
            chan = await self.fetch_channel(self.channel_id)
        except discord.Forbidden:
            return
        except Exception:
            return
        await self._regen(chan, self.out_dir)

    async def on_ready(self):
        print(f"Logged in as {self.user} (id {self.user.id})")
        try:
            await self.change_presence(
                status=getattr(discord.Status, "invisible", None)
            )
        except Exception:
            pass
        try:
            chan = await self.fetch_channel(self.channel_id)
        except discord.Forbidden:
            print(f"Channel {self.channel_id} not visible right now")
            return
        except Exception as e:
            print(f"Could not fetch channel {self.channel_id}: {e}")
            return
        await self._regen(chan, self.out_dir)

    async def on_guild_channel_update(self, before, after):
        if getattr(after, "id", None) != self.channel_id:
            return
        await self._try_regen_if_visible()

    async def on_guild_role_update(self, before, after):
        await self._try_regen_if_visible()

    async def on_message(self, message: discord.Message):
        if getattr(message.channel, "id", None) != self.channel_id:
            return
        await self._regen(message.channel, self.out_dir)

    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if getattr(after.channel, "id", None) != self.channel_id:
            return
        await self._regen(after.channel, self.out_dir)

    async def on_message_delete(self, message: discord.Message):
        if getattr(message.channel, "id", None) != self.channel_id:
            return
        await self._regen(message.channel, self.out_dir)
