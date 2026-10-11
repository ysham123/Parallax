# Modernization fixture

Read `CONTRACT.md` and `task-manifest.json` before changing this project.

For this task, edit only `settlement.py`. Replace its optparse parser component with argparse. Preserve business rules in `ledger.py` and all supported behavior in the contract. Do not edit tests, sample data, the acceptance runner, manifest or contract. Do not add packages, network calls or deployment changes.

Run `python3 acceptance/verify_candidate.py --require-modernized` against the candidate. Report real command output and any compatibility uncertainty. The unchanged baseline is intentionally rejected only by the modernization guard; its characterization suite passes. An independent reviewer should invoke the baseline-owned runner with `--candidate /absolute/path/to/candidate` and inspect the delivered diff.
