# First task in the development preview

Use the versioned source ZIP supplied by the pilot operator. The public 1.3.0 download does not contain this workflow. Before enrolling participants, the operator must finish the live acceptance checklist in [PILOT.md](PILOT.md). This guide and the bundled exercise make setup reproducible; they do not establish model quality or pilot readiness.

## Install the supplied build

Check the archive's SHA-256 against the operator's `SHA256SUMS` before extracting it. On macOS, `shasum -a 256 archive.zip` prints the digest; on Linux use `sha256sum archive.zip`. A match identifies the supplied bytes; it is not a publisher signature. Extract into a new folder, then run these commands from that source folder:

```sh
python3 scripts/parallax.py --version
python3 scripts/parallax.py doctor
```

The preview reports Parallax 1.4.0. First start prepares a private, hash-locked Python environment and needs access to the package registry. It does not install global packages. Use macOS with the native command sandbox for the initially verified pilot path. Linux requires working bubblewrap and user namespaces; a successful Linux project execution remains a separate acceptance gate.

You need Python 3.10+, Git 2.38+ and two available independent providers. A simple starting pair is Codex coordinating/checking and Claude implementing, using their existing signed-in CLIs. API transports are also supported. Verify your chosen providers have usable quota; sign-in detection cannot establish it. Model inference and provider charges belong to your accounts. The execution time limit is not a dollar cap.

## Choose a first task

Start with a bounded change in a disposable clone with meaningful checks. The bundled `examples/first-change` exercise is a setup check with no package dependencies. It is deliberately small and is not a demonstration of productivity value. Copy that folder into a new location outside the Parallax source before initializing it:

```sh
cp -R examples/first-change /absolute/path/to/first-change
cd /absolute/path/to/first-change
git init
git add .
git commit -m "First change exercise baseline"
python3 -m unittest discover -s tests -v
```

Git needs your normal author configuration for that explicit baseline commit. The empty-input case should fail with `ZeroDivisionError`; the existing numeric cases should pass. Keep those tests unchanged. Open Studio from the Parallax source folder:

```sh
python3 scripts/parallax.py studio --workspace /absolute/path/to/first-change
```

Open the authenticated URL printed by the command and keep that link private. Local Studio does not require a hosted account. Provider credentials stay in their existing local stores.

## Delegate, inspect and deliver

In **New task**, choose the exercise project and describe the outcome:

> Make `average(values)` raise `ValueError("empty input")` when values is empty. Preserve the existing numeric results and keep the tests unchanged. Run the complete test suite.

Choose **Verified change**. Confirm the two providers, instructions and checks. Use a check with argv `python3`, `-m`, `unittest`, `discover`, `-s`, `tests`, `-v` and a suitable timeout. **Check readiness** should identify setup issues before starting. Per-task checks and instructions are captured on this task; saving a reusable recipe is optional.

For your first task, choose local delivery. The team prepares a separate candidate; your exercise files remain at the captured baseline while it runs. Read **Candidate result** for the change, recorded final checks, independent review, remaining uncertainty and human/delivery status. Then inspect **Changes**, **Checks** and **Reviews**, including failed baseline evidence and fresh final results. Unavailable or unrecorded evidence is not a passed check. You can download the verification record before application; a partial record is not acceptance. Independently read the change before approving it.

To practice correction, request one concrete improvement using **Revise candidate**. A revision starts from the saved candidate and original baseline with a new explicit budget. It gets fresh checks, review and approval. **New task from current project** captures your current files instead. If you changed the exercise project, preserve the old candidate and start that fresh task.

**Approve candidate** records a decision. **Apply locally** is a separate action. After application, run the checks yourself and inspect Git status/diff. A personal workspace permits self-approval. In a team, another authorized human must approve; the requester and Owner cannot bypass that rule.

The hosted worker, invitation and GitHub App setup are optional later steps for this local exercise. Team evidence currently needs the paired worker online; an always-on team machine makes that requirement explicit. Draft PR delivery requires the configured App and a clean captured remote baseline. No merge or deployment happens automatically.

Pilot measurements are optional manual records. Record unknown time or usage as unknown, include failures and corrections, and compare the complete task with your usual workflow. Human labels annotate recorded evidence and cannot approve a candidate or waive a check. Follow [the evaluation protocol](PILOT-EVALUATION.md) for a real comparison; completing this small exercise does not establish productivity value.

## If setup stops

Read the recorded failure before retrying. Missing provider quota, unsupported command isolation and an offline machine require a setup remedy; a model reporting success is not a passed check. Preserve candidates and operation records. Recovery retains consumed budget. Report the task ID and relevant redacted error to the operator, with no credentials or private access links.
