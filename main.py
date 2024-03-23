import logging

from kibernikto.bots.redactor_settings import RedactorSetting
from kibernikto.bots.cybernoone import listener
from kibernikto.bots.vertihvostka import Vertihvostka

from kibernikto.bots import AiSettings

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
    print('\t%-15s%-15s' % ("avatar model:", AiSettings.OPENAI_API_MODEL))
    print('\t%-15s%-15s' % ("avatar host:", AiSettings.OPENAI_BASE_URL))
    print('\t%-15s%-15s' % ("avatar temp:", AiSettings.OPENAI_TEMPERATURE))

    if RedactorSetting.OPENAI_API_KEY:
        print("\t")
        print('\t%-15s%-15s' % ("redact model:", RedactorSetting.OPENAI_API_MODEL))
        print('\t%-15s%-15s' % ("redact host:", constants.OPENAI_BASE_URL))
    else:
        print('\t%-15s%-15s' % ("redactor mode:", 'disabled'))

    print("\t")
    print('\t%-15s%-15s' % ("tg master:", constants.TG_MASTER_ID))
    print('\t%-15s%-15s' % ("tg group:", constants.TG_FRIEND_GROUP_ID))
    print("\t")

    # some kind of switcher here
    single_group_dispatcher.start(bot_class=listener.Kibernikto)
