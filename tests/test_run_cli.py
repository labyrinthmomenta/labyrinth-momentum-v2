import sys
from datetime import date
from types import SimpleNamespace

import run


def test_parse_args_accepts_adjustment_backfill(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run.py",
            "adjustment-backfill",
        ],
    )

    args = run.parse_args()

    assert args.command == "adjustment-backfill"


def test_main_runs_adjustment_backfill_without_daily_pipeline(
    monkeypatch,
    tmp_path,
    capsys,
):
    calls = {}

    class FakeDatabase:
        def __init__(self, path):
            calls["db_path"] = path
            self.conn = object()

        def initialize(self):
            calls["initialized"] = True

        def close(self):
            calls["closed"] = True

    class FakeYahooProvider:
        pass

    class FakeSummary:
        requests_planned = 2
        provider_calls = 2
        records_fetched = 4
        records_accepted = 3
        records_inserted = 3
        records_updated = 0

    def fake_backfill(
        conn,
        provider,
        *,
        as_of,
        tickers=None,
    ):
        calls["conn"] = conn
        calls["provider"] = provider
        calls["as_of"] = as_of
        calls["tickers"] = tickers
        return FakeSummary()

    def forbidden_daily_pipeline(**kwargs):
        raise AssertionError(
            "adjustment-backfill must not enter daily pipeline"
        )

    monkeypatch.setattr(
        run,
        "Database",
        FakeDatabase,
    )

    monkeypatch.setattr(
        run,
        "YahooProvider",
        FakeYahooProvider,
    )

    monkeypatch.setattr(
        run,
        "run_adjustment_backfill",
        fake_backfill,
        raising=False,
    )

    monkeypatch.setattr(
        run,
        "run_daily_pipeline",
        forbidden_daily_pipeline,
    )

    db_path = tmp_path / "backfill.db"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run.py",
            "adjustment-backfill",
            "--db",
            str(db_path),
            "--as-of",
            "2026-09-30",
            "--tickers",
            "ASELS,THYAO",
        ],
    )

    result = run.main()

    assert result == 0
    assert calls["db_path"] == str(db_path)
    assert calls["initialized"] is True
    assert calls["closed"] is True
    assert isinstance(
        calls["provider"],
        FakeYahooProvider,
    )
    assert calls["as_of"].isoformat() == "2026-09-30"
    assert calls["tickers"] == {
        "ASELS",
        "THYAO",
    }

    output = capsys.readouterr().out

    assert "SUCCESS adjustment-backfill" in output
    assert "inserted=3" in output



def test_parse_args_accepts_vcp_oos(
    monkeypatch,
):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run.py",
            "vcp-oos",
            "--as-of",
            "2026-08-31",
        ],
    )

    args = run.parse_args()

    assert args.command == "vcp-oos"
    assert args.as_of == "2026-08-31"


def test_main_vcp_oos_requires_explicit_as_of(
    monkeypatch,
    capsys,
):
    def forbidden_runner(*args, **kwargs):
        raise AssertionError(
            "vcp-oos runner must not run "
            "without explicit --as-of"
        )

    monkeypatch.setattr(
        run,
        "run_frozen_vcp_oos",
        forbidden_runner,
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run.py",
            "vcp-oos",
        ],
    )

    result = run.main()

    assert result == 2

    output = capsys.readouterr().out

    assert (
        "FAILED vcp-oos: --as-of is required"
        in output
    )


def test_main_runs_vcp_oos_without_daily_pipeline(
    monkeypatch,
    tmp_path,
    capsys,
):
    calls = {}

    def fake_oos_runner(
        db_path,
        *,
        calendar,
        as_of,
    ):
        calls["db_path"] = db_path
        calls["calendar"] = calendar
        calls["as_of"] = as_of

        report = SimpleNamespace(
            as_of=date(2026, 8, 31),
            horizon_date_40=date(
                2026,
                10,
                26,
            ),
            available_through=date(
                2026,
                10,
                9,
            ),
            status=SimpleNamespace(
                value="IMMATURE"
            ),
            observation_count=157,
            score_available_count=156,
            outcome_available_count=0,
            data_incomplete_count=0,
            ic40=None,
            q5_minus_q1_relative_return_40=None,
            q5_mean_relative_return_40=None,
        )

        return SimpleNamespace(
            report=report
        )

    def forbidden_daily_pipeline(**kwargs):
        raise AssertionError(
            "vcp-oos must not enter daily pipeline"
        )

    monkeypatch.setattr(
        run,
        "run_frozen_vcp_oos",
        fake_oos_runner,
    )

    monkeypatch.setattr(
        run,
        "run_daily_pipeline",
        forbidden_daily_pipeline,
    )

    db_path = tmp_path / "research.db"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run.py",
            "vcp-oos",
            "--db",
            str(db_path),
            "--as-of",
            "2026-08-31",
        ],
    )

    result = run.main()

    assert result == 0

    assert calls["db_path"] == str(
        db_path
    )

    assert calls["as_of"] == date(
        2026,
        8,
        31,
    )

    output = capsys.readouterr().out

    assert (
        "OOS as_of=2026-08-31"
        in output
    )

    assert (
        "horizon_40=2026-10-26"
        in output
    )

    assert (
        "status=IMMATURE"
        in output
    )

    assert (
        "score_coverage=156/157"
        in output
    )

    assert (
        "outcome_coverage=0/157"
        in output
    )

    assert (
        "performance=BLOCKED"
        in output
    )

    assert "OOS-METRICS" not in output


def test_parse_args_accepts_vcp_oos_snapshot(
    monkeypatch,
):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run.py",
            "vcp-oos-snapshot",
            "--as-of",
            "2026-08-31",
        ],
    )

    args = run.parse_args()

    assert args.command == "vcp-oos-snapshot"
    assert args.as_of == "2026-08-31"


def test_main_vcp_oos_snapshot_requires_explicit_as_of(
    monkeypatch,
    capsys,
):
    def forbidden_runner(*args, **kwargs):
        raise AssertionError(
            "snapshot runner must not execute "
            "without explicit --as-of"
        )

    monkeypatch.setattr(
        run,
        "run_frozen_vcp_oos",
        forbidden_runner,
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run.py",
            "vcp-oos-snapshot",
        ],
    )

    result = run.main()

    assert result == 2

    output = capsys.readouterr().out

    assert (
        "FAILED vcp-oos-snapshot: "
        "--as-of is required"
        in output
    )


def test_main_runs_vcp_oos_snapshot_without_daily_pipeline(
    monkeypatch,
    tmp_path,
    capsys,
):
    calls = {}

    report = SimpleNamespace(
        as_of=date(2026, 8, 31),
        horizon_date_40=date(
            2026,
            10,
            26,
        ),
        available_through=date(
            2026,
            10,
            9,
        ),
        status=SimpleNamespace(
            value="IMMATURE"
        ),
        observation_count=2,
        score_available_count=2,
    )

    quality_observations = (
        object(),
        object(),
    )

    def fake_oos_runner(
        db_path,
        *,
        calendar,
        as_of,
    ):
        calls["db_path"] = db_path
        calls["as_of"] = as_of

        return SimpleNamespace(
            report=report,
            quality_observations=(
                quality_observations
            ),
        )

    def fake_build_snapshot(
        *,
        observations,
        report,
        vcp_state_config,
        git_commit,
    ):
        calls["observations"] = observations
        calls["report"] = report
        calls["git_commit"] = git_commit

        return {
            "as_of": "2026-08-31",
            "snapshot_sha256": "b" * 64,
        }

    def fake_write_snapshot(
        payload,
        output_dir,
    ):
        calls["payload"] = payload
        calls["output_dir"] = output_dir

        return (
            tmp_path
            / "2026-08-31.json"
        )

    def forbidden_daily_pipeline(**kwargs):
        raise AssertionError(
            "vcp-oos-snapshot must not "
            "enter daily pipeline"
        )

    monkeypatch.setattr(
        run,
        "run_frozen_vcp_oos",
        fake_oos_runner,
    )

    monkeypatch.setattr(
        run,
        "build_oos_snapshot_payload",
        fake_build_snapshot,
    )

    monkeypatch.setattr(
        run,
        "write_oos_snapshot",
        fake_write_snapshot,
    )

    monkeypatch.setattr(
        run,
        "_current_git_commit",
        lambda: "a" * 40,
    )

    monkeypatch.setattr(
        run,
        "run_daily_pipeline",
        forbidden_daily_pipeline,
    )

    db_path = tmp_path / "research.db"
    snapshot_dir = tmp_path / "snapshots"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run.py",
            "vcp-oos-snapshot",
            "--db",
            str(db_path),
            "--as-of",
            "2026-08-31",
            "--snapshot-dir",
            str(snapshot_dir),
        ],
    )

    result = run.main()

    assert result == 0
    assert calls["as_of"] == date(
        2026,
        8,
        31,
    )
    assert (
        calls["observations"]
        == quality_observations
    )
    assert calls["git_commit"] == "a" * 40
    assert calls["output_dir"] == str(
        snapshot_dir
    )

    output = capsys.readouterr().out

    assert "SNAPSHOT as_of=2026-08-31" in output
    assert "status=IMMATURE" in output
    assert "observations=2" in output
    assert "sha256=" in output
