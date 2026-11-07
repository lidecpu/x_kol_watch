import copy
import datetime as dt
import http.client
import io
import json
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import x_kol_daily as market


class MarketReportingTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.now = dt.datetime(2026, 11, 8, 23, 45, tzinfo=market.CN_TZ)
        self.state = self.root / "market.json"
        self.calendar = self.root / "calendar.json"
        self.state.write_text(json.dumps({
            "version": 1,
            "snapshots": {
                "2026-11-07": {
                    "derivatives_volume": 2e11, "eth_staking_total": 44000000,
                },
                "2026-11-08": {
                    "derivatives_volume": 2.5e11, "eth_staking_total": 44010000,
                    "captured_at": "2026-11-08T23:30:00+08:00",
                },
            },
            "unrelated": {"keep": True},
        }), encoding="utf-8")
        self.calendar.write_text(json.dumps({
            "version": 2,
            "events": {
                "CPI": {
                    "release_at": "2026-11-10T21:30:00+08:00",
                    "captured_at": "2026-11-01T12:00:00+08:00",
                },
            },
        }), encoding="utf-8")
        self.coinglass = {
            "current_price": 80000,
            "long_levels": [
                {"price": 79000, "intensity": 200, "distance_percent": -1.25},
            ],
            "short_levels": [
                {"price": 81000, "intensity": 100, "distance_percent": 1.25},
            ],
            "long_short_ratio": {"long_users": 100, "short_users": 50, "ratio": 2},
            "market_structure": {
                "btc_dominance": 60, "btc_dominance_change_24h": 0.2,
                "exchange_balance": 2580736,
                "exchange_balance_change_24h": 0,
                "exchange_balance_change_7d": -18000,
                "exchange_balance_change_30d": -24000,
            },
            "_captured_at": self.now.isoformat(),
        }
        self.sources = {
            "fetch_global_volume": {
                "current": 1.2e11, "delta": 2e10, "percent": 20,
                "volume_valid": True, "market_cap": 2.7e12, "market_cap_percent": -2,
                "btc_dominance": 60, "eth_dominance": 11,
            },
            "fetch_dex_volume": {"current": 1e10, "delta": 2e9, "percent": 25},
            "fetch_derivatives_volume": 3e11,
            "fetch_eth_staking_metrics": {"total": 44020000, "percent": 35, "apr": 2.5},
            "fetch_chain_activity": {
                "record_date": dt.date(2026, 11, 6),
                "assets": {
                    symbol: {
                        "transactions": 1000000, "percent": 1,
                        "seven_day_average_percent": 2,
                    } for symbol in ("btc", "eth")
                },
            },
            "fetch_stablecoin_supply": {
                symbol: {"current": 1e10, "delta": 1e8} for symbol in ("USDT", "USDC")
            },
            "fetch_stablecoin_volumes": {
                symbol: {"current": 1e10, "delta": 1e8, "percent": 1}
                for symbol in ("USDT", "USDC")
            },
            "fetch_strategy_btc": {
                "record_date": dt.date(2026, 11, 1),
                "holdings_as_of": dt.date(2026, 11, 1),
                "verified_date": dt.date(2026, 11, 8),
                "holdings": 849327, "change": 811, "average_price": 75451,
                "total_cost_millions": 64080, "verification_source": "SEC",
                "filing_date": dt.date(2026, 11, 2),
            },
            "fetch_bitmine_eth": {
                "record_date": dt.date(2026, 11, 2),
                "holdings": 6060500, "change": 8600, "supply_percent": 4.9,
                "staked": 5227000,
            },
            "fetch_us_treasury_debt": {
                "record_date": dt.date(2026, 11, 5), "current": 4e13, "delta": 1e9,
            },
            "fetch_us_treasury_yields": {
                "record_date": dt.date(2026, 11, 6),
                "2y": 4.51, "5y": 4.64, "10y": 4.86, "30y": 5.26,
            },
            "fetch_coinglass_snapshot": self.coinglass,
            "fetch_spot_etf_flow_snapshot": {
                symbol: {"records": [
                    {"record_date": day, "flow_millions": 100}
                    for day in (
                        "2026-11-06", "2026-11-05", "2026-11-04",
                        "2026-11-03", "2026-11-02",
                    )
                ]} for symbol in ("BTC", "ETH")
            },
        }

    def run_market(self, arguments=None, **overrides):
        stdout, stderr = io.StringIO(), io.StringIO()
        sources = self.sources | overrides
        with ExitStack() as stack:
            stack.enter_context(patch.object(market, "cn_now", return_value=self.now))
            stack.enter_context(patch.object(market, "MARKET_STATE", self.state))
            stack.enter_context(patch.object(market, "US_MACRO_STATE", self.calendar))
            for name, value in sources.items():
                options = {"side_effect": value} if isinstance(value, Exception) else {"return_value": value}
                stack.enter_context(patch.object(market, name, **options))
            stack.enter_context(patch.object(market, "fetch_bls_macro_calendar", return_value={
                "CPI": dt.datetime(2026, 11, 10, 21, 30, tzinfo=market.CN_TZ),
                "非农": dt.datetime(2026, 12, 4, 21, 30, tzinfo=market.CN_TZ),
            }))
            stack.enter_context(patch.object(
                market, "fetch_us_macro_page",
                return_value="<h4>2026 FOMC Meetings</h4>\n<p>December 8-9</p>",
            ))
            stack.enter_context(redirect_stdout(stdout))
            stack.enter_context(redirect_stderr(stderr))
            if arguments is None:
                summary = market.fetch_stablecoin_summary()
            else:
                stack.enter_context(patch.object(market, "load_dotenv"))
                stack.enter_context(patch.object(market.sys, "argv", ["market", *arguments]))
                summary = market.main()
        return summary, stdout.getvalue(), stderr.getvalue()

    def status(self, stderr):
        statuses = [
            json.loads(line)["market"]
            for line in stderr.splitlines() if line.startswith('{"market":')
        ]
        self.assertEqual(len(statuses), 1, stderr)
        return statuses[0]

    def test_complete_report_has_explicit_complete_status(self):
        summary, _, stderr = self.run_market()
        status = self.status(stderr)
        self.assertEqual(status["status"], "complete")
        self.assertEqual(status["missing"], [])
        self.assertIn("现价 $80,000", summary)
        self.assertNotIn("数据提示", summary)

    def test_partial_report_warns_for_each_missing_metric_without_hiding_good_data(self):
        snapshot = copy.deepcopy(self.coinglass)
        snapshot.pop("long_short_ratio")
        volumes = {"USDT": self.sources["fetch_stablecoin_volumes"]["USDT"]}
        with patch.dict(market.os.environ, {"GITHUB_ACTIONS": "true"}):
            summary, _, stderr = self.run_market(
                fetch_coinglass_snapshot=snapshot, fetch_stablecoin_volumes=volumes,
            )
        status = self.status(stderr)
        self.assertEqual(status["status"], "partial")
        self.assertEqual(set(status["missing"]), {"持仓人数多空比", "USDC现货成交"})
        self.assertIn("现价 $80,000", summary)
        self.assertIn("数据提示", summary)
        self.assertIn("USDC现货成交", summary)
        self.assertIn("::warning title=市场数据缺项::", stderr)

    def test_no_market_data_returns_failure_even_when_calendar_is_available(self):
        failed = {name: TimeoutError("source unavailable") for name in self.sources}
        summary, _, stderr = self.run_market(**failed)
        self.assertEqual(summary, "")
        self.assertEqual(self.status(stderr)["status"], "failed")

    def test_missing_market_cap_change_cannot_be_reported_as_complete(self):
        global_volume = self.sources["fetch_global_volume"] | {"market_cap_percent": None}
        summary, _, stderr = self.run_market(fetch_global_volume=global_volume)
        self.assertEqual(self.status(stderr)["status"], "partial")
        self.assertIn("总市值24H变化", self.status(stderr)["missing"])
        self.assertIn("24H 暂不可用", summary)

    def test_interrupted_http_response_keeps_other_market_data(self):
        summary, _, stderr = self.run_market(
            fetch_derivatives_volume=http.client.IncompleteRead(b"partial"),
        )
        self.assertIn("现价 $80,000", summary)
        self.assertEqual(self.status(stderr)["status"], "partial")
        self.assertIn("全网合约成交", self.status(stderr)["missing"])

    def test_debt_failure_does_not_hide_live_yields(self):
        summary, _, stderr = self.run_market(fetch_us_treasury_debt=TimeoutError())
        self.assertIn("收益率（截至 11-06）", summary)
        self.assertIn("10年 4.86%", summary)
        self.assertEqual(self.status(stderr)["missing"], ["美国国债总额"])

    def test_preview_does_not_modify_official_baselines_or_calendar(self):
        for arguments in (
            ["--market-only", "--no-send", "--telegram-preview"],
            ["--market-only", "--send", "--no-send"],
            ["--cache-recent", "1", "--no-send", "--telegram-preview"],
        ):
            with self.subTest(arguments=arguments), patch.object(
                market, "cached_results", return_value=[],
            ):
                before = (self.state.read_bytes(), self.calendar.read_bytes())
                result, stdout, stderr = self.run_market(arguments)
                self.assertEqual(result, 0)
                self.assertIn("质押量 4402.00万枚", stdout)
                self.assertIn("本次观测 11-08 23:45", stdout)
                self.assertEqual((self.state.read_bytes(), self.calendar.read_bytes()), before)
                self.assertEqual(self.status(stderr)["status"], "complete")

    def test_formal_send_preserves_daily_snapshot_updates(self):
        with patch.object(market, "telegram_send_reports_once", return_value={"groups": 1, "rows": 0}):
            result, _, _ = self.run_market(["--market-only", "--send"])
        self.assertEqual(result, 0)
        state = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(state["snapshots"]["2026-11-08"]["derivatives_volume"], 3e11)
        self.assertEqual(state["snapshots"]["2026-11-08"]["eth_staking_total"], 44020000)
        self.assertEqual(state["unrelated"], {"keep": True})


if __name__ == "__main__":
    unittest.main()
