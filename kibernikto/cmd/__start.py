import logging
import argparse
from dotenv import load_dotenv


def start(outer_env=False):
    """
    Run main dispatcher, connect to Telegram and start listening for messages.

    :return:
    """
    parser = argparse.ArgumentParser(description='Run Kibernikto')
    parser.add_argument('--env_file_path', metavar='env_file_path', required=False,
                        help='env file location', default='.env')

    args = parser.parse_args()

    if not outer_env:
        load_dotenv(dotenv_path=args.env_file_path)

    from kibernikto.utils.environment import configure_logger, print_banner
    from kibernikto.telegram import dispatcher
    configure_logger()
    print_banner()

    # for service messages
    from kibernikto.telegram import middleware_service_group
    # for default commands
    from kibernikto.telegram import commands
    # for subscription
    from kibernikto.telegram.payment import middleware_subscription
    from kibernikto.bots.cybernoone import Kibernikto
    dispatcher.start(bot_class=Kibernikto)


# Initialize bot and dispatcher
if __name__ == '__main__':
    start()
