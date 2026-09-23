# Repository Release Checklist

A package is ready for first GitHub upload only when all checks below pass.

## Code and tests

- [ ] `python -m compileall -q src run.py`
- [ ] `python -m pytest -q`
- [ ] No test cache or `__pycache__` directories are included in the release ZIP.
- [ ] `git diff --check` reports no whitespace errors.

## Legacy safety

- [ ] V1 repository is not modified.
- [ ] V1 Excel reference exists under `migration/legacy/excel/`.
- [ ] V1 detail JSON archive exists under `migration/legacy/json/`.
- [ ] Legacy report reproduces all archived V1 Momentum/FIP values.

## Production safeguards

- [ ] Official universe source fails closed on malformed/suspiciously small input.
- [ ] Non-equity KAP markets are excluded from the equity universe.
- [ ] Calendar coverage is explicit; unknown years fail closed.
- [ ] Missing BIST sessions block indicator publication.
- [ ] IPO pre-listing sessions are not treated as missing data.
- [ ] Yahoo OHLCV is staged before canonical writes.
- [ ] Full-universe vendor downloads use batch mode when supported.
- [ ] Canonical price mutation is atomic.
- [ ] Partial-universe production publication is forbidden.
- [ ] Publication requires a PASS manifest and exact expected/published count match.

## GitHub readiness

- [ ] `.github/workflows/validation.yml` exists.
- [ ] `.github/workflows/daily_update.yml` exists.
- [ ] Production workflow has only the permissions it needs.
- [ ] Schedule uses `Europe/Istanbul`.
- [ ] README points to the first-push setup guide.
- [ ] GitHub Pages is not enabled until a V2 frontend entry point exists.
