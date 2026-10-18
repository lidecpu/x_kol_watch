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
        self.assertEqual(record["filing_date"], dt.date(2026, 10, 5))

    def test_holdings_in_press_release_exhibit_are_not_skipped(self):
        filings = {"filings": {"recent": {
            "form": ["8-K", "8-K", "8-K"],
            "filingDate": ["2026-10-16", "2026-10-13", "2026-10-05"],
            "accessionNumber": ["dividend", "holdings", "old"],
            "primaryDocument": ["dividend.htm", "main.htm", "old.htm"],
        }}}
        exhibit = table(
            ["During Period October 5, 2026 to October 11, 2026", "", "As of October 11, 2026"],
            ["BTC Purchased (1)", "AggregatePurchase Price (in millions) (2)", "Average Purchase Price (2)",
             "Aggregate BTC Holdings", "Aggregate Purchase Price (in billions) (2)", "Average Purchase Price (2)"],
            ["250", "$", "21.5", "$", "86,194", "848,250", "$", "64.00", "$", "75,444"],
        )
        with patch.object(market.urllib.request, "urlopen", side_effect=[
            io.BytesIO(json.dumps(filings).encode()),
            io.BytesIO(b"<p>Dividend declaration.</p>"),
            io.BytesIO(b'<a href="mstr-ex99_1.htm">Press release, dated October 12, 2026</a>'),
            io.BytesIO(exhibit.encode()),
        ]) as opened, patch.object(market, "load_strategy_btc_cache", return_value={}):
            record = market.fetch_strategy_btc_sec()
        self.assertEqual(record["holdings"], 848250)
        self.assertEqual(record["change"], 250)
        self.assertEqual(record["holdings_as_of"], dt.date(2026, 10, 11))
        self.assertEqual(record["filing_date"], dt.date(2026, 10, 13))
        self.assertEqual(record["average_price"], 75444)
        self.assertEqual(record["total_cost_millions"], 64000)
        self.assertEqual(opened.call_count, 4)
        self.assertEqual(
            opened.call_args.args[0].full_url,
            market.STRATEGY_SEC_ARCHIVES_URL + "/holdings/mstr-ex99_1.htm",
        )

    def test_exhibit_links_outside_the_filing_are_not_followed(self):
        filings = {"filings": {"recent": {
            "form": ["8-K", "8-K"],
            "filingDate": ["2026-10-16", "2026-10-05"],
            "accessionNumber": ["new", "old"],
            "primaryDocument": ["main.htm", "old.htm"],
        }}}
        for href in (
            "https://example.com/press.htm",
            "https://www.sec.gov.evil.example/press.htm",
            "../old/ex99.htm",
            "ex99.htm?redirect=1",
            "https://user@www.sec.gov/Archives/edgar/data/1050446/new/ex99.htm",
        ):
            with self.subTest(href=href), patch.object(
                market.urllib.request, "urlopen", side_effect=[
                    io.BytesIO(json.dumps(filings).encode()),
                    io.BytesIO(f'<a href="{href}">Press release</a>'.encode()),
                    io.BytesIO(split_tables().encode()),
                ],
            ) as opened, patch.object(market, "load_strategy_btc_cache", return_value={}):
                record = market.fetch_strategy_btc_sec()
                self.assertEqual(record["filing_date"], dt.date(2026, 10, 5))
                self.assertEqual(opened.call_count, 3)

    def test_website_403_uses_sec(self):
        error = urllib.error.HTTPError(market.STRATEGY_PURCHASES_URL, 403, "Forbidden", {}, None)
        with patch.object(market.urllib.request, "urlopen", side_effect=error), \
                patch.object(market, "fetch_strategy_btc_sec", return_value={"holdings": 900000}) as sec:
            self.assertEqual(market.fetch_strategy_btc()["holdings"], 900000)
        sec.assert_called_once()

    def test_cache_preserves_verification_and_cutoff(self):
        record = market.parse_strategy_btc_sec(split_tables())
        record.update(
            verified_date=dt.date(2026, 10, 7),
            verification_source="SEC",
            filing_date=dt.date(2026, 10, 6),
        )
        with patch.object(market, "load_json", return_value={}), \
                patch.object(market, "save_json") as save:
            market.save_strategy_btc_cache(record)
        saved = save.call_args.args[1]
        with patch.object(market, "load_json", return_value=saved):
            restored = market.load_strategy_btc_cache()
        self.assertEqual(restored["holdings_as_of_time"], "04:00")
        self.assertEqual(restored["verification_source"], "SEC")
        self.assertEqual(restored["filing_date"], dt.date(2026, 10, 6))
        self.assertEqual(restored["change"], 334)

    def test_cached_holdings_label_preserves_cutoff_without_timezone(self):
        old = "BTC持仓 900,000枚 | 持仓截至 10-05 04:00（北京时间） | SEC核验 10-07"
        expected = "BTC持仓 900,000枚 | 持仓截至 10-05 04:00 | SEC核验 10-07"
        self.assertEqual(market.normalize_stablecoin_summary_labels(old), expected)
        self.assertEqual(market.normalize_stablecoin_summary_labels(expected), expected)

    def test_holdings_filing_date_is_preserved_separately_from_verification_date(self):
        record = market.parse_strategy_btc_sec(split_tables())
        record.update(
            verified_date=dt.date(2026, 10, 18),
            filing_date=dt.date(2026, 10, 13),
            verification_source="SEC",
        )
        with patch.object(market, "load_json", return_value={}), \
                patch.object(market, "save_json") as save:
            market.save_strategy_btc_cache(record)
        saved = save.call_args.args[1]
        with patch.object(market, "load_json", return_value=saved):
            restored = market.load_strategy_btc_cache()
        self.assertEqual(restored["filing_date"], dt.date(2026, 10, 13))
        self.assertEqual(restored["verified_date"], dt.date(2026, 10, 18))


class TreasuryDateTests(unittest.TestCase):
    def test_debt_uses_latest_published_date_not_fetch_date(self):
        payload = {"data": [
            {"record_date": "2026-10-15", "tot_pub_debt_out_amt": "40388317675071.91"},
            {"record_date": "2026-10-14", "tot_pub_debt_out_amt": "40329229827541.02"},
        ]}
        with patch.object(market, "fetch_market_json", return_value=payload):
            record = market.fetch_us_treasury_debt()
        self.assertEqual(record["record_date"], dt.date(2026, 10, 15))
        self.assertAlmostEqual(record["current"], 40388317675071.91, places=2)

    def test_yields_choose_latest_available_business_day(self):
        xml = (
            '<feed xmlns="http://www.w3.org/2005/Atom" '
            'xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata" '
            'xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices">'
            + "".join(
                '<entry><content><m:properties>'
                f'<d:NEW_DATE>{date}T00:00:00</d:NEW_DATE>'
                '<d:BC_2YEAR>4.74</d:BC_2YEAR><d:BC_5YEAR>4.89</d:BC_5YEAR>'
                '<d:BC_10YEAR>5.09</d:BC_10YEAR><d:BC_30YEAR>5.43</d:BC_30YEAR>'
                '</m:properties></content></entry>'
                for date in ("2026-10-16", "2026-10-15")
            )
            + '</feed>'
        )
        with patch.object(market.urllib.request, "urlopen", return_value=io.BytesIO(xml.encode())):
            record = market.fetch_us_treasury_yields()
        self.assertEqual(record["record_date"], dt.date(2026, 10, 16))


class GlobalVolumeTests(unittest.TestCase):
    def _payload(self, volume, percent=10.0):
        return {
            "data": {
                "total_volume": {"usd": volume},
                "volume_change_percentage_24h_usd": percent,
                "total_market_cap": {"usd": 2.7e12},
                "market_cap_change_percentage_24h_usd": -2.0,
                "market_cap_percentage": {"btc": 60.0, "eth": 11.0},
            }
        }

    def test_implausible_volume_is_omitted_but_market_data_is_kept(self):
        with patch.object(
            market, "fetch_market_json", return_value=self._payload(5.4e13, -69.0)
        ):
            result = market.fetch_global_volume()
        self.assertFalse(result["volume_valid"])
        self.assertIsNone(result["current"])
        self.assertIsNone(result["delta"])
        self.assertEqual(result["market_cap"], 2.7e12)
        self.assertEqual(result["eth_dominance"], 11.0)

    def test_normal_volume_is_returned(self):
        with patch.object(
            market, "fetch_market_json", return_value=self._payload(1.0e11)
        ):
            result = market.fetch_global_volume()
        self.assertTrue(result["volume_valid"])
        self.assertEqual(result["current"], 1.0e11)
        self.assertGreater(result["delta"], 0)


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
