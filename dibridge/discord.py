import asyncio
import discord
import logging
import re
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

        # Anyone that has spoken in the Discord channel, will get a highlight if their name is used on IRC.
        # This is especially needed as on IRC your Discord name is used, not your nick.
        self._mentions = {}

        self.loop = asyncio.get_event_loop()

    async def on_ready(self):
        # Check if we have access to the channel.
        self._channel = self.get_channel(self._channel_id)
        if not self._channel:
            log.error("Discord channel ID %s not found", self._channel_id)
            asyncio.run_coroutine_threadsafe(relay.IRC.stop(), relay.IRC.loop)
            sys.exit(1)

        # Make sure there is a webhook on the channel to use for relaying.
        for webhook in await self._channel.webhooks():
            if webhook.token is not None:
                self._channel_webhook = webhook
                break
        else:
            self._channel_webhook = await self._channel.create_webhook(
                name="ircbridge", reason="To bridge IRC messages to Discord"
            )

        log.info("Logged on to Discord as '%s'", self.user)

    async def send_message(self, irc_username, message):
        # If the user is mentioned in the message, highlight them.
        for username, id in self._mentions.items():
            # On IRC, it is common to do "name: ", but on Discord you don't do that ": " part.
            if message.startswith(f"{username}: "):
                message = f"<@{id}> " + message[len(f"{username}: ") :]

            # If the username is said as its own word, replace it with a Discord highlight.
            message = re.sub(r"(?<!\w)" + username + r"(?!\w)", f"<@{id}>", message)

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

        content = message.content

        def replace_mention(prefix, postfix, id, name, content):
            identifer = f"{prefix}{id}{postfix}"

            # At the beginning of the line, on IRC it is custom to add a ": " behind the highlight.
            if (
                content.startswith(f"{identifer}")
                and not content.startswith(f"{identifer}:")
                and content != f"{identifer}"
            ):
                return f"{name}: " + content[len(f"{identifer}") :]

            # Otherwise it is just an inline replacement.
            return content.replace(f"{identifer}", name)

        # Replace all mentions in the message with the username (<@12345679>)
        for mention in message.mentions:
            content = replace_mention("<@", ">", mention.id, mention.name, content)
        # Replace all channel mentions in the message with the channel name (<#123456789>).
        for channel in message.channel_mentions:
            content = replace_mention("<#", ">", channel.id, f"Discord channel #{channel.name}", content)
        # Replace all role mentions in the message with the role name (<@&123456789>).
        for role in message.role_mentions:
            content = replace_mention("<@&", ">", role.id, role.name, content)
        content = replace_mention("@", "", "everyone", "all", content)
        content = replace_mention("@", "", "here", "all", content)

        # Replace all emoji mentions in the message with the emoji name (<:emoji:123456789>).
        # (sadly, discord.py library doesn't have support for it)
        def find_emojis(content):
            return [{"id": id, "name": name} for name, id in re.findall(r"<:(\w+):([0-9]{15,20})>", content)]

        for emoji in find_emojis(content):
            content = replace_mention("<:", ">", f"{emoji['name']}:{emoji['id']}", f":{emoji['name']}:", content)

        # Allow highlights for users that have talked.
        self._mentions[message.author.name] = message.author.id

        # First, send any attachment as links.
        for attachment in message.attachments:
            asyncio.run_coroutine_threadsafe(
                relay.IRC.send_message(message.author.name, attachment.url), relay.IRC.loop
            )

        # Next, send the actual message if it wasn't empty.
        # It is empty if for example someone only sends an attachment.
        if content:
            asyncio.run_coroutine_threadsafe(relay.IRC.send_message(message.author.name, content), relay.IRC.loop)

    async def on_error(self, event, *args, **kwargs):
        log.exception("on_error(%s): %r / %r", event, args, kwargs)

    async def stop(self):
        sys.exit(1)


def start(token, channel_id):
    asyncio.set_event_loop(asyncio.new_event_loop())

    relay.DISCORD = RelayDiscord(channel_id)
    relay.DISCORD.run(token)
