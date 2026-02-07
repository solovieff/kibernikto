import argparse
from dotenv import load_dotenv

from kibernikto.config import configure_logger, print_banner
from kibernikto.telegram import runner


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

    configure_logger()
    print_banner()

    runner.run_sync()


# Initialize bot and dispatcher
if __name__ == '__main__':
    start()
