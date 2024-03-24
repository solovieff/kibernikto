from kibernikto.bots.ai_settings import AI_SETTINGS
from kibernikto.bots.redactor_settings import REDACTOR_SETTINGS

import logging

from kibernikto.plugins import KiberniktoPlugin


def print_banner():
    print("\t")
    print('\t%-15s%-15s' % ("avatar model:", AI_SETTINGS.OPENAI_API_MODEL))
    print('\t%-15s%-15s' % ("avatar host:", AI_SETTINGS.OPENAI_BASE_URL))
    print('\t%-15s%-15s' % ("avatar temp:", AI_SETTINGS.OPENAI_TEMPERATURE))

    if REDACTOR_SETTINGS.OPENAI_API_KEY is not None:
        print("\t")
        print('\t%-15s%-15s' % ("redact model:", REDACTOR_SETTINGS.OPENAI_API_MODEL))
        print('\t%-15s%-15s' % ("redact host:", REDACTOR_SETTINGS.OPENAI_BASE_URL))
    else:
        print('\t%-15s%-15s' % ("redactor:", 'disabled'))

    from kibernikto.telegram.single_group_dispatcher import TELEGRAM_SETTINGS
    print("\t")
    print('\t%-15s%-15s' % ("tg master:", TELEGRAM_SETTINGS.TG_MASTER_ID))
    print('\t%-15s%-15s' % ("tg group:", TELEGRAM_SETTINGS.TG_FRIEND_GROUP_ID))


def print_plugin_banner(kbnktp_plgn: KiberniktoPlugin):
    print("\t")
    plgn_name = kbnktp_plgn.__class__.__name__
    print('\t%-15s%-15s' % (f"{plgn_name} model: ", kbnktp_plgn.model))
    print('\t%-15s%-15s' % (f"{plgn_name} host: ", kbnktp_plgn.base_url))


def print_plugin_off(kbnktp_plgn_cls):
    print("\t")
    plgn_name = kbnktp_plgn_cls.__name__
    print('\t%-15s%-15s' % (f"{plgn_name}:", "off"))


def feature_not_configured(feature_name):
    print("\t")
    print('\t%-15s%-15s' % (f"{feature_name}:", "off"))


def configure_logger():
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
