from kibernikto.bots.ai_settings import AI_SETTINGS

import logging

from kibernikto.plugins import KiberniktoPlugin


def print_banner():
    print("\t")
    print('\t%-20s%-20s' % ("avatar model:", AI_SETTINGS.OPENAI_API_MODEL))
    print('\t%-20s%-20s' % ("avatar host:", AI_SETTINGS.OPENAI_BASE_URL))
    print('\t%-20s%-20s' % ("avatar temp:", AI_SETTINGS.OPENAI_TEMPERATURE))


def print_plugin_banner(kbnktp_plgn: KiberniktoPlugin):
    plgn_name = kbnktp_plgn.__class__.__name__
    print('\t%-20s%-20s' % (f"{plgn_name} model: ", kbnktp_plgn.model))
    print('\t%-20s%-20s' % (f"{plgn_name} host: ", kbnktp_plgn.base_url))


def print_plugin_off(kbnktp_plgn_cls):
    plgn_name = kbnktp_plgn_cls.__name__
    print('\t%-20s%-20s' % (f"{plgn_name}:", "off"))


def feature_not_configured(feature_name):
    print("\t")
    print('\t%-20s%-20s' % (f"{feature_name}:", "off"))


def configure_logger():
    logging.basicConfig(
        format='%(levelname)-8s %(asctime)s %(name)s:%(filename)s:%(lineno)d %(message)s',
        datefmt='%Y-%m-%d:%H:%M:%S',
        level=logging.DEBUG)
    logger = logging.getLogger('openai')
    logger.setLevel(logging.INFO)

    logger = logging.getLogger('aiosqlite')
    logger.setLevel(logging.ERROR)

    logger = logging.getLogger('httpcore')
    logger.setLevel(logging.INFO)

    logger = logging.getLogger('httpx')
    logger.setLevel(logging.INFO)

    logger = logging.getLogger('asyncio')
    logger.setLevel(logging.INFO)
