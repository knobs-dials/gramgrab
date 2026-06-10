# gramgrab

Telegram backup and OSINT tool.

Lets you fetch messages and media, and do some analysis.

It stores fetched data into a local database,
and can continue previous fetches.

<!--
There are other tools like this - this one was written 
while trying to learn another tool like it.
-->


## Notes on speed

[As telethon notes](https://github.com/LonamiWebs/Telethon?tab=readme-ov-file), it is your responsibility to use things in a way that adheres to the [Telegram API ToS](https://core.telegram.org/api/terms).

This tool does not send anything, so you won't get your account banned for spamming, but telegram still cares that we don't load their servers more than is reasonable, and will occasionally ask us to slow down. This code respects those requests, attempting to balance it with speed.

You as a user have some effect on this, in that different kinds of fetches count differently. 
For example:
- fetching messages is relatively cheap and fast
- fetching media slows us down, partly just because of the extra work.
- fetching full user details is slower and seems to trigger the 'please slow down' more easily



## Use



### Install

- We plan to put this on pypi, which would install `gramgrab` and `gramparse` commands into your environment

- If you want to run the github code, then assuming you use [poetry](https://python-poetry.org/docs/),
  - `git clone` this repository
  - run `poetry install` to have it set up the virtual environment
  - after that you can e.g. `poetry run gramparse -h`



### Login

You will need

- to supply an API ID and API hash.
  This is not authentication, it generally meant to identify specific software clients.
  To us it's just a necessary step to create one and use it.
  See https://core.telegram.org/api/obtaining_api_id

- your account's phone number

These are expected to be in environment variables `TELEGRAM_API_ID`,  `TELEGRAM_API_HASH`, and `TELEGRAM_PHONENUM`. It might save you some time to put those in a `.env` file, we pick that up.


Your account's usual login method is used. 
The likeliest for you to use is password or 2FA code, both seem to work well.
Some things that require graphical interaction currently do not.

Tje library saves a token that means you should not need to authenticate every run.

Avoid sharing the `gramgrab.session` file, and `.env` file if you use it


### Telling it what to fetch

NOTE: Session and fetched data will be stored in the current directory, so run it from the same directory every time.


The fetching is done with `gramgrab`. Add `-h` for some help.

The minimum you need to supply is `--ch`, to specify a channel to fetch, by public name or ID.

By default, we fetch only messages - this is cheap and fast.

Because we can continue previous fetches, 
things related to messages that are _optional_ to fetch (e.g. media, reaction list) 
won't necessarily be fetchable later. So decide what you need before you start.

The options for basic use include:
- `--fetch-media` - whether to also fetch the media (specifically images and documents) attached to the messages we fetch


For more OSINT-like applications, we have some extras
- we always save that users have been seen posting messages - it's implied from the message data anyway
- you can optionally add users we have seen do emoji reactions to messages: see `--users-from-reaction`
- `--fetch-full-users`    - also try to do a full user fetch for every user we see.



## Read out what you have fetched

If you've fetched things for backup,
you may want to export what we've fetched.

If you've fetched for OSINT use,
you want some analysis.

<!--

`gramparse`
-->



## Questions
<!--
### "What exactly should I hand into --ch?"

Whatever works, but most use cases can use public channel names.

Telegram, telethon, and our code add a little flexibility, which means you can also use IDs.
You generally should not need to, and there are a few rough edges to this.


### "Can you parallelize it?"

For speed?  There would be no point.
Your account is rate-limited by the telegram servers, and nothing you do client-side changes that.


### "Why save media in the database, not files?"

There are a few things we can do more easily while we haven't separated the file data from the metadata of where it came from. Not a lot, though.

You can save all with `grabparse --media-save`
-->

<!-->
## TODO:

- We make one ugly assumption about peer IDs that should be rewritten, because that will break some future expansion.

- Properly share database code between the fetching and readout

- tests

-->