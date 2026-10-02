import sys

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
    ):
        calls["conn"] = conn
        calls["provider"] = provider
        calls["as_of"] = as_of
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

    output = capsys.readouterr().out

    assert "SUCCESS adjustment-backfill" in output
    assert "inserted=3" in output
