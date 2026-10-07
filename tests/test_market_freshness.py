import datetime as dt
import io
import json
import unittest
import urllib.error
from unittest.mock import patch

import x_kol_daily as market


def table(*rows):
    return "<table>" + "".join(
        "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
        for row in rows
    ) + "</table>"


def split_tables(date="October 4, 2026*", change="334", holdings="900,000"):
    return (
        table(
            [f"During Period October 1, 2026 to {date}"],
            ["BTC Acquired (1)", "Aggregate Purchase Price (in millions) (2)", "Average Purchase Price (2)"],
            [change, "$28.7", "$85,838.8"],
        )
        + table(
            [f"As of {date}"],
            ["Aggregate BTC Holdings", "Aggregate Purchase Price (in billions) (2)", "Average Purchase Price (2)"],
            [holdings, "$67.97", "$75,440.7"],
        )
        + "<p>*Bitcoin activity and holdings information is presented as of "
        "4:00 p.m. Eastern Time on the last day indicated.</p>"
    )


class StrategyParsingTests(unittest.TestCase):
    def test_split_tables_choose_latest_with_beijing_cutoff(self):
        page = split_tables("September 30, 2026", "-") + split_tables()
        record = market.parse_strategy_btc_sec(page)
        self.assertEqual(record["holdings"], 900000)
        self.assertEqual(record["change"], 334)
        self.assertEqual(record["average_price"], 75440.7)
        self.assertEqual(record["total_cost_millions"], 67970)
        self.assertEqual(record["holdings_as_of"], dt.date(2026, 10, 5))
        self.assertEqual(record["holdings_as_of_time"], "04:00")

    def test_combined_table_with_separate_dollar_cells(self):
        page = table(
            ["During Period September 21, 2026 to September 27, 2026", "", "As of September 27, 2026"],
            ["BTC Purchased (1)", "AggregatePurchase Price (in millions) (2)", "Average Purchase Price (2)",
             "Aggregate BTC Holdings", "Aggregate Purchase Price (in billions) (2)", "Average Purchase Price (2)"],
            ["", "1,665", "$", "142.7", "$", "85,681", "", "899,666", "$", "67.95", "$", "75,437"],
        )
        record = market.parse_strategy_btc_sec(page)
        self.assertEqual(record["holdings"], 899666)
        self.assertEqual(record["change"], 1665)
        self.assertEqual(record["total_cost_millions"], 67950)
        self.assertEqual(record["holdings_as_of"], dt.date(2026, 9, 27))

    def test_no_purchases_are_zero(self):
        self.assertEqual(market.parse_strategy_btc_sec(split_tables(change="-"))["change"], 0)

    def test_winter_cutoff_uses_beijing_0500(self):
        record = market.parse_strategy_btc_sec(split_tables("December 6, 2026*"))
        self.assertEqual(record["holdings_as_of"], dt.date(2026, 12, 7))
        self.assertEqual(record["holdings_as_of_time"], "05:00")

    def test_missing_and_invalid_values_fail_closed(self):
        pages = (
            "<p>Only a stock offering was disclosed.</p>",
            split_tables(holdings="-"),
            split_tables().replace("$67.97", "$nan"),
            split_tables().replace("in billions", "in unknown units"),
            split_tables().replace("BTC Acquired (1)", "Unrelated Amount"),
        )
        for page in pages:
            with self.subTest(page=page[:60]), self.assertRaises(ValueError):
                market.parse_strategy_btc_sec(page)

    def test_prose_format(self):
        page = (
            "<p>Strategy acquired 334 bitcoin. As of October 4, 2026, Strategy "
            "holds approximately 900,000 bitcoin with an aggregate purchase price "
            "of $67.97 billion and an average purchase price of approximately "
            "$75,440.7 per bitcoin.</p>"
        )
        self.assertEqual(market.parse_strategy_btc_sec(page)["change"], 334)

    def test_unrelated_latest_filing_is_skipped_without_cache_delta(self):
        filings = {"filings": {"recent": {
            "form": ["8-K", "8-K"],
            "filingDate": ["2026-10-06", "2026-10-05"],
            "accessionNumber": ["new", "holdings"],
            "primaryDocument": ["stock.htm", "btc.htm"],
        }}}
        with patch.object(market.urllib.request, "urlopen", side_effect=[
            io.BytesIO(json.dumps(filings).encode()),
            io.BytesIO(b"<p>Stock offering only.</p>"),
            io.BytesIO(split_tables().encode()),
        ]), patch.object(market, "load_strategy_btc_cache", return_value={
            "holdings": 800000,
        }):
            record = market.fetch_strategy_btc_sec()
        self.assertEqual(record["holdings"], 900000)
        self.assertEqual(record["change"], 334)
        self.assertEqual(record["verification_source"], "SEC")

    def test_website_403_uses_sec(self):
        error = urllib.error.HTTPError(market.STRATEGY_PURCHASES_URL, 403, "Forbidden", {}, None)
        with patch.object(market.urllib.request, "urlopen", side_effect=error), \
                patch.object(market, "fetch_strategy_btc_sec", return_value={"holdings": 900000}) as sec:
            self.assertEqual(market.fetch_strategy_btc()["holdings"], 900000)
        sec.assert_called_once()

    def test_cache_preserves_verification_and_cutoff(self):
        record = market.parse_strategy_btc_sec(split_tables())
        record.update(verified_date=dt.date(2026, 10, 7), verification_source="SEC")
        with patch.object(market, "load_json", return_value={}), \
                patch.object(market, "save_json") as save:
            market.save_strategy_btc_cache(record)
        saved = save.call_args.args[1]
        with patch.object(market, "load_json", return_value=saved):
            restored = market.load_strategy_btc_cache()
        self.assertEqual(restored["holdings_as_of_time"], "04:00")
        self.assertEqual(restored["verification_source"], "SEC")
        self.assertEqual(restored["change"], 334)

    def test_cached_holdings_label_preserves_cutoff_without_timezone(self):
        old = "BTC持仓 900,000枚 | 持仓截至 10-05 04:00（北京时间） | SEC核验 10-07"
        expected = "BTC持仓 900,000枚 | 持仓截至 10-05 04:00 | SEC核验 10-07"
        self.assertEqual(market.normalize_stablecoin_summary_labels(old), expected)
        self.assertEqual(market.normalize_stablecoin_summary_labels(expected), expected)


class ChainDateTests(unittest.TestCase):
    def test_exact_beijing_interval(self):
        self.assertEqual(
            market.chain_activity_heading(dt.date(2026, 10, 5)),
            "链上确认交易（10-05 08:00 至 10-06 08:00）",
        )
        self.assertIn(
            "12-31 08:00 至 01-01 08:00",
            market.chain_activity_heading(dt.date(2026, 12, 31)),
        )

    def test_old_cached_labels_normalize_and_merge_once(self):
        new = market.chain_activity_heading(dt.date(2026, 10, 5))
        old = "链上确认交易（最新完整日 10-06）"
        for cached in (
            old,
            "链上确认交易（最新完整日 UTC 10-05｜北京时间 10-06）",
            "链上确认交易（最新完整区间，北京时间 10-05 08:00 至 10-06 08:00）",
            new,
        ):
            with self.subTest(cached=cached):
                self.assertEqual(market.normalize_stablecoin_summary_labels(cached), new)
                self.assertEqual(market.summary_block_key([cached]), market.summary_block_key([new]))
                merged = market.merge_partial_market_summary(
                    new + "\nBTC current", cached + "\nBTC old", None,
                )
                self.assertEqual(merged, new + "\nBTC current")
        separated = market.market_summary_with_separators(["加密市场", new])
        self.assertEqual(separated[1], market.TELEGRAM_SECTION_SEPARATOR)


if __name__ == "__main__":
    unittest.main()
