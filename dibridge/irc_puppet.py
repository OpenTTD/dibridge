import asyncio
import irc.client_aio
import logging
import socket


class IRCPuppet(irc.client_aio.AioSimpleIRCClient):
    def __init__(self, ipv6_address, nickname, channel):
        irc.client.SimpleIRCClient.__init__(self)

        self.loop = asyncio.get_event_loop()

        self._ipv6_address = ipv6_address
        self._nickname = nickname
        self._nickname_original = nickname
        self._nickname_iteration = 0
        self._joined = False
        self._channel = channel

        self._connected_event = asyncio.Event()
        self._connected_event.clear()

        self._log = logging.getLogger(f"{__name__}.{self._nickname}")

    def on_nicknameinuse(self, client, event):
        # First iteration, try adding a [d] (Discord, get it?).
        if self._nickname_iteration == 0:
            self._nickname = f"{self._nickname_original}[d]"
            self._nickname_iteration += 1
            client.nick(self._nickname)
            return

        # [d] is already in use, try adding a [1], [2], ..
        self._nickname = f"{self._nickname_original}[{self._nickname_iteration}]"
        self._nickname_iteration += 1
        client.nick(self._nickname)

    def on_welcome(self, client, event):
        self._client = client
        self._client.join(self._channel)

    def on_privmsg(self, _, event):
        # TODO -- Consider relaying private messages too. Can be useful to identify with NickServ etc.
        pass

    # on_pubmsg is done by the IRCRelay, and not by the puppets.

    def on_join(self, _client, event):
        if event.target != self._channel:
            return

        if event.source.nick == self._nickname:
            self._log.info("Joined %s on IRC", self._channel)
            self._joined = True
            self._connected_event.set()

    def on_part(self, _client, event):
        if event.target != self._channel:
            return
        self._left(event.source.nick)

    def on_kick(self, _client, event):
        if event.target != self._channel:
            return
        self._left(event.arguments[0])

    def on_nick(self, client, event):
        if event.source.nick == self._nickname:
            # Sometimes happens on a netsplit, or when a username is GHOSTed.
            # Most of the time the name is now something like Guest12345.
            # Try changing back to a name more in line with the user-name.
            self._log.info("Nickname changed to '%s' by server; trying to change it back", event.target)
            self._nickname = event.target
            asyncio.create_task(self.reclaim_nick())

    def on_disconnect(self, _client, event):
        self._log.error("Disconnected from IRC: %s", event.arguments[0])
        self._joined = False
        self._connected_event.clear()
        # The library will reconnect us.

    def _left(self, nick):
        # If we left the channel, rejoin.
        if nick == self._nickname:
            self._joined = False
            self._connected_event.clear()
            self._client.join(self._channel)
            return

    async def reclaim_nick(self):
        # We sleep for a second, as it turns out, if we are quick enough to change
        # our name back, we win from people trying to reclaim their nick. Not the
        # nicest thing to do.
        await asyncio.sleep(1)

        self._nickname = self._nickname_original
        self._nickname_iteration = 0
        self._client.nick(self._nickname)

    async def connect(self, host, port):
        self._log.info("Connecting to IRC from %s ...", self._ipv6_address)
        local_addr = (str(self._ipv6_address), 0)
        # We force an IPv6 connection, as we need that for the puppet source address.
        await self.connection.connect(
            host,
            port,
            self._nickname,
            connect_factory=irc.connection.AioFactory(family=socket.AF_INET6, local_addr=local_addr, ssl=True),
        )

    async def send_message(self, content):
        await self._connected_event.wait()
        self._client.privmsg(self._channel, content)

    async def send_action(self, content):
        await self._connected_event.wait()
        self._client.action(self._channel, content)
