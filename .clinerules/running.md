Use the Python version and dependencies declared in pyproject.toml.
Run offline regression tests with the existing environment: python -m unittest discover -s tests -q.
IDE run configurations are optional and are not a prerequisite.
Keep live Telegram/model checks explicit: they send messages and may spend API credits.
Never start a second poller for a bot already running.
