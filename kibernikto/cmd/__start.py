import argparse
from dotenv import load_dotenv


def start(outer_env=False):
    """Build the Telegram bot and start polling."""
    parser = argparse.ArgumentParser(description='Run Kibernikto')
    parser.add_argument('--env_file_path', metavar='env_file_path', required=False,
                        help='env file location', default='.env')
    parser.add_argument('--multi-agent', action='store_true', required=False,
                        help='use multi-agent system with subagent delegation', default=False)

    args = parser.parse_args()

    if not outer_env:
        load_dotenv(dotenv_path=args.env_file_path)

    # Runtime imports construct settings and providers from the selected environment.
    from kibernikto.config import configure_logger, print_banner
    import kibernikto.ai.agent.telegram.telegram_agent as _tg_agent

    configure_logger()
    print_banner()

    from kibernikto.storage.config import validate_storage
    validate_storage()

    from kibernikto.ai.agent.core.config import print_agent_summary

    if args.multi_agent:
        from kibernikto.ai.agent.telegram.telegram_agent import set_telegram_agent
        from kibernikto.ai.agent.telegram.multi_agent import kibernikto_multi_agent

        # Use the pre-built subagents agent (SubAgents delegation with all expert sub-agents).
        set_telegram_agent(kibernikto_multi_agent)
        print_agent_summary('multi-agent')
    else:
        print_agent_summary('default')

    _tg_agent.kibernikto_telegram_agent.to_telegram().run_polling()


if __name__ == '__main__':
    start()