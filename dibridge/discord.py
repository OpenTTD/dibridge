import asyncio
import discord
import logging
import sys

from . import relay

log = logging.getLogger(__name__)


class RelayDiscord(discord.Client):
    def __init__(self, channel_id):
        # We need many intents:
        # - messages, to receive messages.
        # - guilds, to get the channel.
        # - presences, to see when a user goes offline.
        # - members, as otherwise 'presences' doesn't work.
        # - message_content, as we actually want to know the message content.
        intents = discord.Intents(messages=True, guilds=True, presences=True, members=True, message_content=True)
        # Don't allow IRC users to be cheeky, and don't allow @everyone etc.
        allowed_mentions = discord.AllowedMentions.none()
        allowed_mentions.users = True
        super().__init__(intents=intents, allowed_mentions=allowed_mentions)

        self._channel_id = channel_id

        self.loop = asyncio.get_event_loop()

    async def on_ready(self):
        # Check if we have access to the channel.
        self._channel = self.get_channel(self._channel_id)
        if not self._channel:
            log.error("Discord channel ID %s not found", self._channel_id)
            asyncio.run_coroutine_threadsafe(relay.IRC.stop(), relay.IRC.loop)
            sys.exit(1)

        # Make sure there is a webhook on the channel to use for relaying.
        if not await self._channel.webhooks():
            await self._channel.create_webhook(name="ircbridge")
        self._channel_webhook = (await self._channel.webhooks())[0]

        log.info("Logged on to Discord as '%s'", self.user)

    async def send_message(self, irc_username, message):
        await self._channel_webhook.send(
            message,
            username=irc_username,
            suppress_embeds=True,
            avatar_url=f"https://robohash.org/${irc_username}.png?set=set4",
        )

    async def send_message_self(self, message):
        await self._channel.send(message)

    async def update_presence(self, status):
        await self.change_presence(
            activity=discord.Activity(type=discord.ActivityType.watching, name=status),
            status=discord.Status.online,
        )

    async def on_message(self, message):
        # Only monitor the indicated channel.
        if message.channel.id != self._channel_id:
            return
        # We don't care what bots have to say.
        if message.author.bot:
            return
        # We don't care if it isn't a normal message.
        if message.type != discord.MessageType.default:
            return

        asyncio.run_coroutine_threadsafe(relay.IRC.send_message(message.author.name, message.content), relay.IRC.loop)

    async def on_error(self, event, *args, **kwargs):
        log.exception("on_error(%s): %r / %r", event, args, kwargs)

    async def stop(self):
        sys.exit(1)


def start(token, channel_id):
    asyncio.set_event_loop(asyncio.new_event_loop())

    relay.DISCORD = RelayDiscord(channel_id)
    relay.DISCORD.run(token)
