# Parallax Mac beta distribution

Parallax's first desktop build targets Apple Silicon on macOS15 or newer. It includes a native launcher, a pinned CPython runtime, all locked runtime dependencies, and the existing local Studio assets. The app's Help menu opens a bundled self-contained beta setup guide. Customers do not install Python or download Parallax dependencies on first launch. Coding agents and model-provider accounts remain separate, explicit setup steps.

This repository prepares artifacts locally. It does not publish downloads, configure automatic updates, upload signing secrets, or claim that an ad hoc build is an official release. The first customer distribution is an invited beta after the release gates below pass. Intel Macs and native Windows have no supported desktop artifact in this wave. See [Windows support](WINDOWS.md) for the WSL2 validation path when available.

## Reproducible inputs

`desktop/runtime-lock.json` pins the exact Astral `python-build-standalone` release, URL, compressed size and SHA256. The runtime is CPython3.13.16, release20261009, target `aarch64-apple-darwin`, `install_only_stripped`. A second hash-pinned `full` archive provides only upstream runtime metadata and license texts. Its compiler objects and build tools are not shipped. The upstream runtime reports a macOS11 deployment target; the app compiles for macOS15. The current locked `orjson` wheel has an actual macOS15 deployment target and `sqlite_vec` has a macOS14 target despite its macOS11 wheel filename. The builder inspects every Mach-O architecture and deployment target before signing; it refuses code above the advertised floor. Older macOS support requires a separately validated dependency set.

The build cache is private, owned by the current user and mode0700. Symlinked caches, writable ancestors without sticky protection and untrusted existing entries are refused before downloading. Downloads use exclusive random mode0600 staging files and a verified SHA256 before publication into the cache. Do not reuse a public or shared cache for signing builds.

`requirements.lock` pins all runtime packages and acceptable wheel hashes. The builder downloads only binary wheels with hashes at build time, then installs them offline into the fresh embedded runtime. It never copies the host's Python environment, installed provider state or customer project. The curated release inventory refuses private runtime data, credential files and source symlinks.

`Contents/Resources` includes Parallax's MIT license, runtime and dependency manifests, dependency license paths, upstream runtime license texts, source hashes and exact input locks. Python and wheels retain their own license files. The app remains relocatable: the launcher finds its interpreter relative to its own bundle, and starts it with `-I -B -m parallax.desktop`. Application state is stored outside the signed bundle.

Signing timestamps and filesystem-image metadata prevent identical DMG bytes across every build. Reproducibility here means pinned input provenance, a deterministic source inventory, exact package versions, an inspectable final file inventory and recorded artifact digests. The release receipt records the bytes that must be reviewed and published.

## Local review build

On an Apple Silicon Mac with Apple command-line developer tools:

```sh
python3 scripts/build_macos.py --adhoc
```

The builder compiles the native launcher, signs each nested Mach-O from inside out with empty entitlements, signs the app, runs strict nested signature verification, and imports the real embedded backend and native dependencies. The DMG contains the app, an Applications link and installation instructions.

Outputs default to `output/desktop/macos-arm64/`:

- `Parallax Beta.app`
- `parallax-1.4.0-macos-arm64-local-adhoc.dmg`
- `build-receipt.json`, including exact runtime, lock and DMG digests
- `bundle-inventory.json`, including every regular file digest and symlink destination

Apple's hardened-runtime library validation requires matching real Team IDs when Python loads native extensions. An ad hoc identity has no Team ID, so the local review build omits Hardened Runtime only on the embedded interpreter. The native launcher and other nested code retain Hardened Runtime. Developer ID builds retain it everywhere, use one team and require no unsafe library-validation exception. The build receipt records this local limitation.

Ad hoc signing provides local integrity checks. It does not identify the developer to Apple, establish Gatekeeper acceptance, or permit an official download. Do not tell beta users to disable Gatekeeper or bypass quarantine. This artifact is for local development and review only.

## Developer ID build and notarization

Apple Developer membership alone does not install a signing identity. The build machine needs a valid **Developer ID Application** certificate and its private key in Keychain. The selected ten-character Team ID must match that identity. The builder refuses missing, wrong-type or mismatched identities. It never exports private keys. If the matching key is in a dedicated keychain outside the default search list, pass `--keychain /absolute/path/to/signing.keychain-db` to the builder and notary command. The option inspects file metadata only and passes the path directly to Apple identity/signing tools. It does not open the keychain contents, change the global search list, unlock the keychain or accept a password. A read-only, user-owned keychain file is permitted; symlinked, missing or group/world-writable paths are refused. Unlock it manually through macOS when needed. A locked key or untrusted certificate chain must be resolved before signing; the builder fails closed if the identity is not valid.

```sh
python3 scripts/build_macos.py \
  --identity 'Developer ID Application: Your Organization (TEAMID1234)' \
  --team-id TEAMID1234 \
  --output /absolute/private/build-directory
```

The release mode adds secure timestamps and signs the DMG. No debug grants, unsigned-memory exception, disabled library validation, DYLD injection or JIT entitlement is included. The embedded Python interpreter is non-JIT; bundled native extensions carry the same signature.

Use an existing `notarytool` Keychain profile. Configure it through Apple's tooling outside source control; do not paste account passwords, App Store Connect private keys or app-specific passwords into chat, a repository, command examples or CI logs.

```sh
python3 scripts/notarize_macos.py \
  --build-receipt /absolute/private/build-directory/build-receipt.json \
  --identity 'Developer ID Application: Your Organization (TEAMID1234)' \
  --team-id TEAMID1234 \
  --keychain-profile parallax-notary \
  --request-id 00000000-0000-4000-8000-000000000001
```

Choose a new UUID for a new build and reuse it to recover the same operation. The notary script refuses an ad hoc build before contacting Apple. It validates the build identity and file inventory, records submission IDs before waiting, notarizes and staples the app, recreates the image with that accepted app, notarizes and staples the signed DMG, then runs ticket validation and Gatekeeper assessment. Its operation record distinguishes accepted, stapled and published; it always leaves publication false. It avoids printing Apple account or signing details.

Do not change app files or rebuild artifacts during an existing notarization operation. A changed digest is refused. A process interruption between a successful stapling mutation and its journal write can require inspection with Apple's tools and rebuilding a new signed candidate with a new receipt and operation; do not edit journal fields to bypass validation. Live notarization recovery remains unverified until a Developer ID identity and profile are available.

## Customer release gates

Before making the website's Mac download official:

1. Developer ID signature, secure timestamp, Apple notarization, stapled app and DMG tickets, and Gatekeeper acceptance all pass for the exact release bytes.
2. Download the quarantined artifact onto a fresh supported Mac without developer Python, install from the DMG and open it normally. Confirm onboarding, project-folder permissions, provider setup, Studio startup, quit/restart and durable workflow recovery.
3. Run an actual provider task, independent review, revision and human approval. Live migration acceptance is still unverified when an implementer refuses execution because of quota.
4. Confirm installed app privacy behavior, support/recovery instructions, download checksums, architecture labels and current beta limitations. Keep untested Intel and Windows downloads unavailable.

Team authorization and GitHub delivery have separate pilot acceptance gates. Verify remote pairing and revocation, real multi-account sign-in, GitHub App authorization, baseline checks, draft publication, CI/review feedback and recovery before advertising those capabilities as pilot-ready. Local synthetic fixtures do not establish their live readiness. These states are recorded separately from a signed desktop candidate.

The official signed task-environment path also needs validation before publication: current Python project provisioning creates its private venv from Parallax's interpreter. A hardened Developer ID interpreter may reject a project's native wheels because those wheels do not carry Parallax's Team ID. The local ad hoc build does not establish this behavior. Resolve and test that boundary without weakening the app's library-validation policy before claiming native project-dependency support.

There is no automatic updater in this first beta. Users replace the app with a separately signed and notarized later download after stopping active work. Durable state remains outside the app. Every update must carry a new version and pass these gates.

## Upstream references

- [Astral runtime distribution and licensing guidance](https://gregoryszorc.com/docs/python-build-standalone/main/running.html)
- [Pinned runtime release](https://github.com/astral-sh/python-build-standalone/releases/tag/20261009)
- [Apple Developer ID distribution](https://developer.apple.com/developer-id/)
- [Apple code signing tasks](https://developer.apple.com/library/archive/documentation/Security/Conceptual/CodeSigningGuide/Procedures/Procedures.html)
- [Apple notarization requirements](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)
- [Apple common notarization failures](https://developer.apple.com/documentation/security/resolving-common-notarization-issues)
