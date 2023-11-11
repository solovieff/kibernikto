import logging
from cyberavatar.bots.cybernoone import listener

logging.basicConfig(
    format='%(levelname)-8s %(asctime)s %(name)s:%(filename)s:%(lineno)d %(message)s',
    datefmt='%Y-%m-%d:%H:%M:%S',
    level=logging.DEBUG)
logger = logging.getLogger('openai')
logger.setLevel(logging.INFO)
# Initialize bot and dispatcher
if __name__ == '__main__':
    from cyberavatar import constants

    from cyberavatar.telegram import basic_dispatcher

    print("\t")
    print('\t%-15s%-15s' % ("avatar model:", constants.OPENAI_API_MODEL))
    print('\t%-15s%-15s' % ("avatar host:", constants.OPENAI_API_BASE))
    print('\t%-15s%-15s' % ("avatar temp:", constants.OPENAI_TEMPERATURE))
    if constants.SUMMARIZATION_KEY:
        print("\t")
        print('\t%-15s%-15s' % ("sum model:", constants.SUMMARIZATION_MODEL))
        print('\t%-15s%-15s' % ("sum host:", constants.SUMMARIZATION_API_BASE))
    else:
        print('\t%-15s%-15s' % ("summarization:", 'disabled'))
    print("\t")
    print('\t%-15s%-15s' % ("tg master:", constants.TG_MASTER_ID))
    print('\t%-15s%-15s' % ("tg group:", constants.TG_FRIEND_GROUP_ID))
    print("\t")

    basic_dispatcher.start(bot_class=listener.Cybernoone)
