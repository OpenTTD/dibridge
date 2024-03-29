import asyncio
import irc.client_aio
import logging
import random
import socket


class IRCPuppet(irc.client_aio.AioSimpleIRCClient):
    def __init__(self, irc_host, irc_port, ipv6_address, nickname, username, channel, remove_puppet_func, idle_timeout):
        irc.client.SimpleIRCClient.__init__(self)

        self.loop = asyncio.get_event_loop()

        self._irc_host = irc_host
        self._irc_port = irc_port
        self._ipv6_address = ipv6_address
        self._nickname = nickname
        self._nickname_original = nickname
        self._nickname_iteration = 0
        self._username = username
        self._joined = False
        self._channel = channel
        self._pinger_task = None
        self._remove_puppet_func = remove_puppet_func
        self._idle_timeout = idle_timeout
        self._idle_task = None
        self._reconnect = True

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

        if self._pinger_task:
            self._pinger_task.cancel()
        self._pinger_task = asyncio.create_task(self._pinger())

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

    def on_kill(self, _client, event):
        # If a user is killed, the ops on IRC must have a good reason.
        # So we disconnect the bridge on our side too.
        self._log.info("Killed by server; removing puppet")

        self._reconnect = False
        asyncio.create_task(self._remove_puppet_func())

    def on_nick(self, client, event):
        if event.source.nick == self._nickname:
            # Sometimes happens on a netsplit, or when a username is GHOSTed.
            # Most of the time the name is now something like Guest12345.
            # Try changing back to a name more in line with the user-name.
            self._log.info("Nickname changed to '%s' by server; trying to change it back", event.target)
            self._nickname = event.target
            asyncio.create_task(self.reclaim_nick())

    def on_disconnect(self, _client, event):
        self._log.warning("Disconnected from IRC")
        self._joined = False
        self._connected_event.clear()
        if self._pinger_task:
            self._pinger_task.cancel()

        if self._reconnect:
            # Start a task to reconnect us.
            asyncio.create_task(self.connect())

    def _left(self, nick):
        # If we left the channel, rejoin.
        if nick == self._nickname:
            self._joined = False
            self._connected_event.clear()
            self._client.join(self._channel)
            return

    async def _pinger(self):
        while True:
            await asyncio.sleep(120)
            self._client.ping("keep-alive")

    async def _idle_timeout_task(self):
        await asyncio.sleep(self._idle_timeout)

        self._reconnect = False
        self._client.disconnect("User went offline on Discord a while ago")
        await self._remove_puppet_func()

    async def reclaim_nick(self):
        # We sleep for a second, as it turns out, if we are quick enough to change
        # our name back, we win from people trying to reclaim their nick. Not the
        # nicest thing to do.
        await asyncio.sleep(1)

        self._nickname = self._nickname_original
        self._nickname_iteration = 0
        self._client.nick(self._nickname)

    async def connect(self):
        local_addr = (str(self._ipv6_address), 0)
        use_ssl = self._irc_port == 6697

        while self._reconnect:
            # As per RFC, getaddrinfo() sorts IPv6 results in some complicated way.
            # In result, even if the IRC host has multiple IPv6 addresses listed,
            # we will pick almost always the same one. This gives unneeded pressure
            # on a single host, instead of distributing the load. So instead, we do
            # the lookup ourselves, and pick a random one.
            try:
                ipv6s = await self.loop.getaddrinfo(
                    self._irc_host,
                    None,
                    family=socket.AF_INET6,
                    type=socket.SOCK_STREAM,
                    proto=socket.IPPROTO_TCP,
                )
            except socket.gaierror:
                ipv6s = []

            if not ipv6s:
                self._log.warning("Failed DNS lookup, retrying in 5 seconds")
                # When we can't connect, try again in 5 seconds.
                await asyncio.sleep(5)
                continue

            irc_host_ipv6 = random.choice(ipv6s)[4][0]

            self._log.info(
                "Connecting to IRC from %s to %s (%s) ...", self._ipv6_address, self._irc_host, irc_host_ipv6
            )

            try:
                await self.connection.connect(
                    irc_host_ipv6,
                    self._irc_port,
                    self._nickname,
                    username=self._username,
                    # We force an IPv6 connection, as we need that for the puppet source address.
                    connect_factory=irc.connection.AioFactory(
                        family=socket.AF_INET6,
                        local_addr=local_addr,
                        ssl=use_ssl,
                        server_hostname=self._irc_host if use_ssl else None,
                    ),
                )
                break
            except ConnectionRefusedError:
                self._log.warning("Connection refused, retrying in 5 seconds")
                # When we can't connect, try again in 5 seconds.
                await asyncio.sleep(5)

    async def start_idle_timeout(self):
        await self.stop_idle_timeout()
        self._idle_task = asyncio.create_task(self._idle_timeout_task())

    async def stop_idle_timeout(self):
        if not self._idle_task:
            return

        self._idle_task.cancel()
        self._idle_task = None

    async def _reset_idle_timeout(self):
        if not self._idle_task:
            return

        # User is talking while appearing offline. Constantly reset the idle timeout.
        await self.stop_idle_timeout()
        await self.start_idle_timeout()

    def is_offline(self):
        return self._idle_task is not None

    async def send_message(self, content):
        await self._reset_idle_timeout()

        await self._connected_event.wait()
        self._client.privmsg(self._channel, content)

    async def send_action(self, content):
        await self._reset_idle_timeout()

        await self._connected_event.wait()
        self._client.action(self._channel, content)
