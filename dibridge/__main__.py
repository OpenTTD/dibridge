import click
import ipaddress
import logging
import threading

from openttd_helpers import click_helper
from openttd_helpers.logging_helper import click_logging
from openttd_helpers.sentry_helper import click_sentry

from . import discord
from . import irc

log = logging.getLogger(__name__)


@click_helper.command()
@click_logging  # Should always be on top, as it initializes the logging
@click_sentry
@click.option("--discord-token", help="Discord bot token to authenticate.", required=True)
@click.option("--discord-channel-id", help="Discord channel ID to relay to.", required=True, type=int)
@click.option("--irc-host", help="IRC host to connect to.", required=True)
@click.option("--irc-port", help="IRC SSL port to connect to.", default=6697, type=int)
@click.option("--irc-nick", help="IRC nick to use.", required=True)
@click.option("--irc-channel", help="IRC channel to relay to.", required=True)
@click.option("--irc-puppet-ip-range", help="An IPv6 CIDR range to use for IRC puppets. (2001:A:B:C:D::/80)")
def main(discord_token, discord_channel_id, irc_host, irc_port, irc_nick, irc_channel, irc_puppet_ip_range):
    if irc_puppet_ip_range:
        irc_puppet_ip_range = ipaddress.ip_network(irc_puppet_ip_range)
        if irc_puppet_ip_range.num_addresses < 2**48:
            raise Exception("--irc-puppet-ip-range needs to be an IPv6 CIDR range of at least /80 or more.")

    thread_d = threading.Thread(target=discord.start, args=[discord_token, discord_channel_id])
    thread_i = threading.Thread(
        target=irc.start, args=[irc_host, irc_port, irc_nick, f"#{irc_channel}", irc_puppet_ip_range]
    )

    thread_d.start()
    thread_i.start()

    thread_d.join()
    thread_i.join()


if __name__ == "__main__":
    main(auto_envvar_prefix="DIBRIDGE")
