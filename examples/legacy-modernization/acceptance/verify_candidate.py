"""Run a fixed characterization suite; optionally require parser modernization.

For independent review, invoke this baseline-owned file with --candidate PATH.
The suite is public characterization evidence, not a hidden correctness oracle.
"""
import argparse
import ast
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def modernization_error(candidate):
    tree = ast.parse((candidate / "settlement.py").read_text(encoding="utf-8"))
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    if any(name.split(".")[0] == "optparse" for name in imports):
        return "settlement.py still imports the retired optparse component"
    if not any(name.split(".")[0] == "argparse" for name in imports):
        return "settlement.py must use argparse for the approved target component"
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, default=ROOT)
    parser.add_argument("--require-modernized", action="store_true")
    options = parser.parse_args()
    candidate = options.candidate.resolve()
    environment = {**os.environ, "SETTLEMENT_CANDIDATE": str(candidate), "PYTHONDONTWRITEBYTECODE": "1"}
    completed = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", str(ROOT / "tests"), "-v"],
                               env=environment, cwd=ROOT, timeout=120)
    if completed.returncode:
        return completed.returncode
    if options.require_modernized:
        error = modernization_error(candidate)
        if error:
            print("Modernization not accepted: " + error, file=sys.stderr)
            return 1
    print("Characterization accepted" + ("; parser modernization accepted" if options.require_modernized else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
