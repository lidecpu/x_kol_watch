import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import x_kol_daily as market


class LiveMarketSourceTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 11, 7, 0, 10, tzinfo=market.CN_TZ)
        self.cache = {
            "current_price": 70000.0,
            "long_levels": [{"price": 69000.0, "intensity": 100.0}],
            "short_levels": [{"price": 71000.0, "intensity": 100.0}],
            "long_short_ratio": {
                "long_users": 100,
                "short_users": 50,
                "ratio": 2.0,
            },
            "market_structure": {
                "btc_dominance": 60.0,
                "btc_dominance_change_24h": 0.1,
                "exchange_balance": 2500000.0,
                "exchange_balance_change_24h": -100.0,
                "exchange_balance_change_7d": -1000.0,
                "exchange_balance_change_30d": -2000.0,
            },
        }
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        state = Path(directory.name) / "market.json"
        state.write_text(json.dumps({
            "coinglass": {
                "version": 4, "snapshot": self.cache,
                "captured_at": (self.now - dt.timedelta(days=2)).isoformat(),
            },
        }), encoding="utf-8")
        patched = patch.object(market, "MARKET_STATE", state)
        patched.start()
        self.addCleanup(patched.stop)

    def test_failed_live_coinglass_does_not_return_old_snapshot(self):
        with (
            patch.object(market, "cn_now", return_value=self.now),
            patch.object(
                market,
                "fetch_coinglass_live",
                side_effect=ValueError("ratio unavailable"),
            ),
        ):
            snapshot = market.fetch_coinglass_snapshot()
        self.assertEqual(snapshot, {})

    def test_partial_live_coinglass_does_not_fill_missing_fields_from_cache(self):
        live = {
            "current_price": 80000.0,
            "long_levels": [{"price": 79000.0, "intensity": 200.0}],
            "short_levels": [{"price": 81000.0, "intensity": 200.0}],
            "_captured_at": self.now.isoformat(timespec="seconds"),
        }
        with (
            patch.object(market, "cn_now", return_value=self.now),
            patch.object(market, "fetch_coinglass_live", return_value=live),
        ):
            snapshot = market.fetch_coinglass_snapshot()
        self.assertEqual(snapshot["current_price"], 80000.0)
        self.assertNotIn("long_short_ratio", snapshot)
        self.assertNotIn("market_structure", snapshot)


class NoSummaryCacheFallbackTests(unittest.TestCase):
    def test_partial_live_market_report_does_not_merge_old_summary(self):
        old = "\n".join(["加密市场", "总市值 1.00万亿美元", market.TELEGRAM_SECTION_SEPARATOR])
        current = {
            **market.global_spot_volume_record(2.0e11, 10.0, 2.5e12),
            "market_cap": 2.5e12,
            "market_cap_percent": 1.0,
            "btc_dominance": 60.0,
            "eth_dominance": 10.0,
        }
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        state = Path(directory.name) / "market.json"
        state.write_text(json.dumps({
            "summary_cache": {
                "version": 23, "summary": old,
                "captured_at": dt.datetime.now(market.CN_TZ).isoformat(),
            },
        }), encoding="utf-8")
        with (
            patch.object(market, "MARKET_STATE", state),
            patch.object(market, "previous_derivatives_volume", return_value=None),
            patch.object(market, "previous_eth_staking_total", return_value=None),
            patch.object(market, "fetch_dex_volume", return_value={}),
            patch.object(market, "fetch_global_volume", return_value=current),
            patch.object(market, "fetch_chain_activity", return_value={}),
            patch.object(market, "fetch_derivatives_volume", side_effect=TimeoutError()),
            patch.object(market, "fetch_eth_staking_metrics", return_value={}),
            patch.object(market, "fetch_us_treasury_debt", return_value={}),
            patch.object(market, "fetch_us_treasury_yields", return_value={}),
            patch.object(market, "fetch_stablecoin_supply", return_value={}),
            patch.object(market, "fetch_stablecoin_volumes", return_value={}),
            patch.object(market, "fetch_strategy_btc", return_value={}),
            patch.object(market, "load_strategy_btc_cache", return_value={}),
            patch.object(market, "fetch_us_macro_calendar", return_value={}),
            patch.object(market, "fetch_bitmine_eth", return_value={}),
            patch.object(market, "fetch_coinglass_snapshot", return_value={}),
            patch.object(market, "fetch_spot_etf_flow_snapshot", return_value={}),
            patch.object(market, "save_eth_staking_snapshot", return_value={}),
            patch.object(market, "save_json"),
        ):
            summary = market.fetch_stablecoin_summary()
        self.assertIn("总市值 2.50万亿美元", summary)
        self.assertNotIn("总市值 1.00万亿美元", summary)


if __name__ == "__main__":
    unittest.main()
