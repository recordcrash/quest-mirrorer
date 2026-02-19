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
    def __init__(
        self,
        *,
        channel_ids: list[int],
        out_dir: Path,
        regen_callable,
        exit_after_regen: bool = False,
    ):
        super().__init__()
        self.channel_ids = set(channel_ids)
        self.out_dir = out_dir
        self._regen = regen_callable
        self.exit_after_regen = exit_after_regen

    async def _fetch_visible_channels(self) -> list:
        chans = []
        for cid in self.channel_ids:
            try:
                c = await self.fetch_channel(cid)
            except discord.Forbidden:
                continue
            except Exception:
                continue
            else:
                chans.append(c)
        return chans

    async def _try_regen_if_visible(self):
        chans = await self._fetch_visible_channels()
        if not chans:
            return
        await self._regen(chans, self.out_dir)

    async def on_ready(self):
        print(f"Logged in as {self.user} (id {self.user.id})")
        try:
            await self.change_presence(
                status=getattr(discord.Status, "invisible", None)
            )
        except Exception:
            pass
        chans = await self._fetch_visible_channels()
        if not chans:
            print(f"Channels {sorted(self.channel_ids)} not visible right now")
            if self.exit_after_regen:
                await self.close()
            return
        await self._regen(chans, self.out_dir)
        if self.exit_after_regen:
            await self.close()

    async def on_guild_channel_update(self, before, after):
        if getattr(after, "id", None) not in self.channel_ids:
            return
        await self._try_regen_if_visible()

    async def on_guild_role_update(self, before, after):
        await self._try_regen_if_visible()

    async def on_message(self, message: discord.Message):
        if getattr(message.channel, "id", None) not in self.channel_ids:
            return
        await self._try_regen_if_visible()

    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if getattr(after.channel, "id", None) not in self.channel_ids:
            return
        await self._try_regen_if_visible()

    async def on_message_delete(self, message: discord.Message):
        if getattr(message.channel, "id", None) not in self.channel_ids:
            return
        await self._try_regen_if_visible()
