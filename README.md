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

- [ ] Allow binding to different IPv6 address for each IRC puppet.
- [ ] Disconnect IRC puppet if it hasn't seen activity for 7 days.
- [ ] Set IRC status to away if user goes offline on Discord.
- [ ] Show IRC joins if the user talked recently, left, but came back.
- [ ] Validate all Discord messages are handled properly.
- [ ] Validate all IRC messages are handled properly.
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
