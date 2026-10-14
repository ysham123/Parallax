# Install the preview and finish your first task

Use the pinned 1.4.0 source below or the versioned source ZIP and `SHA256SUMS` supplied by your operator. This guide takes one local exercise through installation, a first task, result inspection, approval and application in Studio. Plugin and CLI build requests retain their existing integration behavior.

Before enrolling participants, the operator must finish the live acceptance checklist in [PILOT.md](PILOT.md). Completing this exercise checks setup; it does not establish model quality, productivity gains or pilot readiness.

## Install the preview

If your operator supplied an archive, check its SHA-256 against their `SHA256SUMS` before extracting it. On macOS, `shasum -a 256 archive.zip` prints the digest; on Linux use `sha256sum archive.zip`. A match identifies the supplied bytes; it is not a publisher signature. Extract into a new folder.

Otherwise, clone the pinned preview into a new folder:

```sh
git clone https://github.com/ysham123/Parallax.git Parallax-preview
cd Parallax-preview
git checkout --detach c2127aec7f4acc571247fafe8a7b4b5e47647e97
```

From that source folder, run:

```sh
PARALLAX_SOURCE="$PWD"
python3 scripts/parallax.py --version
python3 scripts/parallax.py doctor
```

The preview reports Parallax 1.4.0. First start prepares a private, hash-locked Python environment and needs access to the package registry. It does not install global packages. Use macOS with the native command sandbox for the initially verified pilot path. Linux requires working bubblewrap and user namespaces; a successful Linux project execution remains a separate acceptance gate.

You need Python 3.10+, Git 2.38+ and two available independent providers. A simple starting pair is Codex coordinating/checking and Claude implementing, using their existing signed-in CLIs. API transports are also supported. Verify your chosen providers have usable quota; sign-in detection cannot establish it. Model inference and provider charges belong to your accounts. The execution time limit is not a dollar cap.

## Choose a first task

Start with a bounded change in a disposable clone with meaningful checks. The bundled `examples/first-change` exercise is a setup check with no package dependencies. It is deliberately small and is not a demonstration of productivity value. Copy that folder into a new location outside the Parallax source before initializing it:

```sh
FIRST_CHANGE_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/parallax-first-task.XXXXXX")"
cp -R examples/first-change "$FIRST_CHANGE_ROOT/project"
cd "$FIRST_CHANGE_ROOT/project"
git init
git add .
git commit -m "First change exercise baseline"
python3 -m unittest discover -s tests -v
```

Git needs your normal author configuration for that explicit baseline commit. Expect two tests: the empty-input case errors with `ZeroDivisionError` and the numeric case passes. Keep the tests unchanged. In the same terminal, return to the Parallax source folder and open Studio for the exercise:

```sh
cd "$PARALLAX_SOURCE"
python3 scripts/parallax.py studio --workspace "$FIRST_CHANGE_ROOT/project"
```

Open the authenticated URL printed by the command and keep that link private. Local Studio does not require a hosted account. Provider credentials stay in their existing local stores.

## Start the task

In **New task**, choose the exercise project and describe the outcome:

> Make `average(values)` raise `ValueError("empty input")` when values is empty. Preserve the existing numeric results and keep the tests unchanged. Run the complete test suite.

Choose **Verified change**. Confirm Codex as coordinator and Claude as implementer, or another supported pair with independent review. Open **Configure team, task instructions, and checks**, click **Add check**, and paste this into **Command arguments**. Set **Package root** to `.` and choose a suitable timeout:

```json
["python3", "-m", "unittest", "discover", "-s", "tests", "-v"]
```

Click **Check readiness** and resolve any blocked setup. Readiness inspects setup; it does not run these tests or establish provider quota. Confirm the execution time limit, then click **Start task**. Local Studio uses local delivery. A connected workspace offers **Apply locally after approval** in the delivery selector. You do not need to save a recipe for this task.

## Inspect the result

Wait for **Awaiting approval**. The team prepares a separate candidate; your exercise files remain at the captured baseline while it runs. In **Evidence**, read the recorded check and review outcomes for the displayed candidate. Then inspect:

- **Changes:** `average.py` should reject empty input with `ValueError("empty input")`. The supplied tests should be unchanged.
- **Checks:** the recorded baseline should contain the empty-input error. The final test run should pass both tests on the candidate.
- **Reviews:** read the independent review and any remaining findings before deciding.

Unavailable or unrecorded evidence is not a passed check. You can download the verification record before application; a partial record is not acceptance. Independently read the change before approving it.

## Approve, then apply

Click **Approve candidate** to record your decision on the displayed candidate. Your exercise files should still be unchanged. Click **Apply locally** to apply that approved patch. In the same terminal, check the result yourself:

```sh
cd "$FIRST_CHANGE_ROOT/project"
python3 -m unittest discover -s tests -v
git status --short
git diff -- average.py tests/test_average.py
```

Both tests should pass. `average.py` should contain the fix and `tests/test_average.py` should have no diff. A personal workspace permits self-approval. In a team, another authorized human must approve; the requester and Owner cannot bypass that rule.

## If the candidate needs a correction

To practice correction, request one concrete improvement using **Revise candidate**. A revision starts from the saved candidate and original baseline with a new explicit budget. It gets fresh checks, review and approval. **New task from current project** captures your current files instead. If you changed the exercise project, preserve the old candidate and start that fresh task.

The hosted worker, invitation and GitHub App setup are optional later steps for this local exercise. Team evidence currently needs the paired worker online; an always-on team machine makes that requirement explicit. Draft PR delivery requires the configured App and a clean captured remote baseline. No merge or deployment happens automatically.

Pilot measurements are optional manual records. Record unknown time or usage as unknown, include failures and corrections, and compare the complete task with your usual workflow. Human labels annotate recorded evidence and cannot approve a candidate or waive a check. Follow [the evaluation protocol](PILOT-EVALUATION.md) for a real comparison; completing this small exercise does not establish productivity value.

## If setup stops

Read the recorded failure before retrying. Missing provider quota, unsupported command isolation and an offline machine require a setup remedy; a model reporting success is not a passed check. Preserve candidates and operation records. Recovery retains consumed budget. Report the task ID and relevant redacted error to the operator, with no credentials or private access links.

If the selected implementer exhausts its account quota, the task stops with the saved evidence. Restore capacity before resuming, or start a new task with another independent provider that you explicitly choose. Readiness can warn about a previously reported quota limit and reset time; the provider decides when capacity returns.
