import logging
from kibernikto.bots.cybernoone import listener

logging.basicConfig(
    format='%(levelname)-8s %(asctime)s %(name)s:%(filename)s:%(lineno)d %(message)s',
    datefmt='%Y-%m-%d:%H:%M:%S',
    level=logging.DEBUG)
logger = logging.getLogger('openai')
logger.setLevel(logging.INFO)

logger = logging.getLogger('httpcore')
logger.setLevel(logging.INFO)

logger = logging.getLogger('httpx')
logger.setLevel(logging.INFO)

logger = logging.getLogger('asyncio')
logger.setLevel(logging.INFO)

# Initialize bot and dispatcher
if __name__ == '__main__':
    from kibernikto import constants

    from kibernikto.telegram import single_group_dispatcher

    print("\t")
    print('\t%-15s%-15s' % ("avatar model:", constants.OPENAI_API_MODEL))
    print('\t%-15s%-15s' % ("avatar host:", constants.OPENAI_BASE_URL))
    print('\t%-15s%-15s' % ("avatar temp:", constants.OPENAI_TEMPERATURE))
    if constants.SUMMARIZATION_KEY:
        print("\t")
        print('\t%-15s%-15s' % ("sum model:", constants.SUMMARIZATION_MODEL))
        print('\t%-15s%-15s' % ("sum host:", constants.SUMMARIZATION_API_BASE_URL))
    else:
        print('\t%-15s%-15s' % ("summarization:", 'disabled'))
    print("\t")
    print('\t%-15s%-15s' % ("tg master:", constants.TG_MASTER_ID))
    print('\t%-15s%-15s' % ("tg group:", constants.TG_FRIEND_GROUP_ID))
    print("\t")
    if constants.TG_CHANNEL_ID:
        print('\t%-15s%-15s' % ("channel id:", constants.TG_CHANNEL_ID))
        print('\t%-15s%-15s' % ("channel model:", constants.TG_CHANNEL_API_MODEL))

    single_group_dispatcher.start(bot_class=listener.Cybernoone)
