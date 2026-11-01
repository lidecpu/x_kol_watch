import copy
import datetime as dt
import unittest
from unittest.mock import patch

import x_kol_daily as market


class StoredStateTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 11, 2, 12, 0, tzinfo=market.CN_TZ)
        self.state = {}
        for target, replacement in (
            ("cn_now", lambda: self.now),
            ("load_json", lambda *_: copy.deepcopy(self.state)),
            ("save_json", self._save),
        ):
            mocked = patch.object(market, target, replacement)
            mocked.start()
            self.addCleanup(mocked.stop)

    def _save(self, _, state):
        self.state = copy.deepcopy(state)


class MacroSourceStatusTests(StoredStateTests):
    fomc_page = "<h4>2026 FOMC Meetings</h4>\n<p>December 8-9</p>"

    def _event(self, release_at, captured_at=None, failed_at=None):
        event = {"release_at": release_at}
        if captured_at:
            event["captured_at"] = captured_at.isoformat(timespec="seconds")
        if failed_at:
            event["failed_at"] = failed_at.isoformat(timespec="seconds")
        return event

    def _bls(self):
        return {
            "非农": dt.datetime(2026, 11, 6, 21, 30, tzinfo=market.CN_TZ),
            "CPI": dt.datetime(2026, 11, 10, 21, 30, tzinfo=market.CN_TZ),
        }

    def test_bls_failure_does_not_cool_down_fomc(self):
        old = self.now - dt.timedelta(days=2)
        self.state = {"version": 2, "events": {
            "非农": {"failed_at": self.now.isoformat()},
            "CPI": {"failed_at": self.now.isoformat()},
            "美联储决议": self._event("2026-12-10T03:00:00+08:00", old),
        }}
        with patch.object(market, "fetch_bls_macro_calendar", side_effect=TimeoutError()) as bls, \
                patch.object(market, "fetch_us_macro_page", return_value=self.fomc_page):
            calendar = market.fetch_us_macro_calendar()
        bls.assert_not_called()
        self.assertEqual(
            self.state["events"]["美联储决议"]["captured_at"], "2026-11-02T12:00:00+08:00",
        )
        self.assertIn("美联储决议 12-10 03:00", "\n".join(market.us_macro_calendar_lines(calendar)))

    def test_fallback_dates_are_never_saved_as_verified_events(self):
        with patch.object(market, "fetch_bls_macro_calendar", side_effect=TimeoutError()), \
                patch.object(market, "fetch_us_macro_page", return_value=self.fomc_page):
            calendar = market.fetch_us_macro_calendar()
            repeated = market.fetch_us_macro_calendar()
        lines = "\n".join(market.us_macro_calendar_lines(calendar))
        self.assertIn("非农/失业率 11-06 21:30（备用，未核验）", lines)
        self.assertIn("CPI 11-10 21:30（备用，未核验）", lines)
        self.assertNotIn("captured_at", self.state.get("events", {}).get("非农", {}))
        repeated_lines = "\n".join(market.us_macro_calendar_lines(repeated))
        self.assertIn("美联储决议 12-10 03:00（缓存核验 11-02 12:00）", repeated_lines)

    def test_failed_source_retries_after_short_cooldown_without_refetching_fomc(self):
        with patch.object(market, "fetch_bls_macro_calendar", side_effect=TimeoutError()), \
                patch.object(market, "fetch_us_macro_page", return_value=self.fomc_page):
            market.fetch_us_macro_calendar()
        self.now += dt.timedelta(minutes=31)
        with patch.object(market, "fetch_bls_macro_calendar", return_value=self._bls()), \
                patch.object(market, "fetch_us_macro_page", side_effect=AssertionError("fresh FOMC refetched")):
            calendar = market.fetch_us_macro_calendar()
        lines = "\n".join(market.us_macro_calendar_lines(calendar))
        self.assertNotIn("备用", lines)
        self.assertNotIn("failed_at", self.state["events"]["非农"])
        self.assertEqual(self.state["events"]["美联储决议"]["captured_at"], "2026-11-02T12:00:00+08:00")

    def test_failure_preserves_original_per_event_verification_time(self):
        old = self.now - dt.timedelta(days=2)
        self.state = {"version": 2, "events": {
            "非农": self._event("2026-11-06T21:30:00+08:00", old),
            "CPI": self._event("2026-11-10T21:30:00+08:00", old),
        }}
        with patch.object(market, "fetch_bls_macro_calendar", side_effect=TimeoutError()), \
                patch.object(market, "fetch_us_macro_page", return_value=self.fomc_page):
            calendar = market.fetch_us_macro_calendar()
        lines = "\n".join(market.us_macro_calendar_lines(calendar))
        self.assertIn("非农/失业率 11-06 21:30（缓存核验 10-31 12:00，刷新失败）", lines)
        self.assertEqual(self.state["events"]["非农"]["captured_at"], "2026-10-31T12:00:00+08:00")

    def test_partial_bls_response_does_not_verify_missing_cpi(self):
        partial = {"非农": self._bls()["非农"]}
        with patch.object(market, "fetch_bls_macro_calendar", return_value=partial), \
                patch.object(market, "fetch_us_macro_page", return_value=self.fomc_page):
            calendar = market.fetch_us_macro_calendar()
        lines = "\n".join(market.us_macro_calendar_lines(calendar))
        self.assertIn("CPI 11-10 21:30（备用，未核验）", lines)
        self.assertEqual(self.state["events"]["非农"]["captured_at"], "2026-11-02T12:00:00+08:00")
        self.assertNotIn("captured_at", self.state["events"]["CPI"])

    def test_legacy_shared_failure_is_not_migrated_as_source_verification(self):
        self.state = {
            "version": 1,
            "snapshot": {"非农": "2026-11-06T21:30:00+08:00"},
            "captured_at": "2026-11-01T12:00:00+08:00",
            "failed_at": self.now.isoformat(),
        }
        with patch.object(market, "fetch_bls_macro_calendar", side_effect=TimeoutError()), \
                patch.object(market, "fetch_us_macro_page", return_value=self.fomc_page):
            calendar = market.fetch_us_macro_calendar()
        lines = "\n".join(market.us_macro_calendar_lines(calendar))
        self.assertIn("美联储决议 12-10 03:00", lines)
        self.assertIn("未核验", lines)
        self.assertNotIn("captured_at", self.state["events"]["非农"])

    def test_legacy_success_does_not_prove_each_fallback_date_was_verified(self):
        self.state = {
            "version": 1,
            "snapshot": {
                "非农": "2026-11-06T21:30:00+08:00",
                "CPI": "2026-11-10T21:30:00+08:00",
            },
            "captured_at": self.now.isoformat(),
        }
        with patch.object(market, "fetch_bls_macro_calendar", side_effect=TimeoutError()), \
                patch.object(market, "fetch_us_macro_page", return_value=self.fomc_page):
            calendar = market.fetch_us_macro_calendar()
        lines = "\n".join(market.us_macro_calendar_lines(calendar))
        self.assertIn("非农/失业率 11-06 21:30（旧缓存，未核验）", lines)
        self.assertNotIn("captured_at", self.state["events"]["非农"])

    def test_future_corrupted_capture_time_is_not_reported_as_verified(self):
        self.state = {"version": 2, "events": {
            "非农": self._event(
                "2026-11-06T21:30:00+08:00", self.now + dt.timedelta(days=1),
            ),
        }}
        with patch.object(market, "fetch_bls_macro_calendar", side_effect=TimeoutError()), \
                patch.object(market, "fetch_us_macro_page", return_value=self.fomc_page):
            calendar = market.fetch_us_macro_calendar()
        lines = "\n".join(market.us_macro_calendar_lines(calendar))
        self.assertIn("非农/失业率 11-06 21:30（旧缓存，未核验）", lines)
        self.assertNotIn("缓存核验 11-03", lines)

    def test_no_fallback_or_history_is_displayed_as_unavailable(self):
        self.now = dt.datetime(2027, 1, 2, 12, 0, tzinfo=market.CN_TZ)
        with patch.object(market, "fetch_bls_macro_calendar", side_effect=TimeoutError()), \
                patch.object(market, "fetch_us_macro_page", side_effect=TimeoutError()):
            calendar = market.fetch_us_macro_calendar()
        lines = "\n".join(market.us_macro_calendar_lines(calendar))
        self.assertIn("非农/失业率 暂不可用", lines)
        self.assertIn("CPI 暂不可用", lines)
        self.assertIn("美联储决议 暂不可用", lines)


class StakingFreshnessTests(StoredStateTests):
    metrics = {"total": 43948738.0, "percent": 35.0, "apr": 2.5}

    def _save_metrics(self, metrics=None):
        market.save_eth_staking_snapshot(self.now.date().isoformat(), metrics or self.metrics)

    def test_initial_observation_is_not_claimed_as_source_update_time(self):
        self._save_metrics()
        freshness = self.state.get("eth_staking_freshness", {})
        self.assertEqual(freshness.get("unchanged_since"), "2026-11-02T12:00:00+08:00")
        self.assertNotIn("last_changed_at", freshness)
        self.assertNotIn("source_updated_at", freshness)

    def test_unchanged_period_survives_snapshot_retention(self):
        self.state = {"unrelated": {"keep": True}}
        self._save_metrics()
        for _ in range(12):
            self.now += dt.timedelta(days=1)
            self._save_metrics()
        self.assertEqual(len(self.state["snapshots"]), 8)
        self.assertEqual(
            self.state.get("eth_staking_freshness", {}).get("unchanged_since"),
            "2026-11-02T12:00:00+08:00",
        )
        self.assertEqual(self.state["unrelated"], {"keep": True})

    def test_any_metric_change_resets_observed_unchanged_period(self):
        for key, value in (("total", 43949000.0), ("percent", 36.0), ("apr", 2.6)):
            with self.subTest(metric=key):
                self.state = {}
                self.now = dt.datetime(2026, 11, 2, 12, 0, tzinfo=market.CN_TZ)
                self._save_metrics()
                self.now += dt.timedelta(days=1)
                self._save_metrics(self.metrics | {key: value})
                freshness = self.state.get("eth_staking_freshness", {})
                self.assertEqual(freshness.get("unchanged_since"), "2026-11-03T12:00:00+08:00")
                self.assertEqual(freshness.get("last_changed_at"), "2026-11-03T12:00:00+08:00")

    def test_legacy_snapshots_seed_only_the_observed_unchanged_run(self):
        snapshots = {}
        for day in range(25, 32):
            snapshots[f"2026-10-{day}"] = {
                "eth_staking_total": 40000000.0 if day == 25 else 43948738.0,
                "eth_staking_percent": 35.0,
                "eth_staking_apr": 2.5,
                "captured_at": f"2026-10-{day}T12:00:00+08:00",
            }
        snapshots["2026-11-01"] = dict(snapshots["2026-10-31"], captured_at="2026-11-01T12:00:00+08:00")
        self.state = {"version": 1, "snapshots": snapshots}
        self._save_metrics()
        freshness = self.state.get("eth_staking_freshness", {})
        self.assertEqual(freshness.get("unchanged_since"), "2026-10-26T12:00:00+08:00")
        self.assertNotIn("last_changed_at", freshness)

    def test_invalid_or_future_tracking_time_cannot_manufacture_source_age(self):
        for value in ("bad", "2030-01-01T12:00:00+08:00"):
            with self.subTest(timestamp=value):
                self.state = {"eth_staking_freshness": self.metrics | {"unchanged_since": value}}
                self._save_metrics()
                self.assertEqual(
                    self.state["eth_staking_freshness"]["unchanged_since"],
                    "2026-11-02T12:00:00+08:00",
                )


if __name__ == "__main__":
    unittest.main()
