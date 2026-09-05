r"""Run a Telegram worker or a caller with local experts and one remote peer.

From the repository root (with the package dependencies available)::

    python -m examples.telegram_peers --env-file /path/to/worker.env \
        --instructions "Ты поэт. Пиши стихи по теме, размеру и настроению из запроса."
    python -m examples.telegram_peers --env-file /path/to/caller.env \
        --peer @swarm_host_bot --peer-name poet

Alternatively, copy this file and run it with an installed kibernikto package.
Use separate bot tokens and storage paths in the two environment files. Enable
Telegram bot-to-bot communication for both bots and check their access settings.
No demonstration message or model request is sent automatically at startup.
The example username is not a default: supply your own worker's address.
Peer descriptions guide the caller; --instructions configures this running bot.
Add --multimodal to the caller to delegate current photos, voice/audio or documents
without legacy preprocessing. Workers decode peer attachments automatically;
they need no extra flag. Without --multimodal, legacy text delegation is unchanged.
The selected dotenv file overrides matching inherited environment variables;
unlisted variables remain inherited. It is loaded before framework settings.
Use an absolute APP_STORAGE_SQLITE_PATH for persistent SQLite storage. Its
parent directories are created; :memory: remains ephemeral. Relative paths
are resolved from the working directory, not the dotenv file's directory.
"""
from __future__ import annotations

import argparse
import re
from collections.abc import Sequence
from pathlib import Path


def peer_address(value: str) -> int | str:
    """Validate a private peer address without importing the framework."""
    if re.fullmatch(r'[1-9][0-9]*', value):
        return int(value)
    if re.fullmatch(r'@[A-Za-z][A-Za-z0-9_]{4,31}', value):
        return value
    raise argparse.ArgumentTypeError('peer must be a positive private chat ID or @username')


def main(argv: Sequence[str] | None = None) -> None:
    """Parse arguments before loading any credential-dependent modules."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--env-file', type=Path, required=True, help='Explicit dotenv file for this bot')
    parser.add_argument(
        '--peer', type=peer_address,
        help='Remote @username or positive private chat ID; omit for a worker',
    )
    parser.add_argument('--peer-name', default='poet', help='Subagent name advertised to the caller')
    parser.add_argument(
        '--peer-description', default='Пишет стихи по заданной теме, размеру и настроению.',
        help='When the caller should delegate; does not configure the worker',
    )
    parser.add_argument(
        '--multimodal', action='store_true',
        help='Caller opt-in: send current photo, voice/audio or document to the peer; workers decode automatically',
    )
    parser.add_argument('--instructions', help='Additional instructions for this bot, not the remote peer')
    args = parser.parse_args(argv)
    if args.multimodal and args.peer is None:
        parser.error('--multimodal requires --peer; workers decode peer attachments automatically')

    from dotenv import load_dotenv

    env_file = args.env_file.expanduser()
    if not env_file.is_file():
        parser.error('--env-file must name an existing file')
    try:
        with env_file.open(encoding='utf-8') as stream:
            load_dotenv(stream=stream, override=True)
    except (OSError, UnicodeError):
        parser.error('could not read --env-file as UTF-8')

    from kibernikto.config import configure_logger
    from kibernikto.storage.config import STORAGE_SETTINGS, validate_storage

    configure_logger()

    if STORAGE_SETTINGS.DATA_BACKEND == 'sqlite' and STORAGE_SETTINGS.SQLITE_PATH != ':memory:':
        Path(STORAGE_SETTINGS.SQLITE_PATH).parent.mkdir(parents=True, exist_ok=True)
    validate_storage()

    from kibernikto.ai.agent.telegram.telegram_agent import TelegramAgent, set_telegram_agent

    if args.peer is not None:
        from kibernikto.ai.agent.extended.orchestrators import build_subagents_agent_with_tg_peers
        from kibernikto.ai.agent.telegram.peer_agent import TelegramPeerAgent

        if args.multimodal:
            peer = TelegramPeerAgent(
                peer=args.peer, name=args.peer_name, description=args.peer_description, multimodal=True,
            )
        else:
            peer = TelegramPeerAgent(peer=args.peer, name=args.peer_name, description=args.peer_description)
        agent = build_subagents_agent_with_tg_peers([peer])
        if args.multimodal:
            agent.capture_peer_media = True
    else:
        from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS
        from kibernikto.ai.agent.core.kibernikto_agent import model, model_settings

        agent = TelegramAgent(
            model=model, model_settings=model_settings, name=AGENT_KIBERNIKTO_SETTINGS.NAME,
        )
    if args.instructions is not None:
        agent.instructions(args.instructions)
    set_telegram_agent(agent)
    agent.to_telegram().run_polling()


if __name__ == '__main__':
    main()
