# Windows and WSL2

Native Windows execution is unsupported. The Mac app and DMG do not install on Windows. WSL2 support is experimental; a complete Parallax task on a real Windows/WSL2 machine remains unverified.

Use a WSL2 Linux distribution with Python 3.10 or newer, Git 2.38 or newer, `bubblewrap` (`bwrap`), `socat`, and the Linux versions of your chosen coding-agent CLIs. Build workflows also need two usable independent providers. Installed CLIs and successful sign-in do not establish available provider quota.

In PowerShell, `wsl --list --verbose` shows the installed distributions and their WSL versions. WSL2 uses a real Linux kernel. See Microsoft's [WSL commands](https://learn.microsoft.com/en-us/windows/wsl/basic-commands) and [WSL2 architecture](https://learn.microsoft.com/en-us/windows/wsl/wsl2-about). This preflight does not install or reconfigure WSL.

Keep the project and tools in the distribution's Linux filesystem, such as `~/projects/your-project`. Do not use `/mnt/c`, another Windows drive, a shared filesystem, or a symlink that points to one. Microsoft also recommends keeping files on the same filesystem as the tools that use them. Parallax checks the actual mounted filesystem, including custom mount points, rather than trusting the path's spelling. See Microsoft's [filesystem guidance](https://learn.microsoft.com/en-us/windows/wsl/filesystems).

From a Parallax source download, run inside the intended distribution:

```sh
python3 -I scripts/check_wsl.py --project "$HOME/projects/your-project" \
  --provider codex --provider antigravity
```

Choose the providers you actually intend to use; `claude` is also available. Native Grok execution does not have a supported Linux sandbox boundary and will fail this check.

Use a trusted Linux Python installation outside the project. The script checks the WSL2 kernel marker, canonical project, interpreter and virtual-environment locations, mounted filesystems, and bounded CLI version diagnostics. Version commands run with an empty temporary home and a filtered Linux PATH, without inherited provider tokens or Python configuration. Raw CLI output is never included in the report. The script does not execute project code, sign in, run a model, or modify the project.

It also requires a real `bwrap` probe to create separate user, mount, PID and network namespaces. Synthetic temporary canaries must demonstrate an allowed read, an allowed scratch write, refusal of an ungranted read and a read-only write, and refusal of a connection to the host's loopback listener. No actual project or host home is mounted into that probe. Bubblewrap depends on the host's namespace capabilities; see the [upstream security model](https://github.com/containers/bubblewrap/blob/main/README.md).

An exit code of zero and `status: capabilities_verified` mean those capability checks passed on that machine. The report still says `wsl_acceptance: unverified`: authentication, provider tool enforcement, inference, and the complete product workflow need separate acceptance. An exit code of one means a required capability is missing or unverified. Native Windows, WSL1, an unidentified kernel, Windows executables, and unavailable namespaces fail closed. Do not disable sandboxing or host protections to make the preflight pass.

After the preflight, follow [the first-task guide](FIRST-TASK.md) for normal provider setup and execution. Initial Python dependency installation may need network access; the preflight does not establish an offline installation.

Before WSL2 can be advertised as supported, a disposable Linux-side project must complete baseline checks, an implementation, independent review, an explicit revision, human approval and local application. Verify cancellation and restart with the original consumed budget, sandbox read/write/network boundaries, and preservation of unrelated local edits. Team authorization and GitHub delivery need their own live checks when used. None of those results can be inferred from the capability report or from Mac tests.
