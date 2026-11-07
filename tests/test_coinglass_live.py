import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import x_kol_daily as market


LIQUIDATION = {
    "current_price": 80000,
    "long_points": [{"price": 79000, "intensity": 200}],
    "short_points": [{"price": 81000, "intensity": 100}],
}
RATIO = {"long_users": 71507, "short_users": 24211, "ratio": 2.9535}
DOMINANCE = {"dominance": "59.94%", "dominance_change": "+0.20%"}
BALANCE = {
    "balance": "2,580,736.30",
    "balance_change_24h": "0.00",
    "balance_change_7d": "-18,382.30",
    "balance_change_30d": "-24,816.84",
}


class Page:
    def __init__(self, frames):
        self.frames = frames
        self.reads = 0
        self.closed = False

    async def goto(self, url, **kwargs):
        self.url = url

    async def evaluate(self, script):
        frame = self.frames[min(self.reads, len(self.frames) - 1)]
        self.reads += 1
        if isinstance(frame, Exception):
            raise frame
        return frame

    async def wait_for_timeout(self, milliseconds):
        await asyncio.sleep(0)

    async def close(self):
        self.closed = True


class CoinGlassLiveTests(unittest.TestCase):
    def collect(self, frames):
        pages = [Page(items) for items in frames]
        pending = iter(pages)

        async def new_page():
            return next(pending)

        async def noop(*args, **kwargs):
            pass

        context = SimpleNamespace(new_page=new_page, route=noop, close=noop)

        async def new_context(**kwargs):
            return context

        browser = SimpleNamespace(version="140.0", new_context=new_context, close=noop)

        async def launch(**kwargs):
            return browser

        class Playwright:
            async def __aenter__(self):
                return SimpleNamespace(chromium=SimpleNamespace(launch=launch))

            async def __aexit__(self, *args):
                pass

        with (
            patch("playwright.async_api.async_playwright", return_value=Playwright()),
            patch.object(market, "cleanup_chromium_debug_log"),
            patch.object(market, "COINGLASS_PAGE_WAIT_SECONDS", 0.05),
        ):
            snapshot = market.fetch_coinglass_live()
        self.assertTrue(all(page.closed for page in pages))
        return snapshot, pages

    def test_waits_for_complete_ratio_instead_of_accepting_first_loaded_count(self):
        snapshot, pages = self.collect([
            [LIQUIDATION],
            [{"long_users": 71507, "short_users": None, "ratio": None}, RATIO],
            [DOMINANCE],
            [BALANCE],
        ])
        self.assertEqual(snapshot["long_short_ratio"], {
            "interval": "day", "long_users": 71507, "short_users": 24211, "ratio": 2.9535,
        })
        self.assertGreaterEqual(pages[1].reads, 2)

    def test_invalid_ratio_does_not_discard_live_balance_dominance_or_liquidations(self):
        snapshot, _ = self.collect([
            [LIQUIDATION], [{"long_users": 71507}], [DOMINANCE], [BALANCE],
        ])
        self.assertEqual(snapshot["current_price"], 80000)
        self.assertEqual(snapshot["market_structure"]["btc_dominance"], 59.94)
        self.assertEqual(snapshot["market_structure"]["exchange_balance"], 2580736.30)
        self.assertNotIn("long_short_ratio", snapshot)

    def test_balance_updates_even_when_dominance_is_invalid(self):
        snapshot, _ = self.collect([
            [LIQUIDATION], [RATIO], [{"dominance": "loading"}], [BALANCE],
        ])
        self.assertEqual(snapshot["market_structure"]["exchange_balance"], 2580736.30)
        self.assertNotIn("btc_dominance", snapshot["market_structure"])

    def test_dominance_updates_even_when_balance_is_invalid(self):
        snapshot, _ = self.collect([
            [LIQUIDATION], [RATIO], [DOMINANCE], [{"balance": "loading"}],
        ])
        self.assertEqual(snapshot["market_structure"]["btc_dominance"], 59.94)
        self.assertNotIn("exchange_balance", snapshot["market_structure"])

    def test_waits_for_both_liquidation_sides(self):
        snapshot, pages = self.collect([
            [LIQUIDATION | {"short_points": []}, LIQUIDATION],
            [RATIO], [DOMINANCE], [BALANCE],
        ])
        self.assertEqual(snapshot["short_levels"][0]["price"], 81000)
        self.assertGreaterEqual(pages[0].reads, 2)


if __name__ == "__main__":
    unittest.main()
