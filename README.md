# gramgrab

Telegram backup and OSINT tool.

Lets you fetch messages and media, and do some analysis.

This tool was written while trying to learn another tool like it.


It stores fetched data into a local database,
and can continue previous fetches.



## Notes on speed

[As telethon notes](https://github.com/LonamiWebs/Telethon?tab=readme-ov-file),
it is your responsibility to use the library in a way that adheres to the [Telegram API ToS](https://core.telegram.org/api/terms).

This tool does not send anything, so you won't get your account banned for spamming,
but telegram still cares that we don't load their servers more than is reasonable,
and will occasionally ask us to slow down. This code respects those requests,
balancing it with decent speed.

You as a user have some effect on this, in that different kinds of fetches count differently. 
For example:
- fetching messages is relatively cheap and fast
- fetching media slows us down, partly just because of the extra work.
- fetching full user details is slower and seems to trigger the 'please slow down' more easily



## Use


### Login

You will need

- to supply an API ID and API hash.
  This is not authentication, it generally meant to identify specific software clients.
  To us it's just a necessary step to create one and use it.
  See https://core.telegram.org/api/obtaining_api_id

- your account's phone number

Your account's usual login method is used. 
The likeliest for you to use is password or 2FA code, both seem to work well.
Some things that require graphical interaction currently do not.

It saves a token that means you should not need to authenticate every run.

WARNING: avoid share the `.session` file, for that reason.


### Telling it what to fetch

By default, we fetch message details, and also note down users we have seen post messages.

`gramgrab`

- `--ch`                  - specify chat/channel to fetch, by public name, or by its ID.
- `--fetch-media`         - also fetch attached media (specifically images and documents)
- `--users-from-reaction` - whether to also note down users we have seen do emoji reactions
- `--fetch-full-users`    - also try to do a full user fetch for every user we see.


Note that
- we store messages as we read them, so we can continue fetching without double work
- anything we can optionally fetch on a message (e.g. media, reaction list) won't necessarily be fetchable later. Decide what you need before you start.


## Read out what you have fetched

TODO
<!--

`gramparse`
-->



## Questions

### "What exactly should I hand into --ch?"

Whatever works, but most use cases can use public channel names.

Telegram, telethon, and our code add a little flexibility, which means you can also use IDs.
You generally should not need to, and there are a few rough edges to this.


### "Can you parallelize it?"

For speed?  There would be no point.
Your account is rate-limited by the server, and nothing you do client-side changes that.


