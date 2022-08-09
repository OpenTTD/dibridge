import asyncio
import irc.client_aio
import logging
import re
import sys
import time

from .irc_puppet import IRCPuppet
from . import relay

log = logging.getLogger(__name__)


class IRCRelay(irc.client_aio.AioSimpleIRCClient):
    def __init__(self, host, port, nickname, channel, single_presence):
        irc.client.SimpleIRCClient.__init__(self)

        self._loop = asyncio.get_event_loop()

        self._host = host
        self._port = port
        self._nickname = nickname
        self._joined = False
        self._tell_once = True
        self._channel = channel
        self._single_presence = single_presence

        # List of users when they have last spoken.
        self._users_spoken = {}

        self._puppets = {}

    def on_nicknameinuse(self, _, event):
        log.error("Nickname already in use: %r", event)
        # TODO -- Pick another name

    def on_welcome(self, client, event):
        self._client = client
        self._client.join(self._channel)

    def on_privmsg(self, _, event):
        # TODO -- Consider relaying private messages too. Can be useful to identify with NickServ etc.
        pass

    def on_pubmsg(self, _, event):
        if event.target != self._channel:
            return
        asyncio.create_task(self._relay_mesage(event.source.nick, event.arguments[0]))

    def on_action(self, _, event):
        if event.target != self._channel:
            return
        asyncio.create_task(self._relay_mesage(event.source.nick, f"_{event.arguments[0]}_"))

    def on_join(self, _client, event):
        if event.target != self._channel:
            return

        if event.source.nick == self._nickname:
            if not self._tell_once:
                relay.DISCORD.send_message_self(":white_check_mark: IRC bridge is now active :white_check_mark: ")
            log.info("Joined %s on IRC", self._channel)
            self._joined = True
            self._tell_once = True

            relay.DISCORD.update_presence("#openttd on IRC")

    def on_part(self, _client, event):
        if event.target != self._channel:
            return
        self._left(event.source.nick)

    def on_kick(self, _client, event):
        if event.target != self._channel:
            return
        self._left(event.arguments[0])

    def on_disconnect(self, _client, event):
        log.error("Disconnected from IRC: %s", event.arguments[0])
        self._joined = False
        # The library will reconnect us.

    def _left(self, nick):
        # If we left the channel, rejoin.
        if nick == self._nickname:
            self._joined = False
            self._client.join(self._channel)
            return

        # If the user spoken recently, show on Discord the user left.
        if self._users_spoken.get(nick, 0) > time.time() - 60 * 10:
            self._users_spoken.pop(nick)
            relay.DISCORD.send_message(nick, "/me left the IRC channel")

    async def _connect(self):
        await self.connection.connect(
            self._host, self._port, self._nickname, connect_factory=irc.connection.AioFactory(ssl=True)
        )

    async def _send_message(self, discord_id, discord_username, message, is_action=False):
        # If we aren't connected to IRC yet, tell this to the Discord users; but only once.
        if not self._joined:
            if self._tell_once:
                self._tell_once = False
                relay.DISCORD.send_message_self(
                    ":warning: IRC bridge isn't active; messages will not be delivered :warning:"
                )
            return

        if self._single_presence:
            if is_action:
                message = f"/me {message}"
            self._client.privmsg(self._channel, f"<{discord_username}>: {message}")
            return

        if discord_id not in self._puppets:
            self._puppets[discord_id] = IRCPuppet(discord_username, self._channel)
            asyncio.create_task(self._puppets[discord_id].connect(self._host, self._port))

        if is_action:
            await self._puppets[discord_id].send_action(message)
        else:
            await self._puppets[discord_id].send_message(message)

    async def _relay_mesage(self, irc_username, message):
        # Don't echo back talk done by our puppets.
        for discord_id, puppet in self._puppets.items():
            if puppet._nickname == irc_username:
                return

            # On IRC, it is common to do "name: ", but on Discord you don't do that ": " part.
            if message.startswith(f"{puppet._nickname}: "):
                message = f"<@{discord_id}> " + message[len(f"{puppet._nickname}: ") :]

            # If the username is said as its own word, replace it with a Discord highlight.
            message = re.sub(r"(?<!\w)" + puppet._nickname + r"(?!\w)", f"<@{discord_id}>", message)

        self._users_spoken[irc_username] = time.time()
        relay.DISCORD.send_message(irc_username, message)

    async def _stop(self):
        sys.exit(1)

    # Thread safe wrapper around functions

    def get_irc_username(self, discord_id, discord_username):
        if discord_id not in self._puppets:
            return discord_username

        return self._puppets[discord_id]._nickname

    def send_message(self, discord_id, discord_username, message):
        asyncio.run_coroutine_threadsafe(self._send_message(discord_id, discord_username, message), self._loop)

    def send_action(self, discord_id, discord_username, message):
        asyncio.run_coroutine_threadsafe(
            self._send_message(discord_id, discord_username, message, is_action=True), self._loop
        )

    def stop(self):
        asyncio.run_coroutine_threadsafe(self._stop(), self._loop)


def start(host, port, name, channel, single_presence):
    asyncio.set_event_loop(asyncio.new_event_loop())

    relay.IRC = IRCRelay(host, port, name, channel, single_presence)

    log.info("Connecting to IRC ...")
    asyncio.get_event_loop().run_until_complete(relay.IRC._connect())
    try:
        relay.IRC.start()
    finally:
        relay.IRC.connection.disconnect()
        relay.IRC.reactor.loop.close()
