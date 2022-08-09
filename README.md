# dibridge: an Discord <-> IRC Bridge

Sometimes you have parts of your community that don't want to leave IRC.
But other parts are active on Discord.
What do you do?

Bridge the two!

This server logs in to both IRC and Discord, and forward messages between the two.

This server is very limited, as in: it only bridges a single Discord channel with a single IRC channel.
If you want to bridge multiple, you will have to run more than one server.

## Usage

```
Usage: python -m dibridge [OPTIONS]

Options:
  --sentry-dsn TEXT             Sentry DSN.
  --sentry-environment TEXT     Environment we are running in.
  --discord-token TEXT          Discord bot token to authenticate  [required]
  --discord-channel-id INTEGER  Discord channel ID to relay to  [required]
  --irc-host TEXT               IRC host to connect to  [required]
  --irc-port INTEGER            IRC port to connect to
  --irc-nick TEXT               IRC nick to use  [required]
  --irc-channel TEXT            IRC channel to relay to  [required]
  -h, --help                    Show this message and exit.
```

You can also set environment variables instead of using the options.
`DIBRIDGE_DISCORD_TOKEN` for example sets the `--discord-token`.
It is strongly advised to use environment variables for secrets and tokens.

## Development

```bash
python3 -m venv .env
.env/bin/pip install -r requirements.txt
.env/bin/python -m dibridge --help
```

## Why yet-another-bridge

OpenTTD has been using IRC ever since the project started.
As such, many old-timers really like being there, everyone mostly knows each other, etc.

On the other hand, it isn't the most friendly platform to great new players with questions, to share screenshots, etc.
Discord does deliver that, but that means the community is split in two.

So, we needed a bridge to .. bridge that gap.

Now there are several ways about this.

First, one can just close IRC and say: go to Discord.
This is not the most popular choice, as a few people would rather die on the sword than switch.
As OpenTTD, we like to be inclusive.
So not an option.

Second, we can bridge IRC and Discord, so we can read on Discord what is going on on IRC, and participate without actually opening an IRC client.
This is a much better option.

Now there are a few projects that already do this.
But all of them don't exactly fit our needs.

- https://github.com/qaisjp/go-discord-irc: awesome project and rather stable.
  But it has either of two modes:
  - Have a single user presence on IRC relaying everything.
  - Have every user on Discord present on IRC, each with their own connection.
  We like the second option, but there are thousands of users on Discord.
  This will not go well.
  This bridge solves that issue by only creating an IRC connection once someone talks in the Discord channel that is being bridged.
  That way, the amount of connections to IRC are reduced as much as possible.
- https://github.com/42wim/matterbridge: can truly connnect everything.
  But that is instantly the downfall: it connects everything.
  The complexity is just too high to maintain long-term.
  Additionally, it uses a single user presence on IRC.
- https://github.com/reactiflux/discord-irc: not sure if it is actually still supported, but otherwise looks mature.
  But, the main drawback: it doesn't use Discord's method of imitation a user, and instead uses a single user presence on Discord.
  That is really annoying really quick.

So after running out of existing options, it was time to build our own.
And this repository is a consequence of that action.

Codewise, thanks to the awesome [irc](https://github.com/jaraco/irc) and [discord.py](https://github.com/Rapptz/discord.py), it is relative trivial.
A bit ironic that the oldest of the two (IRC), is the hardest to implement.
