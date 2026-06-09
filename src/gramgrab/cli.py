
import os
import argparse
import collections
import asyncio
import json
import pprint

import gramgrab


import time, datetime

## Helpers to massage data for JSON to be happy
# This is pretty crude and makes assumptions about the data structure,
# mostly that nested is either dicts or lists including dicts

def dict_dt_replace_inplace(d, isolike:bool=True):
    """ Takes a dict,
        does an in-place replacement of datetime, with either an ISO8601-like string, or a unix timestamp float.

    """
    for k, v in d.items():
        if isinstance(v, dict):
            dict_dt_replace_inplace(v, isolike=isolike)
        if isinstance(v, list):
            for th in v:
                if isinstance(th, dict):
                    dict_dt_replace_inplace(th)
        elif isinstance(v, datetime.datetime):
            if isolike:
                d[k] = v.strftime('%Y-%m-%dT%H:%M:%S%z')                 # ISO8601-like
            else:
                d[k] = time.mktime(v.timetuple()) + (1e-6)*v.microsecond # unix timestamp


def dict_byteval_remove_inplace(d):
    keys_to_remove = []
    for k, v in d.items():
        if isinstance(v, dict):
            dict_byteval_remove_inplace(v)
        if isinstance(v, list):
            for th in v:
                if isinstance(th, dict):
                    dict_byteval_remove_inplace(th)
        elif isinstance(v, bytes):
            keys_to_remove.append(k)
    for rk in keys_to_remove:
        d.pop(rk)

#test = {
#    'd':'',
#    'b':b'',
#    'a':datetime.datetime.now(),
#    1:{'d':datetime.datetime.now(),'q':b'q'},
#}
#dict_byteval_remove_inplace(test)
#test
#
#dict_dt_replace_inplace(test, False)
#test



async def fetcher_work():    

    ## Argument parsing and
    parser = argparse.ArgumentParser(
            description="Telegram OSINT and backup tool",
            #usage="%(prog)s [options] pdf_file",
        )

    parser.add_argument(
        "--ch",
        default=[],
        action='append',
        help="Chat or channel to use. Can be repeated.",
    )

    parser.add_argument(
        "--message-limit", 
        default=None,
        type=int,
        help="Fetch at most this many messages in one run. Useful to be more gentle, and during debugging. Default is no limit.",
    )

    parser.add_argument(
        "--fetch-media", 
        default=False,
        action='store_true',
        help="Whether to fetch stored media while iterating messages (image and document only). Takes a moderate amount of time. Default it not to fetch.",
    )

    #parser.add_argument(
    #    "--fetch-media-catchup", 
    #    default=False,
    #    action='store_true',
    #    help="Whether to also fetch stored media we know exists on already fetched messages, but did not fetch at the time.",
    #)

    #parser.add_argument(
    #    "--users-from-posts", 
    #    default=False,
    #    action='store_true',
    #    help="Whether to recording seeing users on messages we fetched",
    #)

    parser.add_argument(
        "--users-from-reactions", 
        default=False,
        action='store_true',
        help="Whether to record seeing users from (emoji) reactions to the messages, while fetching messages. Takes more requests and a little more time. Default is not to do so.",
    )

    parser.add_argument(
        "--fetch-full-users",
        default=False,
        action='store_true',
        help="Whether to also fetch full user info for every new user we see. Takes a bunch of time.  Default is not to do so.",
    )

    #parser.add_argument(
    #    "--fetch-full-users-catchup",
    #    default=False,
    #    action='store_true',
    #    help="",
    #)

    # Just an idea right now:
    #parser.add_argument(
    #    "--fetch-full-channels-catchup",
    #    default=False,
    #    action='store_true',
    #    help="",
    #)

    parser.add_argument('-v', '--verbose', action='count', default=0)


    args = parser.parse_args()

    channel_refs = args.ch
    #print(args)


    if len(args.ch) == 0:
        raise ValueError("No channel specified")

    if args.verbose==0:
        print("INFO supply -v argument if you want to see updates while fetching")


    ## Get account details into environment, if it's there    
    # from .env if possible
    try:
        import dotenv
        if dotenv.load_dotenv():
            print('INFO loaded .env file')
    except ImportError as e:
        print('WARN skipping dotenv - %s'%e, file=sys.stderr)

    TELEGRAM_API_ID   = os.environ.get('TELEGRAM_API_ID')
    TELEGRAM_API_HASH = os.environ.get('TELEGRAM_API_HASH')
    TELEGRAM_PHONENUM = os.environ.get('TELEGRAM_PHONENUM')
    # warning: you probably don't want to print those, in case you ever share this

    if TELEGRAM_API_ID is None: #  or  TELEGRAM_PHONENUM is None:
        raise ValueError('Did not get get login details from environment') # A nicer error than we'd otherwise get



    ## connect
    async with gramgrab.EasyConnect(TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONENUM) as ec:

        ## resolve channel references (id or name) to entities
        channel_entities = [] # TODO: make dict so we don't add the same thing twice?
        for ch_ref in channel_refs:
            print('INFO getting peer entity for %r'%ch_ref)

            try:
                int(ch_ref)
                ch_ent = await ec.client.get_entity( int(ch_ref))
                print("INFO given chat/channel reference that looks like an integer, resolved to %s"%(await gramgrab.interesting_keys(ch_ent),))
            except ValueError: # not integer
                ch_ent = await ec.client.get_entity(ch_ref)

            channel_entities.append( ch_ent )

            ## See if there is a linked channel to add   (broadcast <--> discussion)
            if True: # TODO: parameter also_linked_chat
                #print('INFO checking for linked channel')
                ch_details = await gramgrab.full_entity_details(ec.client, ch_ent)
                fullch = ch_details['full_chat']
                if 'linked_chat_id' in fullch: # not true for Chats
                    linked_chat_id = fullch['linked_chat_id'] # TODO: check this is always valid
                    if linked_chat_id is not None:
                        print( f"INFO this (id={ch_ent.id}, broadcast={ch_ent.broadcast}, megagroup={ch_ent.megagroup}) has a linked_chat_id ({linked_chat_id}), you might care for that." )
                        #chans.append( await ec.client.get_entity(linked_chat_id) ) # TODO: is that correct or should we instantiate it directly?
                        #ch_details = await gramgrab.full_entity_details(ec.client, await ec.client.get_entity(linked_chat_id) )


        ## actual fetching work
        for ch in channel_entities:
            print(f"\n======= {ch.id} - {ch.title} =======") # TODO: check that Channel and Chat both have a .title

            #ik = await gramgrab.interesting_keys(ch)
            #pprint.pprint(ik)
            #print( f"FETCHING for channel {ik}" )
            fetcher = gramgrab.SQLiteFetcher( 
                ec.client,
                ch,
                'gramgrab.db',
                fetch_message_limit  = args.message_limit,
                fetch_media          = args.fetch_media,
                users_from_posts     = True, #args.users_from_posts,
                users_from_reactions = args.users_from_reactions,
                fetch_full_users     = args.fetch_full_users,
                debug=args.verbose )
            try:
                await fetcher.fetch_messages()
            finally:
                await fetcher.db_close( commit=True ) # get the journal merged earlier rather than later

            if fetcher.debug >= 1:
                for what, howmuch in fetcher.time_spent_in.items():
                    print( f'INFO spent {howmuch:5.1f} seconds in {what}' )






async def reader_work():    

    parser = argparse.ArgumentParser(
        description="Telegram OSINT and backup tool - things to do on the fetched data.",
    )

    parser.add_argument(
        "--count",
        default=False,
        action='store_true',
        help="count what we have fetched",
    )

    parser.add_argument(
        "--edgelists",
        default=False,
        action='store_true',
        help="save edgelists to edgelists/(id).",
    )

    parser.add_argument(
        "--users-in-multiple-channels",
        default=False,
        action='store_true',
        help="Save media to media/",
    )

    parser.add_argument(
        "--media-postlist",
        default=False,
        action='store_true',
        help="",
    )

    parser.add_argument(
        "--media-save",
        default=False,
        action='store_true',
        help="Save media to media/",
    )

    parser.add_argument(
        "--full-users-jsonl",
        default=False,
        action='store_true',
        help="Save user data, one at a time (JSONL to stdout)",
    )

    parser.add_argument(
        "--channel-details-jsonl",
        default=False,
        action='store_true',
        help="Save channel data, one at a time (JSONL to stdout)",
    )

    # media post report / crosspost report 

    args = parser.parse_args()


    async with gramgrab.SQLiteReader('gramgrab.db') as reader:

        if args.count:
            print('Counting what we have...')
            pprint.pprint( await reader.db_counts_all() )


        if args.edgelists:
            print('creating edge lists')
            # edgelist, as in the other chats a message was forwarded from - meant to find related chats

            chan_detail = {}
            for dt, chid, data in await reader.db_channel_details(): # we will get multiple per channel, but any one will do
                chan_detail[chid] = data

            for chid in await reader.db_message_channels(): # sort of an order by
                #print(' -- %s -- '%chid)
                #print( chan_detail.get(chid,None).get('title') )

                for in_chid, msgid, data in await reader.db_messages_all(chid=chid):
                    #print()
                    #pprint.pprint(data)
                    to_channel_title = gramgrab.getget( chan_detail, in_chid,'title')

                    fwd_from = data.get('fwd_from', None)
                    if fwd_from is not None:
                        from_id = fwd_from.get('from_id', None)
                        if from_id is not None: # is that even possible?
                            
                            if 'channel_id' in from_id: # implicitly filters just for PeerChannel (...sources)
                                from_channel_id = from_id['channel_id']
                                from_channel_title = gramgrab.getget( chan_detail, from_channel_id,'title') # which we often do not know
                                #print("post from ch=%s (%s) posted to ch=%s (%s)"%(
                                #    from_channel_id, from_channel_title,
                                #    in_chid,         to_channel_title,
                                #)) 
                            print( json.dumps({'from_chid':from_channel_id, 'from_title':from_channel_title,   'to_chid':in_chid, 'to_title':to_channel_title, 'to_msgid':msgid}) )
                                

                    

        if args.users_in_multiple_channels:
            print('Summarizing users in multiple channels')

            user_details = {}
            for recorded_at, uid, data in await reader.db_user_full():
                user_details[uid] = data

            channel_details = {}
            for dt, chid, data in await reader.db_channel_details():
                channel_details[chid] = data

            user_mention_data = collections.defaultdict( lambda: collections.defaultdict(list) ) # { uid -> { chid -> [ (msgid,data) ] } }
            for dt, uid, chid, msgid, data in await reader.db_user_mentions_all():
                user_mention_data[uid][chid].append( (msgid, data) )

            for uid, inchandict in user_mention_data.items():
                if len(inchandict) > 1:
                    print(f"User {uid} seen in multiple channels:")
                    print('  user details: ', await gramgrab.interesting_keys( gramgrab.getget( user_details, uid, 'data') ) )
                    for chid, msg_data in inchandict.items():
                        #print( '   in channel: ', chid, channel_details.get(chid, None) )
                        print( '  in channel:   ', await gramgrab.interesting_keys( channel_details.get(chid, None) ) )
                        #print( '    mentions:   ', getget(umd, uid, chid) )


        if args.full_users_jsonl:
            print('Summarizing users in multiple channels (note: includes duplicates)')

            for recorded_at, uid, data in await reader.db_user_full():
                dict_dt_replace_inplace(     data )
                dict_byteval_remove_inplace( data ) # mostly image data anyway
                print( json.dumps(data) )


        if args.channel_details_jsonl:
            for dt, chid, data in await reader.db_channel_details():
                dict_dt_replace_inplace(     data )
                dict_byteval_remove_inplace( data ) # mostly image data anyway
                print( json.dumps(data) )
                

        #if args.all_messages_jsonl:
        #    pass


        if args.media_postlist:
            print('saving list of media hashes that were posted in different channels')
            
            ## With message it was on 
            #count = collections.defaultdict(list)
            #messages_with_media = await reader.db_media_list()
            #for chid, msgid, sha1hash in messages_with_media:
            #    count[sha1hash].append( (chid, msgid) )
            #for sha1hash, l in count.items():
            #    if len(l) > 1:
            #        for chid, msgid in l:
            #            print(f'{sha1hash}\t{chid}\t{msgid}') # maybe add channel title

            ## Just mention it was posted
            count = collections.defaultdict(set)
            messages_with_media = await reader.db_media_list()
            for chid, msgid, sha1hash in messages_with_media:
                count[sha1hash].add( chid )
            for sha1hash, l in count.items():
                if len(l) > 1:
                    for chid in l:
                        print(f'{sha1hash}\t{chid}') # maybe add channel title


        if args.media_save:
            print('saving media')

            if not os.path.exists('media'):
                os.mkdir('media')

            messages_with_media = await reader.db_media_list()
            print(f'INFO about to save {len(messages_with_media)} media files')
            for chid, msgid in messages_with_media:
                suggested_path, data = await reader.db_media_formessage(chid, msgid)
                if data is not None:
                    print( chid, msgid, suggested_path, len(data) )

                    #CONSIDER: sanitize suggested_path (it comes from our own code, though)
                    #TODO: have fallback for when suggested_path is empty
                    write_path = os.path.join( 'media', suggested_path )
                    if os.path.exists( write_path ):
                        print("WARN: refusing to ovewrite %r"%write_path)
                    else:
                        with open( write_path, 'wb' ) as f:
                            f.write( data )


def reader_main():
    import asyncio
    asyncio.run( reader_work() )

def fetcher_main():
    asyncio.run( fetcher_work() )

