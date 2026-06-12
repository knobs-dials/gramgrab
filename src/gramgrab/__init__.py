#!/usr/bin/python3
'''
    Don't consider the details to be stable yet.
'''

import os
import time
import getpass
import collections
import sqlite3
import pprint
import asyncio
import warnings
import hashlib

import msgpack
import telethon
import telethon.functions
import telethon.errors
import telethon.tl
import telethon.tl.types
import telethon.tl.functions
import telethon.tl.custom
import telethon.custom



######################## HELPER FUNCTIONS #######################################################################

def sha1_hex( data:bytes ):
    ' Calculates SHA-1 hash of in-memory data, returns as hexadecimal string '
    sha1h = hashlib.sha1()
    sha1h.update( data )
    return sha1h.hexdigest()


def internal2external(typ, id):
    # could check that id is in range
    if typ.lower() == 'channel':
        return -( 1000000000000 + id)
    elif typ.lower() == 'chat':
        return -id
    elif typ.lower() == 'user':
        return id


def external2internal(id):
    # these ranges could be better?
    if id < -1000000000000:
        return 'Channel', -(id+1000000000000)
    elif id < 0:
        return 'Chat', -id
    else:
        return 'User',id


async def dict_subset(dd, keys):
    """ Filter dict by keys, mostly supports 'get interesting subset of telegram object attributes'.
        
        @param dd: input dictionary
        @param keys: should be 
        - a list/tuple of keys to pass through, OR
        - True, for all
        @return: 
    """
    ret = {}
    for d_key, d_value in dd.items():
        if keys is True  or  d_key in keys:
            ret[d_key] = d_value
    return ret


async def interesting_keys(ob, simplify=True):
    """ Take a TL style object, use to_dict, and filter for only the keys we consider more intersting to show/record 
        This is actualy functionality - but also useful for debug.

        If it gets a dict, it assumes you already did to_dict, but avoid that if you can.

        for known types we can reduce the keys to the probably-interesting ones,
        to not store as much data we aren't interested in anyway.

        @param ob:       telegram object
        @param simplify: 
        
    """
    if ob is None:
        return None

    if isinstance(ob, dict): # assume that you did did to_dict already, and continue
        dd = ob
    else:
        dd = ob.to_dict()

    typ = dd['_'] # if this fails you probably have it something not from to_dict
    
    if not simplify:
        return dd
    else:
        if typ == 'Message':
            return await dict_subset(dd, keys='_ message id date edit_date message from_id peer_id fwd_from reply_to forwards reactions ttl_period grouped_id media'.split())
        elif typ == 'Dialog':
            return await dict_subset(dd, keys='_ title id entity unread_count'.split())
        elif typ == 'MessageReplyHeader':
            return await dict_subset(dd, keys='_ reply_to_msg_id reply_to_peer_id reply_to_top_id'.split())
        elif typ == 'MessageFwdHeader':
            return await dict_subset(dd, keys='_ date from_id from_name channel_post'.split())
        elif typ in ('Chat', 'Channel', 'User'):
            return await dict_subset(dd, keys='_ username usernames id contact first_name last_name phone title is_self bot megagroup gigageoup broadcast participants_count restricted deactivated'.split()) #  access_hash 
        elif typ in ('UserFull',):
            return await dict_subset(dd, keys='_ username usernames id first_name last_name about username usernames bot'.split()) # fake access_hash
        elif typ in ('ChatFull',): # TODO: update, currently a copy of chat/channel/user
            return await dict_subset(dd, keys='_ username usernames id contact first_name last_name phone title is_self bot megagroup gigageoup broadcast participants_count restricted deactivated'.split()) # access_hash
        else:
            print('TODO: make interesting_keys handle %r'%typ)
            return await dict_subset(dd, True)


async def full_entity_details(client, ent): # CONSIDER: renaming
    ''' Given a entity object we can fetch more about, try to do so.

        Specifically:
        - for User,    do a GetFullUserRequest
        - for Chat,    do a GetFullChatRequest
        - for Channel, do a GetFullChannelRequest

        Currently used by 
        - fetch_messages(), for the chat/channel,
        - get_full_user_details(), for users

        These would presumably only work when encountered before,
        and if private only when you have permissions.
        We will (fairly) silently fail on them. (TODO: debug that)

        @param ent: entity object, probably a User, Chat, or Channel (TODO: consider its variants)
        @return: details as a dict
    '''
    # TODO: see what difference each GetFull makes
    ret = ent.to_dict()

    if isinstance(ent, telethon.tl.types.User):
        try: # https://tl.telethon.dev/methods/messages/get_full_user.html
            full = await client( telethon.functions.users.GetFullUserRequest( ent ) )       # return type is UserFull
            ret.update( full.to_dict() ) # TODO: check that this doesn't overwrite anything important
        except Exception as e:
            print(f"GetFullUserRequest failed: {e}")
    elif isinstance(ent, telethon.tl.types.Chat):
        try: # https://tl.telethon.dev/methods/messages/get_full_chat.html
            full = await client( telethon.functions.messages.GetFullChatRequest( ent.id ) )  # return type is ChatFull
            ret.update( full.to_dict() ) # TODO: check that this doesn't overwrite anything important
        except Exception as e:
            print(f"GetFullChatRequest failed: {e}")
    elif isinstance(ent, (telethon.tl.types.Channel, telethon.tl.types.PeerChannel)):
        ret = ent.to_dict()
        try: # https://tl.telethon.dev/methods/channels/get_full_channel.html
            full = await client( telethon.functions.channels.GetFullChannelRequest( ent ) ) # return type is ChatFull
            ret.update( full.to_dict() ) # TODO: check that this doesn't overwrite anything important
        except Exception as e:
            print(f"GetFullChannelRequest failed: {e}")
    else:
        raise ValueError(f"full_entity_details() doesn't know the entity type {type(ent)}")

    return ret


def getget(d, k1, k2):
    ''' Get values from a two-deep dict structure, 
        without raising on missing items at either depth - returns None instead 
    '''
    if d is None:
        return None
    d2 = d.get(k1, None)
    if d2 is None:
        return None
    return d2.get(k2, None)  # d2 is assumed to be a dict-like




######################## CLASSES #############################################################################

class EasyConnect:
    ''' Encapsulates login and connection.

        Is a context manager that mostly just gives you an object with .client
        (specifically an async context manager, because most things around here are async)

        Implementation currently focuses on interactive user login.

        The password and code interaction is interactive.
    '''
    def __init__(self, api_id:str, api_hash:str, phonenum:str):
        """ You will need 
            - an API ID and API hash.
              You register these at https://core.telegram.org/api/obtaining_api_id
              To telegram, each of these is considered distinct client software.
            - a phone number to identify who is accessing 
              (yes, other means of login exist, but most of them are based on a previously verified phone,
               so this is the focus right now)
        """
        self._api_id   = api_id
        self._api_hash = api_hash
        self._phonenum = phonenum


    async def connect(self, session_name:str='gramgrab'): # maybe rename that to 'name_me' or something
        ' Connect and sign in '
        self.client = telethon.TelegramClient(session_name, self._api_id, self._api_hash)

        if self.client.is_connected(): # should only be relevant on repeat calls to this connect(),
            # which you should not do anyway, but it can't hurt to handle the code path
            print("INFO Still connected to telegram.")
        else: # usual case: not connected, so connect
            print("INFO Connecting to telegram...")
            await self.client.connect() # if this line throws a 'database is locked' (after a timeout), two processes are trying to share the same session

        # https://docs.telethon.dev/en/stable/modules/client.html
        if await self.client.is_user_authorized(): # basically, whether that session is still deemed valid...
            print("INFO session still authorized with telegram.")
        else: # ..and if not, then we need to sign_in() however your account does it. The following seems to handle the common cases
            print("INFO Authorizing with telegram...")
            # https://docs.telethon.dev/en/stable/modules/client.html#telethon.client.auth.AuthMethods.sign_in
            #    More documentation reading is needed, but it seems that
            #    if you have 2FA enabled you will get SessionPasswordNeededError telling you so, 
            #    and if not you do so with a code, so apparently:
            try:
                await self.client.send_code_request(self._phonenum)
                await self.client.sign_in( phone=self._phonenum, code=input("Enter code you received: ") )
            except telethon.errors.SessionPasswordNeededError:
                await self.client.sign_in( password=getpass.getpass( prompt="Password: ", stream=None ) )

            print("INFO Managed to authorize: ", await self.client.is_user_authorized() )


    async def disconnect(self): 
        " mostly for the async context manager, but if you don't use that,  "
        await self.client.disconnect()
    

    # async context manager:
    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.disconnect()




class Fetcher:
    """ Currently focuses on fetching messages, media, and mentioning the users it saw.

        Each of those things is handed to emit() - the idea is that you create a subclass
        that does something useful with them.

        To avoid unnecessary work for the servers,
        we make it easier to do incremental fetches - see fetch_messages(),
        but to actually do that you would want a subclass of this.
        This too would require a subclass, one that actually stores things,
        to be able to tell you _where_ to continue.

        The separation of concerns could use some work.


        For examples of such a concrete subclass, see SQLiteFetcher below.
        A postgres equivalent has been suggested.
        And there are other sensible extensions. Consider e.g.
        "I have an alert channel and want to occasionally update elasticsearch with that",
        as you can do that without any further storage.
    """

    def __init__( self, client, ch, fetch_message_limit=None, fetch_media=False, fetch_full_users=True, users_from_posts=True, users_from_reactions=True, debug=False ):
        ''' Yes, this represents fetching on a single channel.
            If you have linked discussion channels, you need to wrap multiple of these.

            @param fetch_media:          Whether we would fetch media 
                                         (mostly photos and documents)
            @param users_from_posts:     Whether to mention where users post, e.g. useful to decide related channels 
            @param users_from_reactions: Whether to mention where users react with emojis
                                         (without this you only get counts of the emojis)
            @param fetch_full_users:     Whether to do a full user detail fetch 
                                         for each new user that we see
            @param debug:                How much debug information to print -  
                                          2 for debug, 1/True for info, 0/False for none.
        '''
        #print('Fetcher.init')
        self.client                    = client            

        # TODO: check type of ch, and whether we need to unwrap it from something, etc.
        self.ch                        = ch # client.get_entity(ch)

        self.fetch_message_limit       = fetch_message_limit
        self.fetch_media               = fetch_media  # controls whether handle_message fetches them
        self.users_from_posts          = users_from_posts
        self.users_from_reactions      = users_from_reactions
        self.fetch_full_users          = fetch_full_users            

        self.wait_time                 = 0.5 # how long between iter_messages requests.  If you set this below 1, do expect to be throttled.

        self.mentioned_user_ids        = set()
        self.curfetch_fulled_user_ids  = set()
        self.time_spent_in             = collections.defaultdict(float)

        self.debug                     = debug
        if isinstance(debug, int):
            pass
        else: 
            debug = int(debug) # assume bool, so becomes 1 or 0


    async def emit( self, tup ):
        ''' Any data worth mentioning should be called with emit(), 
            and its implementation should deal usefully with all tuples you emit.
        '''
        warnings.warn( f'To do something useful with the data, you probably want to subclass to override Fetcher.emit( {repr(tup)} )' )


    async def handle_message_media( self, message, retries=2 ):
        " Takes a message, and if there's .media attached will do something with it "
        #if self.debug:
        #    print('handle_message_media')
        if message.media is None:
            return
            
        start_time = time.time()

        #TODO: clean up the file naming logic

        # channel.id+message.id would make it it unique,
        #   but given a filename canbe longer we can make it more informative.
        #  maybe date and time is also useful?
        saveto_path = 'ch%s_msg%s'%(self.ch.id, message.id)
        if message.grouped_id:
            saveto_path += '_gr%s'%message.grouped_id
        # may add an extension later

        if isinstance(message.media, telethon.types.MessageMediaPhoto): # (note that some images are documents instead)
            #print( 'PHOTO', message.media.stringify() )
            saveto_path += '.jpg'   # bit of an assumption but close enough for now

        elif isinstance(message.media, telethon.types.MessageMediaDocument):
            #print( 'DOC', message.media.stringify() )
            #print( message.media.document.mime_type  )
            #for attr in message.media.document.attributes:
                #print('DOC ATTR', attr)
                # TODO: aggressive sanitizing (here it's purely indication)
                #if isinstance( attr, telethon.tl.types.DocumentAttributeFilename ): 
                #    saveto_path += '__'+attr.file_name[-150:]
                #    # TODO: sanitize that 
                #    # note that that often also adds an extension
            pass
        elif isinstance(message.media, telethon.types.MessageMediaWebPage):
            if self.debug >= 2:
                print('INFO ignoring MessageMediaWebPage')
            return
            
        else:
            warnings.warn( "ERROR: handle_message_media() does not yet know how to handle", type(message.media) )

        # This is the part that actually needs to be able to retry
        while retries >= 0:
            try:
                # if we actually want the contents, then we can:
                #print( "Saving media to ", saveto_path )
                #data = await message.download_media(file=saveto_path) 
                data = await message.download_media(file=bytes) # https://docs.telethon.dev/en/stable/modules/client.html#telethon.client.downloads.DownloadMethods.download_media

                saveto_path = sha1_hex(data) + '__' + saveto_path

                # if the media is a photo or document, telethon's File can be useful        
                await self.emit( ('media', {'suggested_path':saveto_path, 'data':data, 'channel':self.ch.id, 'message':message.id} ) )
                break
            except telethon.errors.FloodWaitError as fwe:
                wait_time = 5 + fwe.seconds
                print("handle_message_media - got a FloodWaitError, sleeping for {wait_time}")
                
                self.time_spent_in['asked to sleep'] += wait_time
            retries -= 1
        
        self.time_spent_in['handle_message_media'] += time.time() - start_time


    async def handle_message( self, message ):
        ''' In principle we could just emit/store message.to_dict(),
            which makes python objects of direct members as well as contained types.

            Yet
            - sometimes we also want to do more lookups based on the parts
            - 
            - some fields are just not very interesting
        '''
        
        start_time = time.time()

        md = message.to_dict()

        # TODO: decide whether to keep these details or not - we will barely use it, and keep it only to support the 'catch up fetching media we don't already have'
        #md.pop('media',None) 

        #md['date'] = str(md['date']) # TODO: figure out whether we want to do that at all, actually

        # CONSIDER: This could be removed if we use and tweak interesting_keys
        for remove_less_interesting in (
            'from_scheduled',              # whether this is a https://core.telegram.org/api/scheduled-messages
            'quick_reply_shortcut_id',     # See https://core.telegram.org/api/business#quick-reply-shortcuts
            'suggested_post',              # used to suggest posts to channel - https://core.telegram.org/api/suggested-posts

            'video_processing_pending',    # whether contained video is still being processed by the server
            'via_business_bot_id',         # whether it was sent via https://core.telegram.org/api/bots/connected-business-bots
            'via_bot_id',                  # ID of inline bot if it generated this
            'paid_suggested_post_ton',     # see https://core.telegram.org/api/suggested-posts
            'paid_suggested_post_stars',   # 
            'paid_message_stars',          # 
            'from_boosts_applied',         # number of applied https://core.telegram.org/ai/boost
            'ttl_period',                  # when message should be deleted
            'report_delivery_until_date',  # used by Telegram Gateway?
            'invert_media',                # show webpage on top, not bottom
            'effect',                      # animated message effect   https://core.telegram.org/api/effects
            'silent',                      # no notification triggered

            'media_unread',                
            'offline',                     # sent because of scheduled action
            'mentioned',                   # whether we were mentioned
            'legacy',                      # legacy, has to be refetched with new layer
            'restriction_reason',          # 

            'saved_peer_id',               # less interesting, I think? 

            # review these - maybe keep them after all
            'post_author'                  # string (not peer), used only broadcast channel messages;  sender's name at the time of posting
                                        #   (seems mostly for UI, not that informative) 
            'pinned',      
            'out',                         # seems to effectively mean it was sent by us, or not?
            'post',                        # sent by channel, see it as a feed item - expect from_id to be None
            'noforwards',                  # protected from forwarding
            'factcheck',                   # represents a https://core.telegram.org/api/factcheck
            'entities',    
            'reply_markup',                # to double check
        ):
            if remove_less_interesting in md:
                md.pop( remove_less_interesting )

        #if message.from_id is not None: 
            # then it's one of the Peer types
            #fe = await client.get_entity( message.from_id )
            #print('message.from_id entity', await interesting_keys( fe ) )
            #print( '  from_id:',) )

        # TODO: see if from_id is always user 
        from_user_id = None
        #print('md',md)        
        #print('message',message)        
        #print('message.from_id',message.from_id)        
        # note that in a broadcast channel, from_id is typically None
        if message.from_id is not None:
            if isinstance(message.from_id, telethon.tl.types.PeerUser): #as opposed to PeerChannel, or None
                #print('')
                try:
                    msg_user_id = message.from_id.user_id
                except:
                    print('FOO', dir(message.from_id))
                    raise

                if self.users_from_posts and msg_user_id not in self.mentioned_user_ids:
                    #print('handle_message/m/UM')
                    await self.emit( ('user_mentioned', {'what':'posted', 'uid':msg_user_id, 'chid':self.ch.id, 'message':message.id} )  )
                if self.fetch_full_users:
                    #print('handle_message/m/UF')
                    #TODO: consider doing that emit in the function?
                    user_data_dict = await self.get_full_user_details( await self.client.get_entity(msg_user_id) )
                    if user_data_dict is not None:
                        await self.emit( ('user_full', {'uid':msg_user_id, 'data':user_data_dict} )  )

                # TODO: mention each user just once per channel per run
                self.mentioned_user_ids.add(msg_user_id)
                from_user_id = msg_user_id
            #else

        if message.reactions is not None:
            ## the aggregate reaction counts - easy to extract
            reaction_counts = {}
            for reactioncount in message.reactions.results:
                if isinstance(reactioncount.reaction, telethon.tl.types.ReactionEmoji):
                    # NOTE: the other reaction types are ReactionCustomEmoji, ReactionPaid; we ignore those right now
    
                    reaction_counts[reactioncount.reaction.emoticon] = reactioncount.count
                #print( '  reaction counts: ',reaction_counts )

            md['reaction_counts'] = reaction_counts

            urd = {}
            ## we can also ask for which users reacted, which might find (and encounter?) more users
            if self.users_from_reactions and message.reactions.can_see_list: 
                # can_see_lists is whether we have permissions to fetch this list

                # CONSIDER: separate function so that we can choose to do this here or later or not at all
                #           perhaps async def handle_reaction(ch_id, msg_id, limit=100)
                detailed_reactions = await self.client( telethon.functions.messages.GetMessageReactionsListRequest(
                    peer  = self.ch.id, 
                    id    = message.id,
                    limit = 100,         # TODO: all? configurable?  Right now it's an arbitrary limit for quick testing
                ))
                for dr in detailed_reactions.reactions:

                    if isinstance(dr.peer_id, telethon.tl.types.PeerUser): # can be PeerUser, PeerChannel (and perhaps PeerChat, None?)

                        if isinstance(dr.reaction, telethon.tl.types.ReactionEmoji):
                            # same test as above - if it's any of the other types, we won't set the reactions key with user -> contents
                            #                      but will still emit() the users we found
                            urd[ dr.peer_id.user_id ] = dr.reaction.emoticon

                        if self.users_from_posts:
                            #print('handle_message/r/UM')
                            await self.emit( ('user_mentioned', {'what':'reacted', 'uid':dr.peer_id.user_id, 'chid':self.ch.id, 'message':message.id} )  )

                        if self.fetch_full_users:
                            #print('handle_message/r/UF')
                            user_data_dict = await self.get_full_user_details( await self.client.get_entity(dr.peer_id.user_id) )
                            await self.emit( ('user_full', {'uid':dr.peer_id.user_id, 'data':user_data_dict} )  )
            md['reactions'] = urd


        if message.fwd_from is not None: # https://core.telegram.org/constructor/messageFwdHeader
            # During fetch, telethon also adds a .forward, 
            # but it's basically just the python-type equivalent of the above,
            # and fwd_from serializes more easily
            md['fwd_from'] = await interesting_keys(message.fwd_from) # assume this overwrites what was there


            #CONSIDER: Anything else to do with it?
            #print( 'fwd_from', md['fwd_from'] )

            # Note that fwd_from.from_id is usually either a channel or a user (forward from dialog or chat?)
            from_entity = message.fwd_from.from_id # actually a Peer
            if from_entity is not None:
                from_dict   = getget( md, 'fwd_from', 'from_id') # slightly more convenient
                #print('INFO forward, from_dict', from_dict)

                #if 'user_id' in from_peer: # implicitly, '_' will be PeerUser

                if 'channel_id' in from_dict: # implicitly, '_' will be PeerChannel
                    print(f"INFO forward from channel {from_dict['channel_id']}")
                    
                    # CONSIDER: putting this back if if we do a 'fetch full channel peer only if not known'
                    #try:
                    #    edet = await full_entity_details(self.client, message.fwd_from.from_id)   # TODO: is broken I think?
                    #    edet = edet['full_chat'] # HACK; TODO: figure the nesting out properly
                    #    #print('from channel details', edet)
                    #    await self.emit( ('channel_details', edet) )
                    #except ValueError as ve:
                    #    print('VE', ve)


        if message.reply_to is not None: # https://core.telegram.org/constructor/messageReplyHeader
            md['reply_to'] = await interesting_keys(message.reply_to) # overwrites what was there

        self.time_spent_in['handle_message (including any user fetches)'] += time.time() - start_time

        await self.emit( ('message', self.ch.id, message.id, md) )

        #if message.from_id is not None:
        #    print( message.from_id )
        #entity = await client.get_entity(fwd.from_id)
        #    print("Forwarded from:", getattr(entity, 'title', None) or entity.id)


    async def get_full_user_details( self, user ): # CONSIDER adding complete_cached_ to the name
        ''' Try to get full user details for this user.

            This is intended as a 'fetch full user details only for users we have not done that for before'.
            If we know we have information already, we do nothing and return None.
            Will avoid requesting that more than once per user (per run, and per collection database).

            Note that while we do a full user fetch, for strangers you usually get mainly empty fields,
            for good privacy reasons.
        '''
        ret = None
        start_time = time.time()
        if user.id in self.prevfetch_fulled_user_ids:
            pass
            if self.debug >= 2:
                print("DEBUG already tried get_full_user_details(%s) in a previous run"%user.id)
        elif user.id in self.curfetch_fulled_user_ids:
            if self.debug >= 2:
                print("DEBUG already tried get_full_user_details(%s) in this run"%user.id)
        else:
            if self.debug:
                print("INFO  get_full_user_details(%s)"%user.id)
            data_dict = await full_entity_details(self.client, user)
            #print('fulltest', data_dict)
            ret = data_dict
            self.curfetch_fulled_user_ids.add( user.id )
        self.time_spent_in['get_full_user_details'] += time.time() - start_time
        return ret
        

    async def fetch_messages( self, start_at=0 ):
        """ start_at:  If you want to update from previous stored state,
                       hand in max(stored ids), it will be used as a min_id.
        """
        try:
            edet = await full_entity_details(self.client, self.ch)   # TODO: is broken I think?
            await self.emit( ('channel_details', edet) )
        except Exception as e:
            print(f"full_entity_details() failed: {e}")
            raise

        start_time_f = time.time()
        # If we want to know the count of messages (e.g. for progress indicator),
        #   the max ID is often (much) too high, but the following is usually relatively close:
        _temp_messages = await self.client.get_messages(self.ch, limit=0)
        print( f"INFO Remote message count (for ch={self.ch.id}) is at most {_temp_messages.total} (approximately)" )
        #self.time_spent_in['estimating remote message count'] += time.time() - start_time_f

        # the default for iter_messages is to get messages latest first and then decreasing ID.
        # If we want to continue from earlier runs, it is slighly easier to express "continue from what we have" when go increment
        #   Specificallly, breaking off might create gaps we would have to check.
        # (default decrementing way, weh)
        # say we have 4 3 2 1 and we now are up to 7 and breaking off fetching
        # it's a little easier to express "continue from what we have" when we g

        continue_at = start_at   # the last successful one.   0 means we start at the latest (VERIFY)
        count = 0
        while True:
            print( f"INFO iter_messages continue_at msgid={continue_at}" )
            try:

                # CONSIDER: progress bar somehow?

                async for message in self.client.iter_messages(self.ch, min_id=continue_at, wait_time=self.wait_time, reverse=True, limit=self.fetch_message_limit):
                    start_time_i = time.time()
                    if isinstance(message, telethon.tl.types.Message): 
                        await self.handle_message( message )
                        if self.fetch_media: # if any; the following does nothing if there isn't
                            await self.handle_message_media( message ) 

                        count += 1
                        if self.debug >= 2:
                            print(f"DEBUG at message count {count}")
                        if (count % 50) == 0:
                            if self.debug >= 1:
                               print(f"INFO iter_messages - message count update: {count}")
                            await self._db_commit(checkpoint=True)

                    #else: # it seems the only other type is MessageService, which is less interesting
                    elif isinstance(message, telethon.tl.types.MessageService):
                        #if self.debug >= 2:
                        #    print( f"DEBUG skipped {type(message)} - {message.action}")

                        # non-message things include
                        if isinstance(message.action, (
                          telethon.tl.types.MessageActionChatEditTitle,
                          telethon.tl.types.MessageActionChatEditPhoto,
                          telethon.tl.types.MessageActionPinMessage,
                          telethon.tl.types.MessageActionChatAddUser,
                          telethon.tl.types.MessageActionChannelCreate,
                          telethon.tl.types.MessageActionGiveawayLaunch,
                          telethon.tl.types.MessageActionGiveawayResults,
                          telethon.tl.types.MessageActionSetChatWallPaper,
                        )):
                            continue
                        # that was there so that we could have an else-unhandled but right now that's all there is
                    
                    #if self.debug >= 2:
                    #    print(f"DEBUG now at message id {message.id}")
                    continue_at = message.id

                    self.time_spent_in['iter_messages (mostly handle_message + get_full_user_details + media)'] += time.time() - start_time_i

                print("INFO iter_messages done")
                break   # once we're finished

            except telethon.errors.FloodWaitError as fwe:
                wait_time = 5 + fwe.seconds
                print(f"INFO iter_messages - got a FloodWaitError, sleeping for {wait_time} seconds")
                await self._db_commit(checkpoint=True)
                await asyncio.sleep( wait_time )
                self.time_spent_in['asked to sleep'] += wait_time
                
        self.time_spent_in['fetch_messages'] += time.time() - start_time_f







class GGDB:
    """ Wrapper for both the writing and reading  with the structure this program uses.

        Exists in part so that both the fetcher and the just-reading gramparse can share code.
    """
    def __init__(self, db_path='gramgrab.db'):
        self.db_path = db_path
        self.db_open()
        #self.conn = sqlite3.connect(db_path, timeout=3)
        #self.conn.execute( "PRAGMA journal_mode = WAL" )


    def db_open(self, timeout=3.0):
        """ Open the path previously set by init.
            This function could probably be merged into init, it was separated mostly with the idea that we could keep it closed when not using it.

            timeout: how long wait on opening. Lowered from the default just to avoid a lot of waiting half a minute
        """
        self.conn = sqlite3.connect(self.db_path, timeout=timeout)

        # Note: curs.execute is the regular DB-API way,
        #       conn.execute is a shorthand that gets a temporary cursor

        # If WAL is not possible (that is, we know we can't get the necessary shm due to the VFS) this is effectively just ignroed
        # Using use_wal once persists with a database, in that future opens will use it even if you don't ask for it
        # WAL requires sqlite >=3.7.0, but this seems fine because python's sqlite3 requires >=3.7.15
        self.conn.execute( "PRAGMA journal_mode = WAL" )

        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS noticed_channel (recorded datetime DEFAULT CURRENT_TIMESTAMP, chid text NOT NULL, data text NOT NULL)"
        )
        self.conn.execute( # CONSIDER: add chid so we can fetch per channel directly
            "CREATE TABLE IF NOT EXISTS noticed_user    (recorded datetime DEFAULT CURRENT_TIMESTAMP, uid  text NOT NULL, chid text NOT NULL,  msgid text, data text NOT NULL)"
        )
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS user_full       (recorded datetime DEFAULT CURRENT_TIMESTAMP, uid  text NOT NULL, data text NOT NULL)"
        )
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS messages        (chid text NOT NULL, msgid NOT NULL, data text)"
        ) # maybe a key/index on (chid,msgid) ?
        self.conn.execute( # CONSIDER: adding chidd, add what
            "CREATE TABLE IF NOT EXISTS media           (chid text NOT NULL, msgid NOT NULL, suggested_path text, sha1hash text, data text)"
        ) # maybe a key/index on (chid,msgid) ?


    async def _db_commit(self, checkpoint=False):
        ' Used internally after some blocks of fetches'
        self.conn.commit() 
        if checkpoint:
            self.conn.execute('PRAGMA wal_checkpoint(PASSIVE)')


    async def db_close(self, commit=True):
        ' commit or rollback, then close, the sqlite connection'
        if commit:
            await self._db_commit(checkpoint=True)
        else:
            self.conn.rollback() # conditional?
        self.conn.close()


    # async context manager, for sqlite connection close
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        try:
            self.conn.close()
        except:
            pass


    ######## returning fetched data from database #############
    async def db_counts_all(self):
        ' '
        ret = {}
        start_time = time.time()
        curs = self.conn.cursor()
        try:
            curs.execute( 'SELECT count(*) FROM messages' )
            cnt, = curs.fetchone()
            ret['messages'] = cnt

            curs.execute( 'SELECT count(*) FROM noticed_user' )
            cnt, = curs.fetchone()
            ret['user_mentions'] = cnt

            curs.execute( 'SELECT count(*) FROM user_full' )
            cnt, = curs.fetchone()
            ret['user_fulls'] = cnt

            curs.execute( 'SELECT count(*) FROM noticed_channel' )
            cnt, = curs.fetchone()
            ret['chan_details'] = cnt

            curs.execute( 'SELECT count(*) FROM media' )
            cnt, = curs.fetchone()
            ret['media'] = cnt

            ret['_took_sec'] = time.time() - start_time            
        finally:
            curs.close()
        return ret


    async def db_message_channels(self):
        ' Return the distint channels that we have stored messages for. '
        sql = 'SELECT DISTINCT chid FROM messages'
        curs = self.conn.cursor()
        try:
            curs.execute( sql )
            rows = curs.fetchall()
        finally:
            curs.close()
        ret = []
        for chid, in rows:
            ret.append( int(chid) )
        return ret


    async def db_messages_all(self, chid=None, limit=None):
        ' Returns all messages. In a channel or at all.  Up to a limit, or all.'
        sql = 'SELECT chid, msgid, data FROM messages'
        if chid is not None:
            sql += ' WHERE chid=%d'%chid            
        if limit is not None:
            sql += ' LIMIT %d'%limit

        curs = self.conn.cursor()
        try:
            curs.execute( sql )
            rows = curs.fetchall()
        finally:
            curs.close()
        decoded = []
        for chid, msgid, data in rows:
            decoded.append( (int(chid), int(msgid), msgpack.unpackb(data, timestamp=3, strict_map_key=False)) )
        return decoded


    async def db_user_mentions_all(self, limit=None):
        ' Returns when we recorded which user in which channel '
        sql = 'SELECT recorded, uid, chid, msgid, data FROM noticed_user'
        if limit is not None:
            sql += ' LIMIT %d'%limit

        curs = self.conn.cursor()
        try:
            curs.execute( sql )
            rows = curs.fetchall()
        finally:
            curs.close()
        decoded = []
        for recorded_at, uid, chid, msgid, data in rows:
            decoded.append( (recorded_at, int(uid), int(chid), int(msgid), msgpack.unpackb(data, timestamp=3, strict_map_key=False)) )
        return decoded


    async def db_user_full(self):
        ''' Return
            'posted'  - mentions that user posted. Usually minimal details, assume little more than user id.
            'reacted' - mentions that user reacted. Usually minimal details, assume little more than user id.
            'full' result of 'get full user details' request (which may not be much).  We try to call this on every user that posts or reacts - at most once per user per run.

            For each user we try to return 
            - full details if we have it
            - which channels they posted and reacted in
        '''
        sql = 'SELECT recorded, uid, data FROM user_full ORDER BY recorded asc'

        curs = self.conn.cursor()
        try:
            curs.execute( sql )
            rows = curs.fetchall()
        finally:
            curs.close()

        decoded = []
        # CONSIDER: merging, right now you just get the latest for each uid
        for recorded_at, uid, data in rows:
            decoded.append( (recorded_at, int(uid), msgpack.unpackb(data, timestamp=3, strict_map_key=False)) )
        return decoded

        #inter = collections.defaultdict( lambda: collections.defaultdict(list) ) # uid -> (entered, data)
        #for recorded_at, uid, data in ud:
        #    
        #    inter[int(uid)] = (recorded_at, msgpack.unpackb(data, timestamp=3, strict_map_key=False))
        #return inter


    async def db_channel_details(self):
        """ Note that these are snapshots of their metadata, so that you can notice changes.
            If you do not care, any one of them will do 

            Returns sequence of (recorded_at, chid, data)
        """
        curs = self.conn.cursor()
        try:
            curs.execute('SELECT recorded, chid, data FROM noticed_channel')
            rows = curs.fetchall()
        finally:
            curs.close()
        decoded = []
        for recorded_at, chid, data in rows:
            decoded.append( (recorded_at, int(chid), msgpack.unpackb(data, timestamp=3, strict_map_key=False)) )
        return decoded


    async def db_media_list(self):
        """ Returns which messages we have media for,
            as a list of (chid, msgid, shaehash) tuples.
        """
        curs = self.conn.cursor()
        try:
            curs.execute('SELECT chid, msgid, sha1hash FROM media')
            rows = curs.fetchall()
        finally:
            curs.close()
        
        ret = []
        for chid, msgid, sha1hash in rows:  # almost a no-op, but let's do it for being explicit about what's in here
            ret.append( (chid, msgid, sha1hash) ) 
        return ret


    async def db_media_formessage(self, chid, msgid):
        ' Returns (fetched_at, data) '
        curs = self.conn.cursor()
        try:
            curs.execute('SELECT chid, suggested_path, data  FROM media  WHERE chid=? AND msgid=?', (chid, msgid) )
            rows = curs.fetchall()
        finally:
            curs.close()
        
        if len(rows)==0:
            raise ValueError('No media for chid=%d,msgid=%d'%(chid, msgid))
        if len(rows)>1: # shouldn't happen
            print('WARN: multiple media (%d) for chid=%d,msgid=%d'%(chid, msgid))
        
        chid, suggested_path, data = rows[0]

        return suggested_path, data





class SQLiteFetcher(Fetcher, GGDB):
    ''' Bare Fetcher just emit()s information,
        but doesn't store it, and exits for encapsulation reasons.

        This expands on that by listening to those emit()s and storing them,
        and some functionality that only makes sense when storing.

        Additions:
        - database open and close
        - emit() is implemented to store in that open database
        - fetch_messages augmented to 
          - pick up where message fetching left off ealier
          - only do full user fetches we didn't already do
        - some functions to ease database readout


        Could stand separation of db and fetching, 
        because right now you need to connect to telegram 
        just to read out the db.
    '''
    def __init__(self, client, ch, db_path='gramgrab.db', *args, **kwargs):
        """ 
            @param client:   A telethon client.
                             If you use EasyConnect class, you can hand in its .client
            @param ch:       Channel/chat we will be fetching. 
                             The database refers to which channel/chat it got things in, so you can fetch multiple channels into it,
                             but the fetcher instance works on one channel/chat at a time.
            @param db_path:  Path to the file to open/create the database in.


            It is fine to use a database that contains other channels's data,
            - as most things are separable afterwards,
            - and there are some analyses (e.g. 'where else is this user active')
              that are much easier if it's in the same database
            - though in some use cases it will make more to you to use a database per channel.


        """
        Fetcher.__init__(self, client, ch, *args, **kwargs)
        GGDB.__init__(   self, db_path)
        #self.db_path = db_path
        self.prevfetch_fulled_user_ids = set()
        #self.db_open()


    async def fetch_messages( self, start_at=0 ):
        '  '
        #if self.debug:
        #    print('fetch_messages')

        # TODO: think about whether this is the best spot for this,
        #       or whether it should be 'do this once on first need'
        if self.fetch_full_users:
            print("INFO prevuser - fetching knowledge of users we already looked up...")
            curs = self.conn.cursor()
            start_time = time.time()
            # CONSIDER: making it a map from uid to recent fetch, so we can have "refresh if older than" behaviour
            try:
                curs.execute('SELECT distinct uid FROM user_full')
                rows = curs.fetchall()
            finally:
                curs.close()
            for uid, in rows:
                self.prevfetch_fulled_user_ids.add( int(uid) )

            took = time.time() - start_time
            self.time_spent_in['db_fullfetch'] += took
            print("INFO prevuser - ...%d user IDs loaded (in %.2f sec)"%(len(self.prevfetch_fulled_user_ids),took))
            #print(self.prevfetch_fulled_user_ids)            


        start_time = time.time() 
        curs = self.conn.cursor()
        # Figure out what we have, and where to continue from 
        maxmid = None
        try:
            curs.execute('SELECT count(msgid),max(msgid) FROM messages WHERE chid=?',(self.ch.id,))
            count, maxmid, = curs.fetchone()
        finally:
            curs.close()
        
        if maxmid is None:
            maxmid = 0
        self.time_spent_in['db'] += time.time() - start_time
        print("INFO currently have %d messages for %s(%s)"%(
            count, 
            self.ch.to_dict()['_'],  # Channel / Chat
            self.ch.id)
        )

        # database stuff is handled/separated by handling emit()s
        await super().fetch_messages( start_at=maxmid )

        await self._db_commit()


    async def emit( self, tup ): 
        ''' overrides emit with something that knows how to store it 
            This is an example for sqlite to make a quick file store, 
            you might consider postgres, elasticsearch, or others.
        '''
        start_time = time.time()

        what = tup[0]
        if what == 'message':
            channelid, messageid, dd = tup[1:]
            self.conn.execute('INSERT INTO messages (chid, msgid, data) VALUES (?,?,?)', 
                (channelid, messageid, msgpack.dumps(dd, datetime=True))
            )
        elif what == 'user_mentioned': # assumes dict presence of keys 'uid', 'chid', and 'message'
            dd = tup[1]
            self.conn.execute('INSERT INTO noticed_user (uid, chid, msgid, data) VALUES (?,?,?,?)', 
                (dd['uid'], dd.get('chid'), dd.get('message',None), msgpack.dumps(dd, datetime=True))
            )
        elif what == 'user_full': # assumes presence of keys 'user_id' and 'message'
            dd = tup[1]
            self.conn.execute('INSERT INTO user_full (uid, data) VALUES (?,?)', 
                (dd['uid'], msgpack.dumps(dd, datetime=True))
            )
        elif what == 'channel_details': # assumes dict presence of key 'id'
            dd = tup[1]
            #print('chd',dd)
            self.conn.execute('INSERT INTO noticed_channel (chid, data) VALUES (?,?)', 
                (dd['id'], msgpack.dumps(dd, datetime=True))
            )
        elif what == 'media':# assumes presence of keys 'channel', 'message', 'suggested_path', and 'data'
            dd = tup[1]
            self.conn.execute('INSERT INTO media (chid, msgid, suggested_path, sha1hash, data) VALUES (?,?,?,?,?)', 
                (dd['channel'], dd['message'], dd['suggested_path'], sha1_hex(dd['data']), dd['data'])
            )
        else:
            raise ValueError("emit() doesn't know what to do with {what} - {tup}")
        #CONSIDER: occasional commit, this is currently closer to an autocommit
        #await self._db_commit(checkpoint=False)
        self.time_spent_in['db'] += time.time() - start_time            


