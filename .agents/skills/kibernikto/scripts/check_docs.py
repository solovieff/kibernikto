"""Check this skill's links/imports offline; optionally run existing unittest tests."""
from __future__ import annotations

import argparse
import ast
import importlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

SKILL = Path(__file__).resolve().parents[1]
REPO = SKILL.parents[2]
REMOVED_PATHS = {
    "kibernikto/telegram/runner.py",
    "kibernikto/ai/agent/core/history.py",
    "kibernikto/telegram/agent/telegram_agent.py",
}


def anchors(text: str) -> set[str]:
    result = set()
    for heading in re.findall(r"^#{1,6}\s+(.+)$", text, re.M):
        heading = re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")
        result.add(heading)
    return result


def static_checks() -> tuple[dict[str, int], list[tuple[str, str]]]:
    files = sorted(SKILL.rglob("*.md"))
    links = paths = blocks_count = 0
    blocks = []
    for file in files:
        text = file.read_text(encoding="utf-8")
        for target in re.findall(r"\[[^\]\n]+\]\(([^)\s]+)\)", text):
            if "://" in target or target.startswith("mailto:"):
                continue
            name, _, anchor = target.partition("#")
            resolved = (file.parent / name).resolve() if name else file
            assert resolved.exists(), f"{file.name}: missing link {target}"
            if anchor:
                assert anchor in anchors(resolved.read_text()), f"{file.name}: missing anchor {target}"
            links += 1
        for target in re.findall(r"`((?:kibernikto/|tests/|examples/|scripts/)[^`\s]+)`", text):
            if target in REMOVED_PATHS:
                assert not (REPO / target).exists(), f"Removed-path note now stale: {target}"
            else:
                base = SKILL if target.startswith("scripts/") else REPO
                assert (base / target).exists(), f"{file.name}: missing source path {target}"
            paths += 1
        for block in re.findall(r"^```python\n(.*?)^```", text, re.M | re.S):
            ast.parse(block)
            blocks.append((file.name, block))
            blocks_count += 1
    skill = (SKILL / "SKILL.md").read_text()
    assert skill.startswith("---\n")
    frontmatter = skill.split("---\n", 2)[1]
    description_match = re.search(r"^description: (.+)$", frontmatter, re.M)
    assert description_match is not None
    description = description_match.group(1)
    assert len(description) <= 60 and description.endswith(".")
    for key in ("name", "version", "author", "license", "platforms", "metadata"):
        assert re.search(rf"^{key}:", frontmatter, re.M), key
    for sibling in ("building-pydantic-ai-agents", "pydantic-ai-harness"):
        assert (SKILL.parent / sibling / "SKILL.md").exists()
    return {"markdown_files": len(files), "links": links, "source_paths": paths,
            "python_blocks": blocks_count}, blocks


def block_external_access(event: str, args: tuple) -> None:
    if event in {"socket.connect", "socket.getaddrinfo", "socket.bind", "socket.sendto"}:
        raise RuntimeError(f"Network disabled in docs check: {event}")
    if event == "open" and isinstance(args[0], (str, bytes)):
        path = Path(os.fsdecode(args[0]))
        name = path.name
        if name == ".env" or name.startswith(".env.") or name in {".git-credentials", "credentials"}:
            raise RuntimeError("Secret/config file access disabled in docs check")
        if ".git" in path.parts and name == "config":
            raise RuntimeError("Git credential-bearing config access disabled")


def runtime_checks(blocks: list[tuple[str, str]], run_tests: bool) -> dict[str, object]:
    sys.addaudithook(block_external_access)
    sys.path.insert(0, str(REPO))
    from pydantic_ai import models
    from pydantic_ai.models.test import TestModel
    from unittest.mock import patch

    models.ALLOW_MODEL_REQUESTS = False
    imports = set()
    # Eager expert singletons must not demand live providers or optional credentials.
    with patch("kibernikto.ai.agent.utils.infer_kibernikto_model", return_value=TestModel()):
        for _, block in blocks:
            for node in ast.walk(ast.parse(block)):
                if isinstance(node, ast.ImportFrom):
                    assert node.module is not None and not node.level
                    module = importlib.import_module(node.module)
                    for alias in node.names:
                        getattr(module, alias.name)
                        imports.add(f"{node.module}.{alias.name}")
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        importlib.import_module(alias.name)
                        imports.add(alias.name)
        for file, block in blocks:
            if file == "CORE-AGENT.md" and "asyncio.run(smoke())" in block:
                exec(compile(block, file, "exec"), {"__name__": "__docs_smoke__"})
        from kibernikto.ai.agent.extended.orchestrators import build_subagents_agent_with_tg_peers
        from kibernikto.ai.agent.telegram.peer_agent import TelegramPeerAgent
        from pydantic_ai_harness.subagents import SubAgent

        peer = TelegramPeerAgent(peer=200, name="offline", description="Offline test peer")
        assert SubAgent(peer).agent is peer
        parent = build_subagents_agent_with_tg_peers([peer])
        assert parent is not None
    result: dict[str, object] = {"imports": len(imports), "core_smoke": "passed",
                                "real_subagent_and_builder": "passed"}
    if run_tests:
        # Restore real inference in modules whose import bound the mocked function.
        from kibernikto.ai.agent import utils
        from kibernikto.ai.agent.extended import orchestrators
        orchestrators.infer_kibernikto_model = utils.infer_kibernikto_model
        # Example tests intentionally load a temporary bot.env. The audit hook still
        # rejects production .env files; the child cwd/home/storage stay isolated.
        os.environ.pop("PYTHON_DOTENV_DISABLED", None)
        suite = unittest.defaultTestLoader.discover(str(REPO / "tests"), top_level_dir=str(REPO))
        tested = unittest.TextTestRunner(verbosity=1).run(suite)
        result.update(tests_run=tested.testsRun, failures=len(tested.failures), errors=len(tested.errors))
        if not tested.wasSuccessful():
            print(json.dumps(result, sort_keys=True), flush=True)
        assert tested.wasSuccessful(), "Offline tests failed"
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tests", action="store_true", help="also run existing offline unittest suite")
    parser.add_argument("--isolated-child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    counts, blocks = static_checks()
    if args.isolated_child:
        report = {**counts, **runtime_checks(blocks, args.tests)}
        print(json.dumps(report, sort_keys=True))
        return
    # No inherited API keys, dotenv loading, home config or live storage paths.
    with tempfile.TemporaryDirectory(prefix=".docs-check-", dir=SKILL) as tmp:
        env = {
            "PATH": os.defpath,
            "HOME": tmp,
            "USERPROFILE": tmp,
            "TMPDIR": tmp,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHON_DOTENV_DISABLED": "1",
            "OPENROUTER_API_KEY": "offline-docs-not-a-real-key",
            "VSEGPT_API_KEY": "offline-docs-not-a-real-key",
            "AGENT_KIBERNIKTO_MODEL_NAME": "openrouter:test/offline",
            "AGENT_KIBERNIKTO_IMAGE_MODEL_NAME": "",
            "APP_STORAGE_DATA_BACKEND": "file",
            "APP_STORAGE_MEDIA_BACKEND": "file",
            "APP_STORAGE_FILESTORE_LOCATION": tmp,
            "LOGFIRE_SEND_TO_LOGFIRE": "false",
        }
        # Required for Python process startup on Windows, not application secrets.
        if "SYSTEMROOT" in os.environ:
            env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
        command = [sys.executable, "-B", str(Path(__file__).resolve()), "--isolated-child"]
        if args.tests:
            command.append("--tests")
        completed = subprocess.run(command, cwd=tmp, env=env, check=False)
        raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
