# Live test repositories

Small repositories that the live API suite (`tests/live/`) copies into a
temporary git repository and hands to the real engine. They are data, not engine
tests: the root `conftest.py` never collects them and mypy skips them.

- `cli_pkg`: a src-layout package with a command-line entry point (understand).
- `script_proj`: a plain script project with no package (understand).
- `attack_repo`: a slow workload whose README, docstrings and comments carry
  prompt-injection text (the attack test). The test adds a `.env` file with a
  fresh canary value before it commits the repository.
