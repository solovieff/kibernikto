from kibernikto.cmd import start
from kibernikto.telegram import comprehensive_dispatcher

if __name__ == '__main__':
    # for service messages
    from kibernikto.telegram import service
    # for default commands
    from kibernikto.telegram import commands

    # Initialize bot and dispatcher
    start(outer_env=True)
