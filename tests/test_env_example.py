"""The shipped env example must parse with current settings and contain no superseded variable names."""

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from dotenv import dotenv_values

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / 'deploy' / 'tg_bots' / 'kibernikto' / 'kibernikto.env'
_SUPERSEDED_PREFIXES = ('OPENAI_', 'VOICE_', 'IMGBB_')
_SUPERSEDED_NAMES = {'TG_STICKER_LIST', 'AGENT_KIBERNIKTO_PROVIDER_KEY', 'AGENT_KIBERNIKTO_PROVIDER_CUSTOM_URL'}


class EnvExampleTests(unittest.TestCase):
    def test_no_superseded_variables(self) -> None:
        names = set(dotenv_values(EXAMPLE))
        self.assertEqual({n for n in names if n.startswith(_SUPERSEDED_PREFIXES)}, set())
        self.assertEqual(names & _SUPERSEDED_NAMES, set())

    def test_every_settings_class_parses_the_example(self) -> None:
        # Fresh interpreter: settings singletons are built at import time from the example only.
        script = textwrap.dedent("""\
            import os, sys
            from dotenv import dotenv_values
            env = {k: v for k, v in dotenv_values(sys.argv[1]).items() if v is not None}
            env['OPENROUTER_API_KEY'] = env.get('OPENROUTER_API_KEY') or 'offline-placeholder'
            os.environ.update(env)
            from kibernikto.telegram.config import TELEGRAM_SETTINGS
            from kibernikto.storage.config import STORAGE_SETTINGS
            from kibernikto.ai.agent.core.config import AGENT_KIBERNIKTO_SETTINGS
            from kibernikto.utils.image_hosting import IMAGE_HOSTING_SETTINGS
            from kibernikto.telegram.pre_processors._default import SETTINGS
            assert TELEGRAM_SETTINGS.STICKER_IDS and TELEGRAM_SETTINGS.MASTER_IDS
            assert AGENT_KIBERNIKTO_SETTINGS.WHO_AM_I and not AGENT_KIBERNIKTO_SETTINGS.WHO_AM_I.startswith('"')
            assert IMAGE_HOSTING_SETTINGS.HOSTING_PROVIDER == 'imgbb' and STORAGE_SETTINGS.DATA_BACKEND == 'file'
            assert SETTINGS.OPENAI_API_MODEL
            """)
        with tempfile.TemporaryDirectory() as home:
            env = {'PATH': os.defpath, 'HOME': home, 'USERPROFILE': home, 'PYTHONPATH': str(REPO),
                   'PYTHONDONTWRITEBYTECODE': '1'}
            if 'SYSTEMROOT' in os.environ:
                env['SYSTEMROOT'] = os.environ['SYSTEMROOT']
            proc = subprocess.run([sys.executable, '-c', script, str(EXAMPLE)], cwd=home, env=env,
                                  capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])

    def test_multi_agent_imports_with_only_the_main_provider_key(self) -> None:
        # Disabled experts (report: vsegpt) must not be built at import time on a fresh install.
        script = textwrap.dedent("""\
            import os, sys
            os.environ['OPENROUTER_API_KEY'] = 'offline-placeholder'
            from kibernikto.ai.agent.telegram.multi_agent import kibernikto_multi_agent
            assert kibernikto_multi_agent is not None
            assert 'kibernikto.ai.agent.harness.report_agent' not in sys.modules
            assert 'kibernikto.ai.agent.harness.scheduler_agent' not in sys.modules
            """)
        with tempfile.TemporaryDirectory() as home:
            env = {'PATH': os.defpath, 'HOME': home, 'USERPROFILE': home, 'PYTHONPATH': str(REPO),
                   'PYTHONDONTWRITEBYTECODE': '1'}
            if 'SYSTEMROOT' in os.environ:
                env['SYSTEMROOT'] = os.environ['SYSTEMROOT']
            proc = subprocess.run([sys.executable, '-c', script], cwd=home, env=env,
                                  capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])


if __name__ == '__main__':
    unittest.main()
