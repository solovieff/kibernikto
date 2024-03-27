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
    parser.add_argument('--bot_type', metavar='bot_type', required=False,
                        help='kibernikto, vertihvostka', default='kibernikto')

    parser.add_argument('--dispatcher', metavar='dispatcher', required=False,
                        help='default, multiuser, open', default='default')
    args = parser.parse_args()

    if not outer_env:
        load_dotenv(dotenv_path=args.env_file_path)

    from kibernikto.utils.environment import configure_logger, print_banner

    configure_logger()
    print_banner()

    if args.bot_type == 'kibernikto':
        from kibernikto.bots.cybernoone import Kibernikto
        bot_class = Kibernikto
    elif args.bot_type == 'vertihvostka':
        from kibernikto.bots.vertihvostka import Vertihvostka
        bot_class = Vertihvostka
    else:
        raise RuntimeError("Wrong bot_type, should be in ('kibernikto','vertihvostka')")

    if args.dispatcher == 'default':
        from kibernikto.telegram import single_group_dispatcher

        single_group_dispatcher.start(bot_class=bot_class)
    elif args.dispatcher == 'multiuser':
        from kibernikto.telegram import comprehensive_dispatcher

        comprehensive_dispatcher.start(bot_class=bot_class)
    else:
        raise RuntimeError("Wrong dispatcher!")


# Initialize bot and dispatcher
if __name__ == '__main__':
    start()
