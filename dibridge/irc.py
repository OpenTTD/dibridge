import asyncio
import irc.client_aio
import functools
import hashlib
import logging
import re
import sys
import time

from openttd_helpers.asyncio_helper import enable_strong_referenced_tasks

from .irc_puppet import IRCPuppet
from . import relay

log = logging.getLogger(__name__)

# When a user on IRC was talking but left within 10 minutes, announce
# this on Discord. This to prevent Discord users thinking they can still
# talk to someone if they are in an active conversation with them.
LEFT_WHILE_TALKING_TIMEOUT = 60 * 10

# By RFC, only these characters are allowed in a nickname.
REGEX_NICKNAME_FILTER = r"[^a-zA-Z0-9_\-\[\]\{\}\|]"
# By RFC, a nickname cannot start with a number or a dash.
REGEX_NICKNAME_START_FILTER = r"^[0-9\-]+"
# By implementation, a username is more strict than a nickname in what
# it can start with. This filter is in addition to the nickname filters.
REGEX_USERNAME_START_FILTER = r"^[_\[\]\{\}\|]+"


class IRCRelay(irc.client_aio.AioSimpleIRCClient):
    def __init__(self, host, port, nickname, channel, puppet_ip_range, puppet_postfix, ignore_list, idle_timeout):
        irc.client.SimpleIRCClient.__init__(self)

        self._loop = asyncio.get_event_loop()

        self._host = host
        self._port = port
        self._nickname = nickname
        self._nickname_original = nickname
        self._nickname_iteration = 0
        self._joined = False
        self._tell_once = True
        self._channel = channel
        self._puppet_ip_range = puppet_ip_range
        self._puppet_postfix = puppet_postfix
        self._pinger_task = None
        self._ignore_list = ignore_list
        self._idle_timeout = idle_timeout

        # List of users when they have last spoken.
        self._users_spoken = {}

        self._puppets = {}

    def on_nicknameinuse(self, client, event):
        # Nickname is already in use, start adding numbers at the end to fix that.
        self._nickname_iteration += 1
        self._nickname = f"{self._nickname_original}[{self._nickname_iteration}]"
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

    def on_pubmsg(self, _, event):
        if event.target != self._channel:
            return
        if event.source.nick.lower() in self._ignore_list:
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

            relay.DISCORD.update_presence(f"{self._channel} on IRC")

    def on_part(self, _client, event):
        if event.target != self._channel:
            return
        self._left(event.source.nick)

    def on_kick(self, _client, event):
        if event.target != self._channel:
            return
        self._left(event.arguments[0])

    def on_quit(self, _client, event):
        self._left(event.source.nick)

    def on_disconnect(self, _client, event):
        log.error("Disconnected from IRC")
        self._joined = False
        if self._pinger_task:
            self._pinger_task.cancel()

        # Start a task to reconnect us.
        asyncio.create_task(self._connect())

    def _left(self, nick):
        # If we left the channel, rejoin.
        if nick == self._nickname:
            self._joined = False
            self._client.join(self._channel)
            return

        # If the user spoken recently, show on Discord the user left.
        if self._users_spoken.get(nick, 0) > time.time() - LEFT_WHILE_TALKING_TIMEOUT:
            self._users_spoken.pop(nick)
            relay.DISCORD.send_message(nick, "_left the IRC channel_")

    async def _pinger(self):
        while True:
            await asyncio.sleep(120)
            self._client.ping("keep-alive")

    async def _connect(self):
        while True:
            # Additional constraints usernames have over nicknames.
            username = re.sub(REGEX_USERNAME_START_FILTER, "", self._nickname)

            try:
                await self.connection.connect(
                    self._host,
                    self._port,
                    self._nickname,
                    username=username,
                    connect_factory=irc.connection.AioFactory(ssl=self._port == 6697),
                )
                break
            except ConnectionRefusedError:
                log.warning("Connection refused, retrying in 5 seconds")
                # When we can't connect, try again in 5 seconds.
                await asyncio.sleep(5)

    async def _send_message(self, discord_id, discord_username, message, is_action=False):
        # If we aren't connected to IRC yet, tell this to the Discord users; but only once.
        if not self._joined:
            if self._tell_once:
                self._tell_once = False
                relay.DISCORD.send_message_self(
                    ":warning: IRC bridge isn't active; messages will not be delivered :warning:"
                )
            return

        if not self._puppet_ip_range:
            if is_action:
                message = f"/me {message}"
            self._client.privmsg(self._channel, f"<{discord_username}>: {message}")
            return

        if discord_id not in self._puppets:
            sanitized_discord_username = self._sanitize_discord_username(discord_username)
            ipv6_address = self._puppet_ip_range[self._generate_ipv6_bits(sanitized_discord_username)]

            irc_nickname = f"{sanitized_discord_username}{self._puppet_postfix}"
            irc_username = re.sub(REGEX_USERNAME_START_FILTER, "", irc_nickname)

            self._puppets[discord_id] = IRCPuppet(
                self._host,
                self._port,
                ipv6_address,
                irc_nickname,
                irc_username,
                self._channel,
                functools.partial(self._remove_puppet, discord_id),
                self._idle_timeout,
            )
            asyncio.create_task(self._puppets[discord_id].connect())

        if is_action:
            await self._puppets[discord_id].send_action(message)
        else:
            await self._puppets[discord_id].send_message(message)

    async def _relay_mesage(self, irc_username, message):
        for discord_id, puppet in self._puppets.items():
            # Don't echo back talk done by our puppets.
            if puppet._nickname == irc_username:
                return

            # If the username is said as its own word, replace it with a Discord highlight.
            message = " ".join(
                [
                    (
                        re.sub(r"(?<!\w)" + re.escape(puppet._nickname) + r"(?!\w)", f"<@{discord_id}>", part)
                        if "://" not in part
                        else part
                    )
                    for part in message.split(" ")
                ]
            )

            # On IRC, it is common to do "name: ", but on Discord you don't do that ": " part.
            if message.startswith(f"<@{discord_id}>: "):
                message = f"<@{discord_id}> " + message[len(f"<@{discord_id}>: ") :]

        self._users_spoken[irc_username] = time.time()
        relay.DISCORD.send_message(irc_username, message)

    def _sanitize_discord_username(self, discord_username):
        original_discord_username = discord_username

        discord_username = discord_username.strip()
        # Remove all characters not allowed in IRC nicknames.
        discord_username = re.sub(REGEX_NICKNAME_FILTER, "", discord_username)
        # Make sure a nicknames doesn't start with an invalid character.
        discord_username = re.sub(REGEX_NICKNAME_START_FILTER, "", discord_username)

        # On Discord you can create usernames that don't contain any character valid
        # on IRC, leaving an empty username. In that case we have no option but to
        # replace it with a default placeholder. To make sure the names are somewhat
        # stable over multiple runs, we use a partial of the SHA256 of the original
        # discord name. It is not perfect, but at least it is better than nothing.
        if discord_username == "":
            postfix = hashlib.sha256(original_discord_username.encode()).hexdigest()
            discord_username = f"discord_user_{postfix[0:8]}"

        # Make sure a username is no more than 20 character.
        # Depending on the IRC network, different lengths are allowed.
        discord_username = discord_username[:20]
        return discord_username

    def _generate_ipv6_bits(self, discord_username):
        # Based on the Discord username, generate N bits to add to the IPv6 address.
        # This way we do not have to persistently store any information, but every user
        # will always have the same IPv6.
        # For the N bits, we simply take the last N bits from the SHA-256 hash of the
        # username. Chances on collision are really low.
        # N here is the length of the IPv6 range assigned.
        return (
            int(hashlib.sha256(discord_username.encode("utf-8")).hexdigest(), 16) % self._puppet_ip_range.num_addresses
        )

    async def _stop(self):
        sys.exit(1)

    async def _remove_puppet(self, discord_id):
        self._puppets.pop(discord_id)

    # Thread safe wrapper around functions

    def get_status(self):
        if self._joined:
            status = f":green_circle: **IRC** listening on `{self._host}` in `{self._channel}`\n"
        else:
            status = ":red_circle: **IRC** not connected\n"
        if self._puppets:
            joined = len([True for puppet in self._puppets.values() if puppet._joined])
            status += "\n"
            status += f"**{len(self._puppets)}** IRC connections, **{joined}** connected\n"
        return status

    def get_irc_username(self, discord_id, discord_username):
        if discord_id not in self._puppets:
            return self._sanitize_discord_username(discord_username)

        return self._puppets[discord_id]._nickname

    def update_status(self, discord_id, is_offline):
        if discord_id not in self._puppets:
            return

        if self._puppets[discord_id].is_offline() == is_offline:
            return

        if is_offline:
            # Start a timer to delete the puppet after timeout.
            asyncio.run_coroutine_threadsafe(self._puppets[discord_id].start_idle_timeout(), self._loop)
        else:
            # Stop the timer if the user comes back.
            asyncio.run_coroutine_threadsafe(self._puppets[discord_id].stop_idle_timeout(), self._loop)

    def send_message(self, discord_id, discord_username, message):
        asyncio.run_coroutine_threadsafe(self._send_message(discord_id, discord_username, message), self._loop)

    def send_action(self, discord_id, discord_username, message):
        asyncio.run_coroutine_threadsafe(
            self._send_message(discord_id, discord_username, message, is_action=True), self._loop
        )

    def stop(self):
        asyncio.run_coroutine_threadsafe(self._stop(), self._loop)


def start(host, port, name, channel, puppet_ip_range, puppet_postfix, ignore_list, idle_timeout):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    enable_strong_referenced_tasks(loop)

    relay.IRC = IRCRelay(host, port, name, channel, puppet_ip_range, puppet_postfix, ignore_list, idle_timeout)

    log.info("Connecting to IRC ...")
    asyncio.get_event_loop().run_until_complete(relay.IRC._connect())
    try:
        relay.IRC.start()
    finally:
        relay.IRC.connection.disconnect()
        relay.IRC.reactor.loop.close()
