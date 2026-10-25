# .github

GitHub-specific configuration for the repository.

## Contents

- `workflows/ruff_pylint.yml` — "ruff-pylint" workflow. Runs `ruff format --check` and
  `ruff check` (including ruff's `PL` pylint rules) on every push to `main` and every pull request,
  using the project's `uv` toolchain via `astral-sh/setup-uv`.
- `workflows/test.yml` — "Test" workflow. Runs the `pytest` suite on the same triggers, separate
  from linting so each reports its own status check.
- `workflows/build.yml` — "Build" workflow. Builds a standalone binary for three targets
  (`macos-14`/arm64, `ubuntu-latest`, `windows-latest`) on every PR and every
  push to `main`. macOS is **Apple Silicon only** — the Intel runner (`macos-13`) is a deprecated,
  scarce image that queues for many minutes (plan I8); Intel Mac users run the arm64 build under
  Rosetta 2. A `version` job resolves the embedded version string **once** (so all legs
  embed the same string for a commit); each build leg writes the gitignored `model_meta/_version.py`,
  runs `pyinstaller model-meta.spec` (onedir; on macOS the spec **also** wraps the tree in
  `model-meta.app` — the staplable container notarization needs), gates on the `--version`/`--check`
  smoke test against the freshly built launcher (inside the `.app` on macOS), ad-hoc signs the macOS
  `.app` (arm64 canaries execute; **no** Developer ID / notarization here — that is `release.yml`'s
  `sign-macos` job), and packages per-OS (the `.app` tarred to `.tar.gz` on macOS, the onedir tree to
  `.tar.gz` on Linux / `.zip` on Windows). On PRs each leg writes a one-click download link to the
  run **Summary** (via `upload-artifact`'s `artifact-url` + `$GITHUB_STEP_SUMMARY`) so a reviewer
  never has to expand logs — Actions artifacts have no public URL, so the link needs a signed-in
  session and dies with the 14-day retention. **Holds no secrets** — it runs on untrusted fork PRs.
- `workflows/release.yml` — "Release (rolling latest)" workflow. Triggered by `workflow_run` on the
  **Build** workflow completing (not `needs:`), so it stays decoupled from the secret-free, fork-facing
  `build.yml` — a cancelled or failed Build never releases. A single job `if:` guard narrows the many
  `workflow_run` firings to the one that should publish: `conclusion == 'success'` **and** the triggering
  Build's `event == 'push'` **and** `head_branch == 'main'` **and** `repository == 'nuggylib/model-meta'`.
  Two jobs. **`sign-macos`** (`macos-14`) takes the ad-hoc `model-meta.app` from the triggering
  Build run (downloaded by `run-id` into an ephemeral keychain workflow), **Developer ID signs** it
  inner-to-outer (nested Mach-O → launcher → bundle) with `--options runtime --timestamp` (hardened
  runtime), **notarizes** it via the App Store Connect API (`notarytool submit --wait`, `notarytool log`
  dumped on failure), **staples** the ticket (so first launch works offline with no Gatekeeper prompt
  and no `xattr`), repackages under the identical archive name, and uploads it as `signed-macos-arm64`.
  It holds the signing **secrets** but only `actions: read` (**not** `contents: write` — it must not be
  able to touch releases/tags). **`publish`** (`ubuntu`, `needs: sign-macos`) downloads the
  Linux/Windows archives from the Build run (`pattern: release-*-x86_64` — macOS is `-arm64`, so this
  skips the ad-hoc one) **plus** the stapled `signed-macos-arm64` from this run, writes `SHA256SUMS`,
  force-moves the `latest` tag to the merged commit, and rolls the `latest` prerelease in place via
  `softprops/action-gh-release`. `publish` is the sole holder of `contents: write`. Both jobs carry the
  same `workflow_run` guard (`conclusion == 'success'` **and** the triggering Build's `event == 'push'`
  **and** `head_branch == 'main'` **and** `repository == 'nuggylib/model-meta'`); when `sign-macos`
  is skipped, `publish` (`needs:` it) is skipped too, so nothing releases off a PR/fork build.
- `release-notes-latest.md` — Body for the rolling `latest` prerelease (`release.yml` passes it as
  `body_path`). Per-OS download/extract/run steps: macOS is **Developer ID signed + notarized +
  stapled** (just download and run, offline-safe), with the `xattr -cr` quarantine step kept behind an
  "if you see a security warning" fallback for the un-notarized degraded path. Also the Rosetta 2 note
  for Intel Macs, the moving-`latest` caveat, and `SHA256SUMS` verification. macOS is launched from the
  `.app`'s inner `Contents/MacOS/model-meta` (it is a terminal app — never double-clicked). Keep it
  in sync with the README's "Download & Install" section.
- `workflows/qa_signoff.yml` — "QA Sign-off" workflow. Fails a PR until the author ticks the
  **Author** checkbox in the `## QA Sign-off` section of the PR body — the developer's explicit
  "I ran the QA Steps and they pass" acknowledgement. It reads the body from the event payload
  (no API token) and greps for a checked `**Author:**` line.
- `pull_request_template.md` — Default pull request description template. Pre-fills every new PR with a
  **Summary** (plus a flat **Changelog** list), numbered **manual QA Steps**, and a **QA Sign-off**
  checkbox the author ticks after running those steps. GitHub auto-populates the PR body from this file.

## Conventions

- CI must mirror the local dev commands documented in the root `README.md`
  (`uv sync`, `uv run pytest`, `uv run ruff ...`) so "green locally" means "green in CI."
- Use `uv sync --locked` in CI so a stale `uv.lock` fails the build instead of silently
  resolving different dependencies.
- Pin actions to a specific release, not a moving major tag. `astral-sh/setup-uv`'s v8
  series does **not** publish a floating `v8` tag (only `v8.x.y`), so pin the exact
  version (e.g. `@v8.3.2`) and bump deliberately.
- **`build.yml` pins every action to a full 40-char commit SHA** with a trailing `# vX.Y.Z`
  comment (a version *tag* is mutable — a compromised action re-tag would then run in CI).
  This is the stronger form of the pinning rule above; prefer it for new workflows and let a
  Dependabot bump move the SHA. (`qa_signoff.yml` still pins by tag — a safe follow-up is to
  migrate it to SHAs too.)
- **Artifact naming.** `build.yml` uploads canary artifacts on PRs
  (`model-meta-canary-pr<N>-<shortsha>-<target>`, 14-day retention, so a longer review keeps a
  live link) and stable release-named artifacts on pushes to `main` (`release-<target>`, 1-day
  retention, consumed by `release.yml`). Filename slugs use only `-` (never `+`/`.`, which break in
  URLs and download tooling); the embedded `--version` string keeps SemVer form
  (`0.1.0-canary.pr42+a1b2c3d`).
- On a `pull_request` event, `github.sha` is the ephemeral **merge** commit — use
  `github.event.pull_request.head.sha` for anything identifying the PR's actual code.
- **Rolling `latest` release.** There is exactly one moving `latest` prerelease, rebuilt on every
  push to `main`. `release.yml` **force-moves the `latest` tag** to the merged commit and clobbers the
  same-named assets in place — `softprops/action-gh-release` updates the release object but never moves
  an existing tag, hence the manual `git tag -f latest && git push -f`. Keep it `--prerelease`
  (`make_latest: false`) so it never steals the "Latest" badge from a future tagged `vX.Y.Z`. **GitHub
  Immutable Releases must stay DISABLED** while `latest` is a moving tag (it forbids tag moves + asset
  mutation). Link the explicit `…/releases/download/latest/<file>` asset URL, not
  `…/releases/latest/download/…` (which follows the "Latest" badge, not this prerelease).
- **`workflow_run` token + artifacts.** A `workflow_run`-triggered workflow gets a **read-only** token
  by default and its `github.*` fields describe the *triggering* run (it always runs from the default
  branch). Grant `contents: write` (release + tag push) **and** `actions: read` (cross-run
  `download-artifact`) on the job, and pull the upstream artifacts by
  `run-id: ${{ github.event.workflow_run.id }}` + `github-token` — they do not auto-transfer.
- Treat the PR body as untrusted input. Pass `github.event.pull_request.body` through an
  `env:` variable, never interpolate it directly into a `run:` script (prevents shell
  injection via a crafted description) — see `workflows/qa_signoff.yml`.
- The `**Author:**` marker text is a contract shared between `pull_request_template.md` and
  the `qa_signoff.yml` grep. Change them together, or the check fails closed on every PR.
- **Making QA Sign-off required:** the check reports the context `QA Sign-off` (the job's
  `name:`). A status check can only be marked required after it has reported at least once,
  so add it to `main`'s protection **after** the introducing PR has run it. Apply the
  setting once via the GitHub API rather than click-ops, e.g.:

  ```bash
  gh api --method POST repos/nuggylib/model-meta/rulesets --input - <<'JSON'
  {
    "name": "Require QA sign-off on main",
    "target": "branch",
    "enforcement": "active",
    "conditions": { "ref_name": { "include": ["~DEFAULT_BRANCH"], "exclude": [] } },
    "rules": [
      { "type": "required_status_checks",
        "parameters": { "strict_required_status_checks_policy": false,
          "required_status_checks": [ { "context": "QA Sign-off", "integration_id": 15368 } ] } }
    ]
  }
  JSON
  ```

  Confirm the exact context string on a completed run's Checks tab first (GitHub can render
  it as `workflow / job`), and use classic branch protection instead if the repo uses that
  model — do not configure both.

## macOS signing & notarization secrets

`release.yml`'s `sign-macos` job Developer ID signs + notarizes + staples the macOS `.app`. It
reads **seven repository secrets**. Their **values are added in the GitHub UI** (Settings → Secrets
and variables → Actions) and must **never** appear in source, in a plan, or in an assistant's
context — only the **names** below. They live only in `release.yml`, which never runs on PR/fork code.

| Secret name | What it is |
|-------------|------------|
| `MACOS_CERT_P12_BASE64` | The **Developer ID Application** certificate + private key, exported as a `.p12`, then base64-encoded (base64 so the multi-line blob survives as a secret). |
| `MACOS_CERT_PASSWORD` | The password protecting that `.p12` export. |
| `MACOS_KEYCHAIN_PASSWORD` | Any strong value; unlocks the throwaway CI keychain the cert is imported into. Not an Apple credential. |
| `MACOS_SIGN_IDENTITY` | The full identity string `Developer ID Application: <Name> (<TEAMID>)` passed to `codesign --sign`. |
| `AC_API_KEY_P8_BASE64` | The App Store Connect API key (`.p8`), base64-encoded (base64 to avoid newline mangling; decoded to a runner-temp file for `notarytool`). |
| `AC_KEY_ID` | The App Store Connect API **Key ID** (`--key-id`). |
| `AC_ISSUER_ID` | The App Store Connect API **Issuer ID** (`--issuer`). |

**Regenerating the Developer ID certificate** (needs the paid Apple Developer Program membership):
1. In **Keychain Access** (or the Apple Developer portal → Certificates), create/download a
   **Developer ID Application** certificate; make sure its private key is in your login keychain.
2. Export the certificate **with its private key** as a `.p12` (set an export password → that is
   `MACOS_CERT_PASSWORD`).
3. Base64-encode it and store as `MACOS_CERT_P12_BASE64` — e.g. `base64 -i cert.p12 | pbcopy`, then
   paste into the secret. Set `MACOS_SIGN_IDENTITY` to the cert's full `Developer ID Application: …`
   name (`security find-identity -v -p codesigning` prints it).

**Regenerating the App Store Connect API key** (the `notarytool` credential, independently revocable —
preferred over an app-specific password):
1. **App Store Connect → Users and Access → Integrations → App Store Connect API → Keys**, generate a
   key with the **Developer** role. Download the `.p8` **once** (it cannot be re-downloaded).
2. Copy the **Key ID** → `AC_KEY_ID` and the **Issuer ID** (top of the Keys page) → `AC_ISSUER_ID`.
3. Base64-encode the `.p8` → `AC_API_KEY_P8_BASE64` (`base64 -i AuthKey_XXXX.p8 | pbcopy`).

If a credential expires or is revoked, releases fail at the sign/notarize step (they do **not** ship
an unsigned binary). Rotate the affected secret; the degraded `xattr` fallback documented in the
release notes keeps users able to run an un-notarized build in the meantime.
