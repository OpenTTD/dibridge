import asyncio
import irc.client_aio
import logging
import sys
import time

from . import relay

log = logging.getLogger(__name__)


class IRCRelay(irc.client_aio.AioSimpleIRCClient):
    def __init__(self, host, port, nickname, channel):
        irc.client.SimpleIRCClient.__init__(self)

        self.loop = asyncio.get_event_loop()

        self._nickname = nickname
        self._joined = False
        self._tell_once = True
        self._channel = channel

        # List of users when they have last spoken.
        self._users_spoken = {}

        self.connect(host, port, nickname, connect_factory=irc.connection.AioFactory(ssl=True))

    async def send_message(self, discord_username, content):
        # If we aren't connected to IRC yet, tell this to the Discord users; but only once.
        if not self._joined:
            if self._tell_once:
                self._tell_once = False
                asyncio.run_coroutine_threadsafe(
                    relay.DISCORD.send_message_self(
                        ":warning: IRC bridge isn't active; messages will not be delivered :warning:"
                    ),
                    relay.DISCORD.loop,
                )
            return

        self._client.privmsg(self._channel, f"<{discord_username}> {content}")

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

        self._users_spoken[event.source.nick] = time.time()

        asyncio.run_coroutine_threadsafe(
            relay.DISCORD.send_message(event.source.nick, event.arguments[0]), relay.DISCORD.loop
        )

    def on_action(self, _, event):
        if event.target != self._channel:
            return

        asyncio.run_coroutine_threadsafe(
            relay.DISCORD.send_message(event.source.nick, f"_{event.arguments[0]}_"), relay.DISCORD.loop
        )

    def on_join(self, _client, event):
        if event.target != self._channel:
            return

        if event.source.nick == self._nickname:
            if not self._tell_once:
                asyncio.run_coroutine_threadsafe(
                    relay.DISCORD.send_message_self(":white_check_mark: IRC bridge is now active :white_check_mark: "),
                    relay.DISCORD.loop,
                )

            log.info("Joined %s on IRC", self._channel)
            self._joined = True
            self._tell_once = True

            asyncio.run_coroutine_threadsafe(
                relay.DISCORD.update_presence("#openttd on IRC"),
                relay.DISCORD.loop,
            )

    def on_part(self, _client, event):
        if event.target != self._channel:
            return
        self._left(event.source.nick)

    def on_kick(self, _client, event):
        if event.target != self._channel:
            return
        self._left(event.arguments[0])

    def _left(self, nick):
        # If we left the channel, rejoin.
        if nick == self._nickname:
            self._joined = False
            self._client.join(self._channel)
            return

        # If the user spoken recently, show on Discord the user left.
        if self._users_spoken.get(nick, 0) > time.time() - 60 * 10:
            self._users_spoken.pop(nick)
            asyncio.run_coroutine_threadsafe(
                relay.DISCORD.send_message(nick, "/me left the IRC channel"), relay.DISCORD.loop
            )

    def on_disconnect(self, _client, event):
        log.error("Disconnected from IRC: %s", event.arguments[0])
        self._joined = False
        # The library will reconnect us.

    async def stop(self):
        sys.exit(1)


def start(host, port, name, channel):
    asyncio.set_event_loop(asyncio.new_event_loop())

    relay.IRC = IRCRelay(host, port, name, channel)

    log.info("Connecting to IRC ...")
    try:
        relay.IRC.start()
    finally:
        relay.IRC.connection.disconnect()
        relay.IRC.reactor.loop.close()
