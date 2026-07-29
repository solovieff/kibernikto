import argparse
from dotenv import load_dotenv

from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS
from kibernikto.config import configure_logger, print_banner
import kibernikto.ai.agent.telegram_agent as _tg_agent


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

    configure_logger()
    print_banner()

    if args.multi_agent:
        from kibernikto.ai.agent.telegram_agent import set_telegram_agent
        from kibernikto.ai.agent.extended.orchestrators import kibernikto_subagents_agent

        # Use the pre-built subagents agent (SubAgents delegation with all expert sub-agents).
        set_telegram_agent(kibernikto_subagents_agent)

    _tg_agent.kibernikto_telegram_agent.to_telegram().run_polling()


if __name__ == '__main__':
    start()