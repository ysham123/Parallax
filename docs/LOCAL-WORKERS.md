# Hosted Studio with a local coding worker

Keep Studio on Vercel and the authenticated relay on Railway. Pair a Mac or compatible Linux machine to run the complete Parallax engine locally with its existing CLI sign-ins. The worker makes outbound HTTPS requests; it does not open a listener, expose SSH, mount files remotely, or copy provider credentials to Railway.

## Connect

Install this repository and its pinned Python dependencies on the worker machine. Open hosted Studio, choose **Machines**, and generate a pairing code. It expires after five minutes and can be consumed once.

Run:

~~~sh
parallax worker --url https://YOUR-STUDIO.vercel.app --workspace /absolute/path/to/project --name "My Mac"
~~~

Paste the code into the hidden terminal prompt. Repeated --workspace flags approve additional exact project roots. A private --pair-file can be used for operator automation; do not put codes or access keys in arguments or URLs. A separate state directory is created under Parallax's state folder with a mode-0600 scoped connection file. Use --state for another private directory outside every project. A state directory has one process owner. Changing its relay or approved project list requires new state and pairing.

Choose the machine from Studio's **Execution machine** menu. Models, efforts, project assessment, profiles, history, checks, reviews, receipts, and integration refer to that selected machine. There is no automatic fallback to Railway or another machine.

Anyone with access to this private operator Studio can run tasks in the approved projects. Do not pair an unrelated customer's machine to the same workspace. This is not a multi-tenant account system.

## Execution and evidence

The existing local engine owns snapshots, worktrees, provider sessions, concurrency, independent reviews, checks, and destination revalidation. Verified integration changes the local approved project. Work does not move into a Railway project clone.

Studio operations cross a method/path allowlist. The worker validates it again and resolves requested projects against exact approved roots. Symlink escapes and parent directories are rejected. A worker token can fetch assigned requests and submit its evidence, but cannot log in to Studio, pair another machine, control other workers, or submit new run commands.

API connections can be inspected and existing connections used. Credential creation, replacement, and deletion remain local; the relay rejects these operations and does not persist API keys in its request journal.

Run results, diffs, check output, and ordered events are mirrored to the private Railway workspace for graph inspection and replay. These may contain project information. Provider auth caches and arbitrary source files are not mirrored. Local inference still communicates with each provider's service.

## Disconnection and recovery

If the network drops, already authorized local runs continue, including authorized verified integration. Studio marks the machine offline and can show saved evidence. New commands are rejected until the worker reconnects. A sleeping or shut-down Mac cannot execute work.

Requests are durable and have unique identifiers. The local dispatch journal returns the same result for duplicate delivery. A crash between engine dispatch and recording its reply produces an explicit reconciliation error instead of repeating the action. Expired requests that have not started are rejected. A timed-out browser response may still finish locally; inspect history before retrying.

Stopping the worker interrupts active processes through the existing engine and preserves recovery state. Restart with the same state and approved projects to reconnect. Interrupted runs need deliberate Resume and reconciliation; no automatic integration or redispatch happens on restart.

**Disconnect** in Machines revokes the scoped token. A connected worker observes revocation and stops its engine. An offline worker learns of revocation when it reconnects, so revocation cannot instantly cancel offline work. Stop the local process directly when immediate cancellation is needed.

Run the worker in a terminal for now. Login-time installation, automatic boot, and an always-awake cloud worker are not configured by pairing.
