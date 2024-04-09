import asyncio
import discord
import logging
import re
import sys
import textwrap

from . import relay

log = logging.getLogger(__name__)

# The maximum length of a message on IRC. This is different per network,
# but 400 seems like a safe value for most modern IRC networks.
IRC_MAX_LINE_LENGTH = 400


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

        self._status = None
        self._channel_id = channel_id
        self._commands = discord.app_commands.CommandTree(self)

        # Rebind the commands to the current client.
        self.command_status.binding = self

        # Add the commands we are listening too.
        self._commands.add_command(self.command_status)

    async def setup_hook(self):
        # Sync the commands, so Discord knows about them too.
        await self._commands.sync()

    async def on_ready(self):
        # Check if we have access to the channel.
        self._channel = self.get_channel(self._channel_id)
        if not self._channel:
            log.error("Discord channel ID %s not found", self._channel_id)
            relay.IRC.stop()
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

        if self._status:
            await self._update_presence(self._status)

        log.info("Logged on to Discord as '%s'", self.user)

    async def on_message(self, message):
        # Only monitor the indicated channel.
        if message.channel.id != self._channel_id:
            return
        # We don't care what bots have to say.
        if message.author.bot:
            return
        # We don't care if it isn't a message or a reply.
        if message.type not in (discord.MessageType.default, discord.MessageType.reply):
            return

        relay.IRC.update_status(message.author.id, message.author.status == discord.Status.offline)

        content = message.content

        if message.type == discord.MessageType.reply:
            author = message.reference.resolved.author
            content = f"{relay.IRC.get_irc_username(author.id, author.name)}: {content}"

        def replace_mention(prefix, postfix, id, name, content):
            identifer = f"{prefix}{id}{postfix}"

            # At the beginning of the line, on IRC it is custom to add a ": " behind the highlight.
            if (
                content.startswith(f"{identifer}")
                and not content.startswith(f"{identifer}:")
                and content != f"{identifer}"
            ):
                return f"{name}: " + content[len(f"{identifer}") :].strip()

            # Otherwise it is just an inline replacement.
            return content.replace(f"{identifer}", name)

        # Replace all mentions in the message with the username (<@12345679>)
        for mention in message.mentions:
            content = replace_mention(
                "<@", ">", mention.id, relay.IRC.get_irc_username(mention.id, mention.name), content
            )
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

        # First, send any attachment as links.
        for attachment in message.attachments:
            relay.IRC.send_message(message.author.id, message.author.name, attachment.url)

        content = content.replace("\r\n", "\n").replace("\r", "\n").strip()

        # On Discord text between _ and _ is what IRC calls an action.
        # IRC has a limit on message size; if reached, make the action multi-line too.
        if (
            content.startswith("_")
            and content.endswith("_")
            and len(content) > 2
            and "\n" not in content
            and len(content) < IRC_MAX_LINE_LENGTH
        ):
            relay.IRC.send_action(message.author.id, message.author.name, content[1:-1])
        else:
            for full_line in content.split("\n"):
                # On Discord, you make code-blocks by starting and finishing with ```.
                # This is considered noise on IRC however. So we ignore those lines.
                if full_line == "```":
                    continue

                # Split the message in lines of at most IRC_MAX_LINE_LENGTH characters, breaking on words.
                for line in textwrap.wrap(full_line.strip(), IRC_MAX_LINE_LENGTH):
                    relay.IRC.send_message(message.author.id, message.author.name, line)

    async def on_presence_update(self, before, after):
        relay.IRC.update_status(after.id, after.status == discord.Status.offline)

    async def on_error(self, event, *args, **kwargs):
        log.exception("on_error(%s): %r / %r", event, args, kwargs)

    @discord.app_commands.command(name="status", description="Get the status of the bridge")
    async def command_status(self, interaction: discord.Interaction):
        status = f":green_circle: **Discord** listening in <#{self._channel_id}>\n"
        status += relay.IRC.get_status()

        await interaction.response.send_message(status, ephemeral=True)

    async def _send_message(self, irc_username, message):
        await self._channel_webhook.send(
            message,
            username=irc_username,
            suppress_embeds=True,
            avatar_url=f"https://robohash.org/${irc_username}.png?set=set4",
        )

    async def _send_message_self(self, message):
        await self._channel.send(message)

    async def _update_presence(self, status):
        self._status = status
        await self.change_presence(
            activity=discord.Activity(type=discord.ActivityType.watching, name=status),
            status=discord.Status.online,
        )

    async def _stop(self):
        sys.exit(1)

    # Thread safe wrapper around functions

    def send_message(self, irc_username, message):
        asyncio.run_coroutine_threadsafe(self._send_message(irc_username, message), self.loop)

    def send_message_self(self, message):
        asyncio.run_coroutine_threadsafe(self._send_message_self(message), self.loop)

    def update_presence(self, status):
        asyncio.run_coroutine_threadsafe(self._update_presence(status), self.loop)


def start(token, channel_id):
    relay.DISCORD = RelayDiscord(channel_id)
    backoff = discord.backoff.ExponentialBackoff()

    while True:
        try:
            relay.DISCORD.run(token, log_handler=None)
        except Exception:
            retry = backoff.delay()
            log.exception("Discord client stopped unexpectedly; will reconnect in %.2f seconds", retry)

            asyncio.run(asyncio.sleep(retry))
