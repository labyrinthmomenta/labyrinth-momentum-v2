# Repository Setup

This checklist is for the first GitHub upload of Labyrinth Momentum V2.

## 1. Create a separate repository

Create a new empty repository, for example:

`labyrinth-momentum-v2`

Do **not** reuse or overwrite the V1 repository. V1 remains the immutable reference.

For the cleanest first push, create the GitHub repository without adding another README, `.gitignore`, or license during repository creation; those files are already present in this package.

## 2. Keep the default branch as `main`

The included scheduled workflow runs from the repository's default branch. `main` is the recommended default.

## 3. Push the complete repository

Make sure hidden files are included, especially:

- `.github/workflows/validation.yml`
- `.github/workflows/daily_update.yml`
- `.gitignore`
- `.gitattributes`

The archived V1 Excel/JSON files under `migration/legacy/` are intentional regression fixtures.

## 4. Confirm the first Validation workflow

The first push should automatically run **Validation**. Do not run production until Validation is green.

Expected local release-candidate baseline:

- 58 unit/integration tests PASS
- 594/594 V1 Excel ↔ JSON regression matches

## 5. Check Actions write permissions

The production workflow declares `contents: write` because it commits:

- `data/labyrinth.db`
- `docs/data/`
- `migration/reports/`

If repository or organization policy prevents `GITHUB_TOKEN` write access, the final `git push` will fail safely after the calculations. Adjust repository Actions policy only if required by your GitHub account/organization settings.

## 6. First live run: use a completed trading day

Before the first full production bootstrap, run **Daily Production Update** manually from the Actions tab.

If BIST is still trading, provide the previous completed trading day in the optional `as_of` input. If the market is closed and Yahoo's daily bar is final, leaving `as_of` blank is appropriate.

The workflow order is:

1. Tests
2. Live KAP/BIST/Yahoo preflight
3. Full official-universe sync
4. Incremental/batched OHLCV bootstrap
5. Data-quality validation
6. Calculation
7. Publication gate
8. V1 legacy audit
9. Commit generated DB/data only after PASS

## 7. Verify the first generated commit

After a successful production run, confirm that the bot commit contains:

- `data/labyrinth.db`
- `docs/data/manifest.json`
- `docs/data/screener.json`
- `docs/data/details/*.json`
- refreshed `migration/reports/v1_v2_comparison.json`

Inspect `docs/data/manifest.json`. It must show:

- `status = PASS`
- `dry_run = false`
- `securities_published = securities_expected`

## 8. Leave GitHub Pages disabled for now

The current milestone produces the validated data layer, but does not yet include the final V2 frontend entry page. Enable Pages after `docs/index.html` and the frontend data contract have been added/tested.

## 9. Branch protection consideration

The scheduled workflow commits generated data to the default branch. If you later enable branch protection, configure it so the authorized GitHub Actions workflow can still make the intended generated-data commit, or move publication persistence to a dedicated branch/storage design.

## 10. Scheduled run

The production workflow is configured for weekdays at:

`20:15 Europe/Istanbul`

The schedule uses an explicit IANA timezone rather than a manually converted UTC offset.
