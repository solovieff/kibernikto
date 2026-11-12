import argparse
from dotenv import load_dotenv


def build_bridge(multi_agent: bool = False, vkusvill: bool = False):
    """Pick the agent for this process; the Telegram transport is identical for every preset."""
    from kibernikto.telegram.bridge import TelegramBridge, get_telegram_bridge

    if vkusvill:
        from kibernikto.ai.agent.vkusvill import build_vkusvill_agent

        return TelegramBridge(build_vkusvill_agent()), 'vkusvill'
    if multi_agent:
        from kibernikto.ai.agent.telegram.multi_agent import build_multi_agent

        return TelegramBridge(build_multi_agent()), 'multi-agent'
    return get_telegram_bridge(), 'default'


def start(outer_env=False):
    """Build the Telegram bot and start polling."""
    parser = argparse.ArgumentParser(description='Run Kibernikto')
    parser.add_argument('--env_file_path', metavar='env_file_path', required=False,
                        help='env file location', default='.env')
    parser.add_argument('--multi-agent', action='store_true', required=False,
                        help='use multi-agent system with subagent delegation', default=False)
    parser.add_argument('--vkusvill', action='store_true', required=False,
                        help='run the VkusVill shopping agent instead of the default one', default=False)

    args = parser.parse_args()

    if not outer_env:
        load_dotenv(dotenv_path=args.env_file_path)

    # Runtime imports construct settings and providers from the selected environment.
    from kibernikto.config import configure_logger, print_banner

    configure_logger()
    print_banner()

    from kibernikto.storage.config import validate_storage
    validate_storage()

    from kibernikto.ai.agent.core.config import print_agent_summary
    from kibernikto.telegram.agent.telegram_app import TelegramApp

    bridge, preset = build_bridge(multi_agent=args.multi_agent, vkusvill=args.vkusvill)
    print_agent_summary(preset)

    TelegramApp.from_bridge(bridge).run_polling()


if __name__ == '__main__':
    start()
