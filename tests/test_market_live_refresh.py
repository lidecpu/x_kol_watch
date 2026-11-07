import datetime as dt
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import x_kol_daily as market


def etf_asset():
    return {"records": [
        {"record_date": day, "flow_millions": flow}
        for day, flow in (
            ("2026-11-06", -411.9), ("2026-11-05", -430.2),
            ("2026-11-04", 74.6), ("2026-11-03", -115.6),
            ("2026-11-02", -398.6),
        )
    ]}


class LiveEtfTests(unittest.TestCase):
    def test_every_call_refreshes_both_assets_even_with_recent_cache(self):
        now = dt.datetime(2026, 11, 8, 3, 50, tzinfo=market.CN_TZ)
        with (
            patch.object(market, "cn_now", return_value=now),
            patch.object(market, "load_spot_etf_flow_cache",
                         return_value=({"BTC": etf_asset(), "ETH": etf_asset()}, now, now)),
            patch.object(market, "fetch_farside_etf_flow", side_effect=[
                etf_asset(), etf_asset(), etf_asset(), etf_asset(),
            ]) as fetch,
            patch.object(market, "save_json"),
        ):
            first = market.fetch_spot_etf_flow_snapshot()
            second = market.fetch_spot_etf_flow_snapshot()
        self.assertEqual(fetch.call_count, 4)
        self.assertEqual(first["BTC"]["records"][0]["flow_millions"], -411.9)
        self.assertEqual(second["ETH"]["records"][0]["record_date"], "2026-11-06")

    def test_failed_asset_is_unavailable_without_reusing_old_flows(self):
        now = dt.datetime(2026, 11, 8, 3, 50, tzinfo=market.CN_TZ)
        with (
            patch.object(market, "load_spot_etf_flow_cache",
                         return_value=({"BTC": etf_asset()}, now, None)),
            patch.object(market, "fetch_farside_etf_flow",
                         side_effect=[TimeoutError(), etf_asset()]),
            patch.object(market, "save_json"),
        ):
            snapshot = market.fetch_spot_etf_flow_snapshot()
        self.assertNotIn("records", snapshot.get("BTC", {}))
        lines = market.spot_etf_summary_lines(snapshot)
        self.assertIn("BTC 暂不可用", lines)
        self.assertIn("ETH 11-06 -4.12", lines[2])
        self.assertFalse(any("缓存" in line for line in lines))

    def test_invalid_source_records_do_not_become_zero_or_cached_flows(self):
        for records in (
            [],
            [{"record_date": "bad", "flow_millions": 1}] * 5,
            [{"record_date": "2026-11-06", "flow_millions": float("nan")}] * 5,
        ):
            with (
                self.subTest(records=records),
                patch.object(market, "fetch_farside_etf_flow",
                             side_effect=[{"records": records}, etf_asset()]),
            ):
                snapshot = market.fetch_spot_etf_flow_snapshot()
            self.assertEqual(snapshot["BTC"], {})
            self.assertEqual(snapshot["ETH"]["records"][0]["flow_millions"], -411.9)

    def test_failures_retry_next_call_without_cooldown(self):
        with patch.object(market, "fetch_farside_etf_flow", side_effect=[
            TimeoutError(), TimeoutError(), etf_asset(), etf_asset(),
        ]) as fetch:
            first = market.fetch_spot_etf_flow_snapshot()
            second = market.fetch_spot_etf_flow_snapshot()
        self.assertEqual(first, {"BTC": {}, "ETH": {}})
        self.assertEqual(fetch.call_count, 4)
        self.assertEqual(second["BTC"]["records"][0]["flow_millions"], -411.9)


class MarketPreviewTests(unittest.TestCase):
    def test_cloud_preview_prints_report_without_sending_or_scanning(self):
        with (
            patch.object(market.sys, "argv", [
                "x_kol_daily.py", "--market-only", "--no-send", "--telegram-preview",
            ]),
            patch.object(market, "load_dotenv"),
            patch.object(market, "fetch_stablecoin_summary",
                         return_value="加密市场\n总市值 2.50万亿美元"),
            patch.object(market, "telegram_send_reports_once") as send,
            patch.object(market, "cookies_from_env") as cookies,
            redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(market.main(), 0)
        self.assertIn("市场全景 24H", output.getvalue())
        self.assertIn("总市值 2.50万亿美元", output.getvalue())
        send.assert_not_called()
        cookies.assert_not_called()


if __name__ == "__main__":
    unittest.main()
