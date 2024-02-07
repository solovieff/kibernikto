import logging


def init():
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


def banner():
    from kibernikto import constants
    from kibernikto.telegram.channel import constants as channel_constants
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
    if channel_constants.TG_CHANNEL_ID:
        print('\t%-15s%-15s' % ("channel id:", channel_constants.TG_CHANNEL_ID))
        print('\t%-15s%-15s' % ("channel model:", channel_constants.TG_CHANNEL_API_MODEL))
