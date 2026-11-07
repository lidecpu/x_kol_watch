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
        error.close()

    def test_incomplete_primary_still_checks_same_filing_exhibit(self):
        filings = {"filings": {"recent": {
            "form": ["8-K"],
            "filingDate": ["2026-10-05"],
            "accessionNumber": ["holdings"],
            "primaryDocument": ["main.htm"],
        }}}
        primary = (
            '<p>Strategy holds approximately 900,000 bitcoin.</p>'
            '<a href="ex99.htm">Press release</a>'
        )
        with patch.object(market.urllib.request, "urlopen", side_effect=[
            io.BytesIO(json.dumps(filings).encode()),
            io.BytesIO(primary.encode()),
            io.BytesIO(split_tables().encode()),
        ]), patch.object(market, "load_strategy_btc_cache", return_value={}):
            record = market.fetch_strategy_btc_sec()
        self.assertEqual(record["holdings"], 900000)
        self.assertEqual(record["filing_date"], dt.date(2026, 10, 5))
        self.assertFalse(record.get("unverified_filings"))

    def test_incomplete_newer_filing_does_not_relabel_older_record(self):
        filings = {"filings": {"recent": {
            "form": ["8-K", "8-K"],
            "filingDate": ["2026-10-29", "2026-10-05"],
            "accessionNumber": ["incomplete", "holdings"],
            "primaryDocument": ["main.htm", "btc.htm"],
        }}}
        with patch.object(market.urllib.request, "urlopen", side_effect=[
            io.BytesIO(json.dumps(filings).encode()),
            io.BytesIO(b"<p>Strategy holds approximately 900,000 bitcoin.</p>"),
            io.BytesIO(split_tables().encode()),
        ]), patch.object(market, "load_strategy_btc_cache", return_value={}):
            record = market.fetch_strategy_btc_sec()
        self.assertEqual(record["filing_date"], dt.date(2026, 10, 5))
        self.assertEqual(record["holdings_as_of"], dt.date(2026, 10, 5))
        self.assertEqual(record["unverified_filings"], ["2026-10-29"])

    def test_unreadable_exhibit_does_not_block_other_exhibits(self):
        filings = {"filings": {"recent": {
            "form": ["8-K"],
            "filingDate": ["2026-10-05"],
            "accessionNumber": ["holdings"],
            "primaryDocument": ["main.htm"],
        }}}
        with patch.object(market.urllib.request, "urlopen", side_effect=[
            io.BytesIO(json.dumps(filings).encode()),
            io.BytesIO(b'<a href="broken.htm">Press release</a><a href="btc.htm">Press release</a>'),
            TimeoutError("exhibit unavailable"),
            io.BytesIO(split_tables().encode()),
        ]), patch.object(market, "load_strategy_btc_cache", return_value={}):
            record = market.fetch_strategy_btc_sec()
        self.assertEqual(record["holdings"], 900000)
        self.assertFalse(record.get("unverified_filings"))

    def test_website_layout_change_uses_sec(self):
        with patch.object(
            market.urllib.request, "urlopen",
            return_value=io.BytesIO(b"<main>New ledger layout</main>"),
        ), patch.object(market, "fetch_strategy_btc_sec", return_value={"holdings": 900000}):
            self.assertEqual(market.fetch_strategy_btc()["holdings"], 900000)

    def test_cache_retains_newer_unverified_filing_warning(self):
        record = market.parse_strategy_btc_sec(split_tables())
        record.update(
            verified_date=dt.date(2026, 11, 2),
            verification_source="SEC",
            filing_date=dt.date(2026, 10, 5),
            unverified_filings=["2026-10-29"],
        )
        with patch.object(market, "load_json", return_value={}), \
                patch.object(market, "save_json") as save:
            market.save_strategy_btc_cache(record)
        with patch.object(market, "load_json", return_value=save.call_args.args[1]):
            restored = market.load_strategy_btc_cache()
        self.assertEqual(restored.get("unverified_filings"), ["2026-10-29"])

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

    def _fallback(self, volume=1.2e11, percent=20.0, age=0):
        return {
            "market_cap_usd": 2.8e12,
            "volume_24h_usd": volume,
            "volume_24h_change_24h": percent,
            "last_updated": market.cn_now().timestamp() - age,
        }

    def test_implausible_volume_uses_fallback_and_keeps_market_data(self):
        with patch.object(
            market, "fetch_market_json", side_effect=[
                self._payload(5.4e13, -69.0), self._fallback(),
            ],
        ) as fetch:
            result = market.fetch_global_volume()
        self.assertTrue(result["volume_valid"])
        self.assertEqual(result["current"], 1.2e11)
        self.assertAlmostEqual(result["delta"], 2e10)
        self.assertEqual(result["percent"], 20.0)
        self.assertEqual(result["volume_source"], "CoinPaprika")
        self.assertEqual(result["market_cap"], 2.7e12)
        self.assertEqual(result["market_cap_percent"], -2.0)
        self.assertEqual(result["btc_dominance"], 60.0)
        self.assertEqual(result["eth_dominance"], 11.0)
        self.assertEqual(fetch.call_args.args[0], market.COINPAPRIKA_GLOBAL_URL)

    def test_failed_fallback_keeps_market_data_without_fake_volume(self):
        with patch.object(
            market, "fetch_market_json", side_effect=[
                self._payload(5.4e13, -69.0), OSError("unavailable"),
            ],
        ):
            result = market.fetch_global_volume()
        self.assertFalse(result["volume_valid"])
        self.assertIsNone(result["current"])
        self.assertIsNone(result["delta"])
        self.assertIsNone(result["percent"])
        self.assertEqual(result["market_cap"], 2.7e12)
        self.assertEqual(result["eth_dominance"], 11.0)

    def test_normal_volume_is_returned(self):
        with patch.object(
            market, "fetch_market_json", return_value=self._payload(1.0e11)
        ) as fetch:
            result = market.fetch_global_volume()
        fetch.assert_called_once_with(market.COINGECKO_GLOBAL_URL)
        self.assertTrue(result["volume_valid"])
        self.assertEqual(result["current"], 1.0e11)
        self.assertGreater(result["delta"], 0)
        self.assertEqual(result["volume_source"], "CoinGecko")

    def test_invalid_primary_volume_or_change_uses_fallback(self):
        for volume, percent in (
            (None, 10), (float("nan"), 10), (float("inf"), 10),
            (-1, 10), (0, 10), (1e11, None), (1e11, float("nan")),
            (1e11, -100), (1e11, -101),
        ):
            with self.subTest(volume=volume, percent=percent), patch.object(
                market, "fetch_market_json", side_effect=[
                    self._payload(volume, percent), self._fallback(),
                ],
            ):
                result = market.fetch_global_volume()
            self.assertEqual(result["volume_source"], "CoinPaprika")

    def test_invalid_or_stale_fallback_is_rejected(self):
        fallbacks = [
            self._fallback(volume=5.4e13),
            self._fallback(volume=float("nan")),
            self._fallback(volume=0),
            self._fallback(percent=-100),
            self._fallback(percent=float("inf")),
            self._fallback(age=market.GLOBAL_VOLUME_MAX_AGE_SECONDS + 1),
            self._fallback(age=-600),
            self._fallback() | {"last_updated": None},
            self._fallback() | {"last_updated": float("nan")},
        ]
        for fallback in fallbacks:
            with self.subTest(fallback=fallback), patch.object(
                market, "fetch_market_json", side_effect=[
                    self._payload(5.4e13), fallback,
                ],
            ):
                result = market.fetch_global_volume()
            self.assertFalse(result["volume_valid"])
            self.assertIsNone(result["current"])

    def test_zero_and_negative_fallback_changes_are_preserved(self):
        for percent in (0, -20):
            with self.subTest(percent=percent), patch.object(
                market, "fetch_market_json", side_effect=[
                    self._payload(5.4e13), self._fallback(percent=percent),
                ],
            ):
                result = market.fetch_global_volume()
            previous = 1.2e11 / (1 + percent / 100)
            self.assertAlmostEqual(result["delta"], 1.2e11 - previous)
            self.assertEqual(result["percent"], percent)

    def test_primary_request_failures_also_use_fallback(self):
        errors = [
            TimeoutError("timed out"),
            urllib.error.URLError("connection failed"),
            urllib.error.HTTPError(market.COINGECKO_GLOBAL_URL, 429, "limited", {}, None),
            urllib.error.HTTPError(market.COINGECKO_GLOBAL_URL, 503, "unavailable", {}, None),
            json.JSONDecodeError("invalid JSON", "", 0),
            market.http.client.IncompleteRead(b"partial"),
        ]
        for error in errors:
            with self.subTest(error=type(error).__name__), patch.object(
                market, "fetch_market_json", side_effect=[error, self._fallback()],
            ) as fetch:
                result = market.fetch_global_volume()
            self.assertTrue(result["volume_valid"])
            self.assertEqual(result["volume_source"], "CoinPaprika")
            self.assertEqual(result["current"], 1.2e11)
            self.assertEqual(result["market_cap"], 2.8e12)
            self.assertEqual(fetch.call_count, 2)
            if isinstance(error, urllib.error.HTTPError):
                error.close()

    def test_malformed_primary_response_also_uses_fallback(self):
        for payload in (None, [], {}, {"data": None}, self._payload(1e11) | {"data": {}}):
            with self.subTest(payload=payload), patch.object(
                market, "fetch_market_json", side_effect=[payload, self._fallback()],
            ):
                result = market.fetch_global_volume()
            self.assertTrue(result["volume_valid"])
            self.assertEqual(result["volume_source"], "CoinPaprika")
            self.assertEqual(result["market_cap"], 2.8e12)

    def test_fallback_market_cap_is_validated_when_primary_is_down(self):
        for cap in (None, float("nan"), float("inf"), 0, -1):
            with self.subTest(cap=cap), patch.object(
                market, "fetch_market_json", side_effect=[
                    TimeoutError(), self._fallback() | {"market_cap_usd": cap},
                ],
            ):
                result = market.fetch_global_volume()
            self.assertFalse(result["volume_valid"])
            self.assertIsNone(result["current"])

    def test_both_sources_down_do_not_create_fake_market_data(self):
        with patch.object(
            market, "fetch_market_json", side_effect=[TimeoutError(), OSError()],
        ):
            result = market.fetch_global_volume()
        self.assertFalse(result["volume_valid"])
        self.assertIsNone(result["current"])
        self.assertNotIn("market_cap", result)

    def test_primary_failure_uses_available_fallback_market_metadata(self):
        fallback = self._fallback() | {
            "market_cap_change_24h": -1.5,
            "bitcoin_dominance_percentage": 57.0,
        }
        with patch.object(
            market, "fetch_market_json", side_effect=[TimeoutError(), fallback],
        ):
            result = market.fetch_global_volume()
        self.assertTrue(result["volume_valid"])
        self.assertEqual(result["market_cap"], 2.8e12)
        self.assertEqual(result["market_cap_percent"], -1.5)
        self.assertEqual(result["btc_dominance"], 57.0)
        self.assertEqual(result["market_source"], "CoinPaprika")
        self.assertNotIn("eth_dominance", result)

    def test_invalid_optional_fallback_metadata_does_not_invent_changes(self):
        for change, dominance in ((None, None), ("bad", "bad"), (float("nan"), float("nan")), (float("inf"), 101)):
            with self.subTest(change=change, dominance=dominance), patch.object(
                market, "fetch_market_json", side_effect=[
                    TimeoutError(), self._fallback() | {
                        "market_cap_change_24h": change,
                        "bitcoin_dominance_percentage": dominance,
                    },
                ],
            ):
                result = market.fetch_global_volume()
            self.assertTrue(result["volume_valid"])
            self.assertIsNone(result["market_cap_percent"])
            self.assertIsNone(result["btc_dominance"])


class GlobalVolumeRenderingTests(unittest.TestCase):
    def _summary(self, global_volume, dex_volume=None, **overrides):
        dex_volume = dex_volume or {
            "current": 1e10, "delta": 2e9, "percent": 25.0,
        }
        replacements = dict(
            previous_derivatives_volume=lambda _: None,
            previous_eth_staking_total=lambda _: None,
            fetch_dex_volume=lambda: dex_volume,
            fetch_global_volume=lambda: global_volume,
            fetch_chain_activity=lambda: {},
            fetch_derivatives_volume=lambda: 1e11,
            fetch_eth_staking_metrics=lambda: {},
            fetch_us_treasury_debt=lambda: {},
            fetch_us_treasury_yields=lambda: {},
            fetch_stablecoin_supply=lambda: {},
            fetch_stablecoin_volumes=lambda: {},
            fetch_strategy_btc=lambda: {},
            load_strategy_btc_cache=lambda: {},
            fetch_us_macro_calendar=lambda **_: {},
            fetch_bitmine_eth=lambda: {},
            fetch_coinglass_snapshot=lambda: {},
            fetch_spot_etf_flow_snapshot=lambda: {},
            save_derivatives_snapshot=lambda *_: None,
            save_eth_staking_snapshot=lambda *_, **__: None,
            save_json=lambda *_: None,
        )
        replacements.update(overrides)
        with patch.multiple(market, **replacements):
            return market.fetch_stablecoin_summary()

    def _volume(self):
        return {
            **market.global_spot_volume_record(1.2e11, 20, 2.7e12),
            "volume_source": "CoinPaprika",
            "market_cap": 2.7e12,
            "market_cap_percent": -2.0,
            "btc_dominance": 60.0,
            "eth_dominance": 11.0,
        }

    def test_fallback_total_dex_and_cex_use_consistent_changes(self):
        summary = self._summary(self._volume())
        self.assertIn("全网 1200.00亿 | +200.00亿（+20.00%） | 来源 CoinPaprika", summary)
        self.assertIn("DEX 100.00亿 | +20.00亿（+25.00%）", summary)
        self.assertIn("CEX估算 1100.00亿 | +180.00亿（+19.57%）", summary)
        self.assertNotIn("全网 暂不可用", summary)
        self.assertNotIn("CEX估算 暂不可用", summary)

    def test_both_sources_failed_are_visible_as_unavailable(self):
        summary = self._summary({})
        self.assertIn("全网 暂不可用", summary)
        self.assertIn("DEX 100.00亿", summary)
        self.assertIn("CEX估算 暂不可用", summary)

    def test_cex_is_not_negative_when_total_is_less_than_dex(self):
        summary = self._summary(self._volume(), {
            "current": 2e11, "delta": 2e10, "percent": 100 / 9,
        })
        self.assertIn("全网 1200.00亿", summary)
        self.assertIn("CEX估算 暂不可用", summary)
        self.assertNotIn("CEX估算 -", summary)

    def test_fallback_volume_renders_when_primary_market_metadata_is_missing(self):
        volume = self._volume()
        for key in ("market_cap", "market_cap_percent", "btc_dominance", "eth_dominance"):
            volume.pop(key)
        summary = self._summary(volume)
        self.assertIn("总市值 暂不可用", summary)
        self.assertIn("全网 1200.00亿", summary)
        self.assertIn("CEX估算 1100.00亿", summary)
        self.assertNotIn("ETH占比", summary.split("数据提示")[0])

    def test_fallback_metadata_source_and_missing_change_are_visible(self):
        volume = self._volume()
        volume.pop("eth_dominance")
        volume.update(market_cap_percent=None, market_source="CoinPaprika")
        summary = self._summary(volume)
        self.assertIn("总市值 2.70万亿美元 | 24H 暂不可用 | 来源 CoinPaprika", summary)
        self.assertIn("BTC占比 60.00%", summary)
        self.assertNotIn("ETH占比", summary.split("数据提示")[0])
        self.assertIn("CEX估算 1100.00亿", summary)

    def test_staking_unchanged_warning_reaches_report_without_inventing_source_date(self):
        metrics = {"total": 43948738.0, "percent": 35.0, "apr": 2.5}
        now = dt.datetime(2026, 11, 2, 12, 0, tzinfo=market.CN_TZ)
        state = {"eth_staking_freshness": metrics | {
            "unchanged_since": "2026-10-16T12:00:00+08:00",
        }}
        with patch.object(market, "cn_now", return_value=now):
            summary = self._summary(
                self._volume(),
                fetch_eth_staking_metrics=lambda: metrics,
                load_json=lambda *_: state,
                save_eth_staking_snapshot=market.save_eth_staking_snapshot,
            )
        self.assertIn("质押量 4394.87万枚", summary)
        self.assertIn("来源 ethereum.org | 本次观测 11-02 12:00", summary)
        self.assertIn("观测值自 10-16 未变", summary)
        self.assertNotIn("数据截至 11-02", summary)

    def test_new_staking_observation_discloses_local_observation_time(self):
        metrics = {"total": 43948738.0, "percent": 35.0, "apr": 2.5}
        summary = self._summary(
            self._volume(),
            fetch_eth_staking_metrics=lambda: metrics,
            load_json=lambda *_: {},
            save_eth_staking_snapshot=market.save_eth_staking_snapshot,
        )
        self.assertIn("来源 ethereum.org | 本次观测", summary)
        self.assertNotIn("观测值自", summary)

    def test_partial_hyperliquid_snapshot_marks_ratio_unavailable(self):
        snapshot = {
            "current_price": 80000.0,
            "long_levels": [
                {"price": 79000.0, "intensity": 200.0, "distance_percent": -1.25},
            ],
            "short_levels": [
                {"price": 81000.0, "intensity": 200.0, "distance_percent": 1.25},
            ],
            "market_structure": {
                "btc_dominance": 60.0,
                "btc_dominance_change_24h": 0.1,
                "exchange_balance": 2500000.0,
                "exchange_balance_change_24h": -100.0,
                "exchange_balance_change_7d": -1000.0,
                "exchange_balance_change_30d": -2000.0,
            },
            "_captured_at": "2026-11-02T12:00:00+08:00",
        }
        summary = self._summary(
            self._volume(),
            fetch_coinglass_snapshot=lambda: snapshot,
        )
        self.assertIn("持仓人数多空比（1天）暂不可用", summary)

    def test_live_liquidation_heading_keeps_section_separator(self):
        lines = market.market_summary_with_separators([
            "加密市场", "总市值 2.50万亿美元",
            "Hyperliquid清算价（BTC，截至 11-08 03:50）", "现价 $80,000",
        ])
        self.assertEqual(lines[2], market.TELEGRAM_SECTION_SEPARATOR)

    def test_ratio_renders_without_liquidation_chart(self):
        summary = self._summary(
            self._volume(),
            fetch_coinglass_snapshot=lambda: {
                "long_short_ratio": {
                    "long_users": 71507, "short_users": 24211, "ratio": 2.9535,
                },
                "_captured_at": "2026-11-08T03:50:00+08:00",
            },
        )
        self.assertIn("多单 71,507", summary)
        self.assertIn("空单 24,211", summary)
        self.assertIn("多空比 2.95", summary)

    def test_partial_market_structure_keeps_live_exchange_balance(self):
        summary = self._summary(
            self._volume(),
            fetch_coinglass_snapshot=lambda: {"market_structure": {
                "exchange_balance": 2580736.30,
                "exchange_balance_change_24h": 0,
                "exchange_balance_change_7d": -18382.30,
                "exchange_balance_change_30d": -24816.84,
            }},
        )
        self.assertIn("交易所BTC 258.07万枚", summary)
        self.assertIn("BTC占比 60.00%", summary)

    def test_newer_unverified_sec_filing_warning_is_visible_in_report(self):
        record = market.parse_strategy_btc_sec(split_tables())
        record.update(
            verified_date=dt.date(2026, 11, 2), filing_date=dt.date(2026, 10, 5),
            verification_source="SEC", unverified_filings=["2026-10-29"],
        )
        summary = self._summary(
            self._volume(), fetch_strategy_btc=lambda: record,
            save_strategy_btc_cache=lambda *_: None,
        )
        self.assertIn("SEC披露 10-05", summary)
        self.assertIn("SEC记录核验 11-02", summary)
        self.assertIn("较新SEC文件未完成核验：10-29", summary)
        self.assertNotIn("SEC披露 10-29", summary)

    def test_strategy_refresh_failure_does_not_reuse_cached_holdings(self):
        record = market.parse_strategy_btc_sec(split_tables())
        record.update(
            verified_date=dt.date(2026, 10, 25), filing_date=dt.date(2026, 10, 5),
            verification_source="SEC",
        )
        summary = self._summary(
            self._volume(), fetch_strategy_btc=lambda: {},
            load_strategy_btc_cache=lambda: record,
        )
        self.assertIn("Strategy（微策略）\nBTC持仓 暂不可用", summary)
        self.assertNotIn("SEC核验 10-25", summary)
        self.assertNotIn("沿用", summary)


class MarketSeparatorTests(unittest.TestCase):
    def test_live_and_cached_reports_use_short_separators(self):
        self.assertEqual(market.TELEGRAM_SECTION_SEPARATOR, "━" * 40)
        for separator in ("", "━" * 20, "━" * 51, market.TELEGRAM_SECTION_SEPARATOR):
            with self.subTest(separator_length=len(separator)):
                summary = "\n".join(line for line in [
                    "加密市场", "总市值 unchanged", separator,
                    "市场现货（亿美元）", "全网 unchanged",
                ] if line)
                report = market.build_market_report(24, summary, generated_at="00:00")
                self.assertEqual(report.splitlines(), [
                    "市场全景 24H | 00:00",
                    "加密市场", "总市值 unchanged",
                    market.TELEGRAM_SECTION_SEPARATOR,
                    "市场现货（亿美元）", "全网 unchanged",
                ])

    def test_old_and_new_separators_remain_recognizable(self):
        self.assertTrue(market.is_telegram_section_separator("━" * 51))
        self.assertTrue(market.is_telegram_section_separator(market.TELEGRAM_SECTION_SEPARATOR))
        self.assertFalse(market.is_telegram_section_separator("市场现货（亿美元）"))


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

    def test_chain_activity_starts_a_separate_section(self):
        heading = market.chain_activity_heading(dt.date(2026, 10, 5))
        separated = market.market_summary_with_separators(["加密市场", heading])
        self.assertEqual(separated[1], market.TELEGRAM_SECTION_SEPARATOR)


if __name__ == "__main__":
    unittest.main()
