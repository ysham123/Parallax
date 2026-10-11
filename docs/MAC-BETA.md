# Using the Parallax Mac beta

The desktop beta opens local Studio for one project on your Mac. It includes the Python runtime and Parallax dependencies. Git, your project's toolchain, and your coding-agent or model-provider account are separate requirements. This build targets Apple Silicon and macOS 15 or newer.

The current artifact is a local review build. An official customer download still needs Developer ID signing, notarization and fresh-Mac acceptance. Do not distribute the ad hoc review DMG or ask customers to bypass macOS security protections. See [distribution and release gates](MAC-DISTRIBUTION.md).

## First launch of an accepted download

1. Download the signed, notarized DMG from the published Parallax download page and compare its checksum with the release receipt. The download is not published yet.
2. Open the DMG and drag **Parallax Beta** into **Applications**. Open the app normally.
3. Select **Choose folder** and choose the project you want to change. Selecting a folder does not start agents.
4. Select **Open local Studio**. The app starts an authenticated runtime on this Mac and opens Studio in your default browser.
5. Follow **Your first task** below. The launcher's **Help** action opens a bundled version of these setup instructions without a source download.

Keep the app open while work runs. **Open Studio** reopens the same local session. Closing a browser tab leaves the runtime running. Use **Stop local Studio** to stop work and retain its evidence. Quitting a running app asks whether to stop work or keep working. **Show Parallax** in the app menu reopens its launcher window.

Studio uses isolated candidate copies. Inspect the diff, checks and independent review, request a revision if needed, and make a fresh approval decision before delivery. Approval and applying a patch are separate actions. Team and GitHub delivery remain subject to their own setup and live acceptance requirements.

## Your first task

Use an existing Git repository that has meaningful checks and a small bug you can recognize. You do not need the source ZIP or a separate Python installation to open Studio. Your project's own tools may still need installation. The [source first-change exercise](FIRST-TASK.md) is optional and has its own source-install requirements.

1. Open **Connections** in Studio. Use installed, signed-in coding-agent CLIs, or select **API key** to save a provider key in macOS Keychain. The desktop runtime does not inherit shell-exported API keys; environment-variable credentials are unavailable through this launcher.
2. In **New task**, keep **Verified change** and open **Configure team, task instructions, and checks**. Select usable providers for implementation and independent review. A detected sign-in does not establish remaining quota.
3. Write a bounded request, for example: `Fix [observed behavior] in [file/function]. Preserve the public interface. Add regression tests for [two cases]. Run [project test command]. Return a reviewed candidate for approval.` Replace every bracketed part with your project's details. Add the real check commands and acceptance criteria in the task settings.
4. Select **Check readiness** and resolve each blocked setup issue before selecting **Start task**. Readiness discovers checks; the workflow runs them.
5. Inspect the saved candidate, check output and independent review. Use **Revise candidate** for a correction, then approve the fresh candidate when satisfied. Select **Apply locally** separately to deliver the approved change. GitHub delivery is an optional later setup with separate acceptance requirements.

## State and privacy

Each selected project's canonical path identifies a separate beta state directory under:

```text
~/Library/Application Support/Parallax/Beta/projects/
```

Task records, evidence and local settings live there. The application bundle contains software, not your project history. Install the app before starting tasks and keep it at that location. Moving or replacing the app leaves saved state intact, but moving it after Python task dependencies have been provisioned can block startup because saved interpreter links reference the old location. The beta refuses those links rather than running a previous interpreter. Keep that state for recovery; do not edit its links or identity file. Moving a project also changes its identity for this beta.

The runtime listens on `127.0.0.1` only. Its authenticated launch link is private; Studio exchanges that link for a browser cookie and removes the token from the address bar. Do not share launch links or state directories. The beta does not automatically pair or share your Mac with a hosted workspace.

Selected agents and model providers may receive project context while a task runs, according to their configuration. Provider accounts, usage limits and charges remain yours. The launcher does not collect your account passwords, install agents, or sign you into a provider. Starting Studio needs no Parallax dependency download; project setup and inference can need network access.

## Recovery, replacement and removal

If startup fails, verify that the project still exists and that another beta instance is not using its state. Select **Try again**. Reopen Studio for the same project to inspect recovered task state. A recovery attempt does not reset the task's consumed budget.

There is no automatic updater. Stop active work and quit the app before replacing it at the same installed path with a later signed, notarized version. Keep a private backup of your beta state before upgrading. Python dependency caches include their runtime identity and are rebuilt when that identity changes. Restoring a backup must happen while the runtime is stopped; never merge two live database directories.

Removing the app leaves the project's original files and saved beta state in place. Treat any later removal of saved task evidence as a separate deliberate operation. For support, use the [Parallax issue tracker](https://github.com/ysham123/Parallax/issues) and include the app version, macOS version, architecture and a sanitized description of the failure. Exclude launch tokens, provider keys and private project content. The beta does not send reports automatically.

## Verification still required

Developer ID Python uses Apple's library validation. Project-specific native Python dependencies need a validated task-interpreter policy; successful imports in an ad hoc build do not prove they will work in the signed app. Native launcher interactions, clean-Mac installation, notarization, and a complete live-provider workflow must be checked on the exact customer artifact before release.
