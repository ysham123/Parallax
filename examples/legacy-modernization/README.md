# Modernize one legacy component

A synthetic settlement batch job keeps an old optparse construction API. Its CLI is used by scheduled commands; its CSV is consumed elsewhere. Replace only the parser component with argparse while preserving the recorded behavior. The business rules, tests and fixed input/output remain unchanged.

This dependency-free fixture works on Python 3.10 and 3.13. From this folder, one command verifies the existing baseline:

```sh
python3 acceptance/verify_candidate.py
```

It runs 34 black-box characterization tests. To see the fixed batch report:

```sh
python3 settlement.py --input sample-input/transactions.csv
```

The result must match `tests/data/report.csv`. The task manifest and `CONTRACT.md` define the compatibility boundaries, including rounding/refunds, rejected input, output preservation and argument values that look like options. Python's current docs mark `OptionParser(option_list=...)` deprecated; they retain optparse itself and caution that an argparse migration can change behavior. This is a chosen component upgrade, not a claim that the module is removed or vulnerable. [Official documentation](https://docs.python.org/3.13/library/optparse.html#creating-the-parser).

Copy this folder into a disposable location **outside** the Parallax source, initialize your normal Git baseline, and verify it before delegating. Follow [the preview first-task guide](../../docs/FIRST-TASK.md) for local Studio installation, providers, sandbox and approval/delivery. You need two usable independent providers, not merely two detected sign-ins.

Use **Modernize one component** when available in your supplied preview. Otherwise use **Safe refactor** with the task instructions below. Recipe names express a task focus; they do not create new agent permissions or specialist-role types.

> Replace the optparse parser in settlement.py with argparse. Preserve CONTRACT.md v1.0, including hyphen/option-looking filenames, filter-before-output safety, inclusive dates, rounding, refunds, CSV bytes, CLI defaults and exit codes. Change only settlement.py; keep ledger.py, tests, sample data, the acceptance runner and manifest unchanged. Use the existing baseline and require fresh independent review. Run python3 acceptance/verify_candidate.py --require-modernized. Review uncertainty explicitly; do not change acceptance criteria to make the task pass.

Configure that final command as argv `python3`, `acceptance/verify_candidate.py`, `--require-modernized`. Before the edit, characterization passes and the guard intentionally refuses the legacy component. After the edit, all characterization and the guard must pass. Run on both interpreters when available, using their actual installed executable paths; do not assume changing a model or recipe installs Python.

An independent reviewer can keep this baseline-owned acceptance runner outside the candidate:

```sh
python3 /path/to/baseline/acceptance/verify_candidate.py --candidate /path/to/candidate --require-modernized
```

The suite is public characterization evidence, not a hidden oracle. For a real repository, the maintainer should hold independent cases outside the agent-readable tree and approve the compatibility contract first. Inspect the exact diff, request a saved-candidate correction if needed, obtain fresh approval and explicitly apply locally. A team needs another authorized human. GitHub publication requires separate configured delivery and live acceptance; this fixture makes no remote request.

The fixture and temporary local migration checks establish a runnable exercise and discriminatory tests. They do not establish an agent completed a real migration, faster development, universal equivalence, enterprise security or paid demand. See [the modernization scope](../../docs/LEGACY-MODERNIZATION.md) and the existing [pilot live gates](../../docs/PILOT.md).
