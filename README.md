# dibridge: an Discord <-> IRC Bridge

Sometimes you have parts of your community that don't want to leave IRC.
But other parts are active on Discord.
What do you do?

Bridge the two!

This server logs in to both IRC and Discord, and forward messages between the two.

This server is very limited, as in: it only bridges a single Discord channel with a single IRC channel.
If you want to bridge multiple, you will have to run more than one server.

## TODO-list

This software is currently in pre-alpha.
Here is a list of things that still needs doing:

- [ ] Disconnect IRC puppet if it hasn't seen activity for 7 days.
- [ ] Set IRC status to away if user goes offline on Discord.
- [ ] Show IRC joins if the user talked recently, left, but came back.
- [ ] Investigate IRC private messages, if we can relay them to Discord and back.

## Implementation

The idea behind this bridge is to be as native on Discord as on IRC.
That on both sides, it is hard to notice you are not talking to a native user.

For Discord, this means we use multi-presence.
Every IRC user gets its own Discord user to talk to you, including its own avatar.
Highlights on IRC, after you talked in the Discord channel, are converted to Discord highlights.
In other words, it looks and feels like you are talking to a Disord user.

For IRC, this also means we use multi-presence.
Once you said something in the Discord channel, an IRC puppet is created with your name, that joins the IRC network.
Highlights on Discord are converted to readable names on IRC, which you can use again to create a highlight on Discord.
In other words, it looks and feels like you are talking to an IRC user.

It is really important to make it feel as native as possible.
This with the goal that the IRC population doesn't think strange about this, and that the Discord population can just do their thing.

There are however some limitations:
- Edits on Discord are not send to IRC.
- Reactions on Discord are not send to IRC.
- This bridges a single Discord channel to a single IRC channel, and no more.
- On IRC you do not see who is online on Discord unless they said something.
- On Discord you do not see who is online on IRC unless they said something.

## Usage

```
Usage: python -m dibridge [OPTIONS]

Options:
  --sentry-dsn TEXT             Sentry DSN.
  --sentry-environment TEXT     Environment we are running in.
  --discord-token TEXT          Discord bot token to authenticate.  [required]
  --discord-channel-id INTEGER  Discord channel ID to relay to.  [required]
  --irc-host TEXT               IRC host to connect to.  [required]
  --irc-port INTEGER            IRC SSL port to connect to.
  --irc-nick TEXT               IRC nick to use.  [required]
  --irc-channel TEXT            IRC channel to relay to, without the first
                                '#'.  [required]
  --irc-puppet-ip-range TEXT    An IPv6 CIDR range to use for IRC puppets.
                                (2001:A:B:C:D::/80)
  --irc-ignore-list TEXT        IRC nicknames to not relay messages for (comma
                                separated, case-insensitive).
  --irc-idle_timeout INTEGER    IRC puppet idle timeout, in seconds (default:
                                2 days).
  -h, --help                    Show this message and exit.
```

You can also set environment variables instead of using the options.
`DIBRIDGE_DISCORD_TOKEN` for example sets the `--discord-token`.
It is strongly advised to use environment variables for secrets and tokens.

### Discord bot

This application logs in as a Discord bot to get a presence on Discord.
You have to create this bot yourself, by going to https://discord.com/developers/ and registering one.
The Discord token can be found under `Bot`.

After creating a bot, you need to invite this bot to your Discord channel.
If you are not the owner of that channel, you would need to make the bot `Public` before the admin can add it.
The bot needs at least `Send Messages`, `Read Messages` and `Manage Webhooks` permissions to operate in a channel.

Additionally, the bot uses the following intents:
- `messages`: to read messages.
- `guilds`: to read channel information.
- `presences`: to know when a user goes offline.
- `members`: to read member information.
- `message_content`: to read message content.

Some of these intents need additional permission on the bot's side, under `Privileged Gateway Intents`.
Without those, this application will fail to start.

### IRC Puppet IP Range

The more complicated setting in this row is `--irc-puppet-ip-range`, and needs some explaining.

Without this setting, the bridge will join the IRC channel with a single user, and relays all messages via that single user.
This means it sends things like: `<username> hi`.
The problem with this is, that it isn't really giving this native IRC feel.
Neither can you do `us<tab>` to quickly send a message to the username.

A much better way is to join the IRC channel with a user for every person talking on Discord.
But as most IRC networks do not allow connecting with multiple users from the same IP address (most networks allow 3 before blocking the 4th), we need a bit of a trick.

`--irc-puppet-ip-range` defines a range of IP address to use.
For every user talking on Discord, the bridge creates a new connection to the IRC channel with a unique IP address for that user from this range.

In order for this to work, you do need to setup a few things.
First of all, you need Linux 4.3+ for this to work.
Next, you need to have an IPv6 prefix, of which you can delegate a part to this bridge.

All decent ISPs these days can assign you an IPv6 prefix, mostly a `/64` or better.
We only need a `/80` for this, so that is fine.
Similar, cloud providers also offer assigning IPv6 prefixes to VMs.
For example [AWS allows you to assign a `/80` to a single VM](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-prefix-eni.html).

Next, you need to make sure that this prefix is forwarded to the machine you are hosting the bridge on.
For example:
```bash
ip route add local ${prefix} dev eth0
ip addr add local ${prefix} dev eth0
```

Where `${prefix}` is something like `2001:db8::/80`.
Please use a part of the prefix assigned by your ISP, and not this example.

Next, we need to tell the kernel to allow us to bind to IP addresses that are not local:
```bash
sysctl -w net.ipv6.ip_nonlocal_bind=1
```

And that is it.
Now we can call this bridge with, for example, `--irc-puppet-ip-range 2001:db8::/80`.
IRC puppets will now use an IP in that range.

And don't worry, the same Discord user will always get the same IPv6 (given the range stays the same).
So if they get banned on IRC, they are done.

## Development

```bash
python3 -m venv .env
.env/bin/pip install -r requirements.txt
.env/bin/python -m dibridge --help
```

### IRC server

To run a local IRC server to test with, one could do that with the following Docker statement:

```bash
docker run --rm --name irc --net=host -p 6667:6667 hatamiarash7/irc-server --nofork --debug
```

The `--net=host` is useful in case you want to work with IRC Puppets.
For example, one could add a local route for some random IPv6 addresses, and tell this bridge to use that to connect to the IRC server.
A typical way of doing this would be:

```bash
sysctl -w net.ipv6.ip_nonlocal_bind=1
ip route add local 2001:db8:100::/80 dev lo
```

(don't forget to use as `--irc-host` something that also resolves to a local IPv6, like `localhost`)

### Discord bot

To connect to Discord, one could register their own Discord bot, invite it to a private server, and create a dedicated channel for testing.

## Why yet-another-bridge

OpenTTD has been using IRC ever since the project started.
As such, many old-timers really like being there, everyone mostly knows each other, etc.

On the other hand, it isn't the most friendly platform to great new players with questions, to share screenshots, etc.
Discord does deliver that, but that means the community is split in two.

So, we needed to bridge that gap.

Now there are several ways to go about this.

First, one can just close IRC and say: go to Discord.
This is not the most popular choice, as a few people would rather die on the sword than switch.
And as OpenTTD, we like to be inclusive.
So not an option.

Second, we can bridge IRC and Discord, so we can read on Discord what happens on IRC, and participate without actually opening an IRC client.
This is a much better option.

Now there are a few projects that already do this.
For example:
- https://github.com/qaisjp/go-discord-irc
- https://github.com/42wim/matterbridge
- https://github.com/reactiflux/discord-irc

Sadly, most of those only support a single presence on IRC.
This is for our use-case rather annoying, as it makes it much more obvious that things are bridged.
As people on IRC can be grumpy, they will not take kind of that.
Additionally, things like user-highlighting etc won't work.

The first one on the list does support it, but in such way that is impractical: every user on Discord gets an IRC puppet.
That would be thousands of outgoing IRC connections.

For example Matrix does do this properly: when you join the channel explicitly, it creates an IRC puppet.

So, we needed something "in between".
And that is what this repository delivers.

Codewise, thanks to the awesome [irc](https://github.com/jaraco/irc) and [discord.py](https://github.com/Rapptz/discord.py), it is relative trivial.
A bit ironic that the oldest of the two (IRC), is the hardest to implement.
