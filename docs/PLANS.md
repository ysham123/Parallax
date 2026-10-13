# Plans and licensing

Release builds include a free monthly allowance of new tasks. A Pro license key removes the limit. Development and source builds without a configured seller organization have no limits.

## What counts

Only new Build and Compare tasks count, by the time they started in the current calendar month (UTC). These never count:

- retrying a request that was already recorded
- resuming, recovering or repairing an existing task
- reviewing, approving, declining, applying locally or publishing a draft PR
- read-only consultation runs

When the allowance is used up, existing tasks stay fully available. New tasks resume when the month renews, or right away with Pro.

## Activating a key

- **Studio:** open **Settings** and enter the key in the plan row.
- **Command line:** `parallax license --activate` reads the key from a hidden prompt or standard input, so it never appears in shell history. `parallax license` shows the plan and this month's usage; `parallax license --deactivate` removes the key.

## What leaves your machine

The key, an opaque per-machine activation label and the seller organization ID are sent to the license service when you activate and about once a day afterwards. Nothing about your projects, prompts, code or task results is sent. If the service can't be reached, a previously validated key keeps working for 14 days.

The key is stored only in the private Parallax state directory, readable by your user alone.

## Configuration

`PARALLAX_LICENSE_ORG` sets the seller organization at runtime; `PARALLAX_UPGRADE_URL` sets the upgrade link shown when the allowance is used. Release builds set the organization in `src/parallax/license.py`.

The public website shows a pricing section only when the build sets `PARALLAX_PRICING` to JSON such as `{"freeTasks":5,"monthly":"$…","yearly":"$…","checkoutUrl":"https://…","founding":"…"}` (`yearly` and `founding` are optional). An unset or invalid value publishes no pricing; checkout links must use HTTPS. On Vercel, set it as a build environment variable.
