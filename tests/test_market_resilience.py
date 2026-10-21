import copy
import datetime as dt
import unittest
from unittest.mock import patch

import x_kol_daily as market


class EtfCacheIsolationTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 10, 21, 23, 30, tzinfo=market.CN_TZ)
        self.old = self.now - dt.timedelta(days=1)
        self.state = {"version": 1, "snapshots": {}, "unrelated": {"keep": True}}
        self.saved = []
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
        self.saved.append(copy.deepcopy(state))

    def _asset(self, date="2026-10-20", captured_at=None):
        latest = dt.date.fromisoformat(date)
        asset = {
            "records": [
                {
                    "record_date": (latest - dt.timedelta(days=index)).isoformat(),
                    "flow_millions": 100 + index,
                }
                for index in range(market.SPOT_ETF_FLOW_SUMMARY_DAYS)
            ],
        }
        if captured_at is not None:
            asset["_captured_at"] = captured_at.isoformat(timespec="seconds")
        return asset

    def _cache(self, btc=None, eth=None, captured_at=None, failed_at=None):
        snapshot = {}
        if btc is not None:
            snapshot["BTC"] = btc
        if eth is not None:
            snapshot["ETH"] = eth
        cache = {"version": market.SPOT_ETF_FLOW_CACHE_VERSION, "snapshot": snapshot}
        if captured_at is not None:
            cache["captured_at"] = captured_at.isoformat(timespec="seconds")
        if failed_at is not None:
            cache["failed_at"] = failed_at.isoformat(timespec="seconds")
        self.state["spot_etf_flows"] = cache

    def _fetch_with_failure(self, failed):
        def fetch(url):
            if (failed == "BTC") == (url == market.FARSIDE_BITCOIN_ETF_FLOW_URL):
                raise TimeoutError("source unavailable")
            return self._asset()
        return fetch

    def test_either_asset_can_update_when_the_other_fails(self):
        for failed in ("BTC", "ETH"):
            with self.subTest(failed=failed):
                self._cache(
                    self._asset("2026-10-19"), self._asset("2026-10-19"),
                    captured_at=self.old,
                )
                with patch.object(
                    market, "fetch_farside_etf_flow", side_effect=self._fetch_with_failure(failed),
                ) as fetch:
                    snapshot = market.fetch_spot_etf_flow_snapshot()
                    repeated = market.fetch_spot_etf_flow_snapshot()
                fresh = "ETH" if failed == "BTC" else "BTC"
                self.assertEqual(fetch.call_count, 2)
                self.assertEqual(snapshot[fresh]["records"][0]["record_date"], "2026-10-20")
                self.assertNotIn("_stale", snapshot[fresh])
                self.assertEqual(snapshot[failed]["records"][0]["record_date"], "2026-10-19")
                self.assertTrue(snapshot[failed]["_stale"])
                self.assertEqual(
                    snapshot[failed]["_captured_at"], self.old.isoformat(timespec="seconds"),
                )
                self.assertEqual(snapshot, repeated)
                lines = market.spot_etf_summary_lines(snapshot)
                self.assertIn("缓存 10-20 23:30", next(line for line in lines if line.startswith(failed)))
                self.assertNotIn("缓存", next(line for line in lines if line.startswith(fresh)))
                self.assertEqual(self.state["unrelated"], {"keep": True})

    def test_missing_history_does_not_hide_the_successful_asset(self):
        for failed in ("BTC", "ETH"):
            with self.subTest(failed=failed):
                self._cache()
                with patch.object(
                    market, "fetch_farside_etf_flow", side_effect=self._fetch_with_failure(failed),
                ):
                    snapshot = market.fetch_spot_etf_flow_snapshot()
                fresh = "ETH" if failed == "BTC" else "BTC"
                lines = market.spot_etf_summary_lines(snapshot)
                self.assertIn(f"{failed} 暂不可用", lines)
                self.assertIn(f"{failed} 暂不可用", lines[-1])
                self.assertTrue(any(line.startswith(f"{fresh} 10-20 +1.00") for line in lines))
                self.assertNotIn("_captured_at", snapshot[failed])

    def test_both_fail_keep_their_own_cache_dates(self):
        earlier = self.old - dt.timedelta(hours=3)
        self._cache(
            self._asset(captured_at=earlier), self._asset(captured_at=self.old),
            captured_at=self.old,
        )
        with patch.object(market, "fetch_farside_etf_flow", side_effect=TimeoutError()):
            snapshot = market.fetch_spot_etf_flow_snapshot()
        lines = market.spot_etf_summary_lines(snapshot)
        self.assertIn("缓存 10-20 20:30", lines[1])
        self.assertIn("缓存 10-20 23:30", lines[2])
        self.assertEqual(
            self.state["spot_etf_flows"]["captured_at"], self.old.isoformat(timespec="seconds"),
        )

    def test_only_the_expired_asset_refreshes_and_clears_failure(self):
        fresh_at = self.now - dt.timedelta(minutes=1)
        expired = self._asset("2026-10-19", captured_at=self.old)
        expired["_failed_at"] = self.old.isoformat(timespec="seconds")
        expired["_stale"] = True
        self._cache(self._asset(captured_at=fresh_at), expired, captured_at=fresh_at)
        with patch.object(market, "fetch_farside_etf_flow", return_value=self._asset()) as fetch:
            snapshot = market.fetch_spot_etf_flow_snapshot()
        fetch.assert_called_once_with(market.FARSIDE_ETHEREUM_ETF_FLOW_URL)
        self.assertEqual(snapshot["BTC"]["_captured_at"], fresh_at.isoformat(timespec="seconds"))
        self.assertNotIn("_failed_at", snapshot["ETH"])
        self.assertNotIn("_stale", snapshot["ETH"])

    def test_fresh_legacy_shared_cache_is_reused_without_writes(self):
        fresh_at = self.now - dt.timedelta(minutes=1)
        self._cache(self._asset(), self._asset(), captured_at=fresh_at)
        with patch.object(market, "fetch_farside_etf_flow") as fetch:
            snapshot = market.fetch_spot_etf_flow_snapshot()
        fetch.assert_not_called()
        self.assertEqual(self.saved, [])
        self.assertEqual(snapshot["BTC"]["_captured_at"], fresh_at.isoformat(timespec="seconds"))
        self.assertEqual(snapshot["ETH"]["_captured_at"], fresh_at.isoformat(timespec="seconds"))
        self.assertFalse(any("缓存" in line for line in market.spot_etf_summary_lines(snapshot)))

    def test_legacy_shared_failure_cooldown_is_respected(self):
        self._cache(
            self._asset(), self._asset(), captured_at=self.old,
            failed_at=self.now - dt.timedelta(minutes=1),
        )
        with patch.object(market, "fetch_farside_etf_flow") as fetch:
            snapshot = market.fetch_spot_etf_flow_snapshot()
        fetch.assert_not_called()
        self.assertTrue(snapshot["BTC"]["_stale"])
        self.assertTrue(snapshot["ETH"]["_stale"])

    def test_empty_history_retries_after_its_own_cooldown(self):
        fresh = self._asset(captured_at=self.now)
        failed = {"_failed_at": self.old.isoformat(timespec="seconds")}
        self._cache(failed, fresh, captured_at=self.now)
        with patch.object(market, "fetch_farside_etf_flow", return_value=self._asset()) as fetch:
            snapshot = market.fetch_spot_etf_flow_snapshot()
        fetch.assert_called_once_with(market.FARSIDE_BITCOIN_ETF_FLOW_URL)
        self.assertEqual(snapshot["BTC"]["records"][0]["record_date"], "2026-10-20")
        self.assertNotIn("_failed_at", snapshot["BTC"])

    def test_invalid_new_data_does_not_replace_good_history(self):
        invalid_assets = [
            {"records": []},
            self._asset() | {"records": [{"record_date": "bad", "flow_millions": 1}] * 5},
            self._asset() | {"records": [{"record_date": "2026-10-20", "flow_millions": float("nan")}] * 5},
        ]
        for invalid in invalid_assets:
            with self.subTest(invalid=invalid):
                self._cache(
                    self._asset("2026-10-19"), self._asset("2026-10-19"),
                    captured_at=self.old,
                )
                with patch.object(
                    market, "fetch_farside_etf_flow", side_effect=[invalid, self._asset()],
                ):
                    snapshot = market.fetch_spot_etf_flow_snapshot()
                self.assertTrue(snapshot["BTC"]["_stale"])
                self.assertEqual(snapshot["BTC"]["records"][0]["record_date"], "2026-10-19")
                self.assertEqual(snapshot["ETH"]["records"][0]["record_date"], "2026-10-20")

    def test_both_fail_without_history_do_not_create_zero_flows(self):
        self._cache()
        with patch.object(market, "fetch_farside_etf_flow", side_effect=TimeoutError()) as fetch:
            snapshot = market.fetch_spot_etf_flow_snapshot()
            market.fetch_spot_etf_flow_snapshot()
        self.assertEqual(fetch.call_count, 2)
        lines = market.spot_etf_summary_lines(snapshot)
        self.assertIn("BTC 暂不可用", lines)
        self.assertIn("ETH 暂不可用", lines)
        self.assertFalse(any("0.00" in line for line in lines))
        self.assertNotIn("captured_at", self.state["spot_etf_flows"])

    def test_summary_cache_refresh_preserves_other_modules_and_partial_status(self):
        stale = self._asset("2026-10-19", captured_at=self.old)
        stale["_stale"] = True
        fresh = self._asset(captured_at=self.now)
        self._cache(fresh, stale, captured_at=self.now)
        summary = "\n".join([
            "加密市场", "总市值 unchanged", market.TELEGRAM_SECTION_SEPARATOR,
            "现货ETF资金流（亿美元）", "BTC old", "ETH old",
            market.TELEGRAM_SECTION_SEPARATOR, "Strategy（微策略）", "BTC持仓 unchanged",
        ])
        updated = market.refresh_cached_summary_etf(summary, self.old)
        self.assertIn("BTC 10-20 +1.00", updated)
        self.assertIn("ETH 10-19 +1.00", updated)
        self.assertIn("缓存 10-20 23:30", updated)
        self.assertIn("BTC持仓 unchanged", updated)
        self.assertNotIn("BTC old", updated)
        self.assertEqual(updated.count("现货ETF资金流"), 1)


if __name__ == "__main__":
    unittest.main()
