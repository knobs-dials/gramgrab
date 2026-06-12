# gramgrab

Telegram backup and OSINT tool.

Lets you fetch messages and media, and do some analysis.

It stores fetched data into a local database,
and can continue previous fetches.

<!--
There are other tools like this - this one was written 
while trying to learn another tool like it.
-->


## Notes on speed (and abuse)

It is your responsibility to comply to the [Telegram API ToS](https://core.telegram.org/api/terms). 
Also consider consent for non-public channels.

This tool does not send anything, so you won't get your account banned for spamming.

Telegram still cares that we don't load their servers more than is reasonable, and will occasionally ask us to slow down. This code respects those requests, attempting to balance it with speed.

What you request as a user also has an effect on this, in that different kinds of fetches count differently.   For example:
- fetching just messages is relatively cheap and fast
- fetching media is somewhat slower
- fetching full user details is slower yet, and seems to trigger the 'please slow down' more easily



## Install

- We plan to put this on pypi, which would install `gramgrab` and `gramparse` commands into your environment

- If you want to run the development code from github, then assuming you use [poetry](https://python-poetry.org/docs/),
  - `git clone` this repository
  - run `poetry install` to have it set up the virtual environment
  - after that you can run the main two commands, `poetry run gramgrab -h` and `poetry run gramparse -h`


## Login

You will need

- to supply an API ID and API hash.
  This is not authentication, it is a pair of values that is generally meant to identify to telegram that you are a specific software client.
  For singular uses like this it becomes just a necessary step, to create one and fill it in.
  See https://core.telegram.org/api/obtaining_api_id

- your account's phone number

- to authenticate the way your account is already configured for
  The likeliest for you to use is password or code, both seem to work well - though require some interaction.   Further auth methods that require graphical interaction are currently not implemented.


More concretely
- you would set the environment variables `TELEGRAM_API_ID`,  `TELEGRAM_API_HASH`, and `TELEGRAM_PHONENUM`. 
  We pick up `.env` contents so it might save you some time to put them in there.

- The library saves a token (in the `.session` file) that means that on successive runs, you do not need to supply any of that.

> [!WARNING]  
> Avoid sharing the `gramgrab.session` file, and `.env` file if you use it



## Telling it what to fetch

Note that the session and fetched data will both be stored in the current directory,
to to reuse the same session, continue the fetching from before, and extract from what you've fetched before,
run repeat fetches (and the reader) from the same directory.

The fetching is done with `gramgrab`.  Add `-h` for some options.


### On channel references

The minimum you need to supply is `--ch`, to specify a channel (or chat) to fetch from.

For public channels, its name is probably easiest, its ID will also work.

To fetch IDs for private chats/channels you are a member of, you can use `--list-my-dialogs`

<!--
this lets you refer to things you do not currently have access to, which will resolve fine, but not do anything else


Because Chats, Channels, and Users all are separately assigned (32-bit) pools,
IDs may exist in each.

As such, external-facing IDs are put into a larger range where they do not, where
-100xxxxxxxx are channel ids, 
negative _without_ the 100 is chats,
and positive is users positive is users

Telegram, telethon, and our code add a little flexibility, which means that even if you hand in the internal IDs it ''might'' work, but ther are rough edges to this.
-->


### Backup

By default, we fetch only messages - this is cheap and fast.

The options for basic use include:
- `--fetch-media` - whether to also fetch the media (specifically images and documents) attached to the messages we fetch


As we can continue previous fetches,
things related to messages that are _optional_ to fetch (e.g. media, reaction list) won't necessarily be fetchable later.
So decide what you need before you start.


### Advanced

For more OSINT-like applications, we provide some extras

- we always save that users have been seen posting messages - it's implied from the message data anyway

- you can optionally add users we have seen do emoji reactions to messages: see `--users-from-reaction`

- `--fetch-full-users`    - also try to do a full user fetch for every user we see.



## Read out what you have fetched

### Backup

If you've fetched things for backup you may want to export what we've fetched. You may be mostly interested in: `gramparse --messages-jsonl --media-save`


### Advanced

If you've fetched for OSINT use you want some analysis.

This is work in progress, see `gramparse -h`


<!--

## Questions

### "Can you parallelize it?"

For speed?  There would be no point.
Your account is rate-limited by the telegram servers, and nothing you do client-side changes that.


### "Why save media in the database, not files?"

There are a few things we can do slightly more easily while we haven't separated the file data from the information of where it came from. Not a lot, though.

You can save all with `grabparse --media-save`
-->