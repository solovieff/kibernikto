import asyncio
from threading import Thread

from kibernikto.bots.cybernoone import listener
from kibernikto.telegram.channel import constants as channel_constants
from kibernikto.telegram.channel.gnews.politics_channel import PoliticsGnewsChannel
from kibernikto import k_logger
from kibernikto.telegram import single_group_dispatcher
from telegram.channel.gnews.free_channel import FreeGnewsChannel

# Initialize bot and dispatcher
if __name__ == '__main__':

    k_logger.init()
    k_logger.banner()

    if channel_constants.TG_CHANNEL_ID:
        if channel_constants.TG_CHANNEL_POLITICS:
            channel = FreeGnewsChannel(api_key=channel_constants.TG_CHANNEL_API_KEY,
                                       model=channel_constants.TG_CHANNEL_API_MODEL,
                                       publish_func=single_group_dispatcher.publish_to_channel,
                                       interests=channel_constants.TG_CHANNEL_INTERESTS,
                                       new_pub_minutes=channel_constants.TG_CHANNEL_PUBLICATION_PERIOD_MINUTES,
                                       refresh_minutes=10
                                       )
    else:
        channel = None
        # single_group_dispatcher.dp.loop.create_task(channel.start())
        # thread = Thread(target=asyncio.run, args=(channel.start(),))
        # thread.start()
    single_group_dispatcher.start(bot_class=listener.Cybernoone, channel=channel)
