import io
import json
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import MagicMock, patch

import x_kol_daily as kol


ROWS = [
    {"name": "first", "handle": "@first", "note": ""},
    {"name": "second", "handle": "@second", "note": ""},
]
ENV = {
    "CLOUDFLARE_BROWSER_API_TOKEN": "private-browser-token",
    "CLOUDFLARE_ACCOUNT_ID": "0" * 32,
}


class CloudflareCdpTests(unittest.TestCase):
    def setUp(self):
        self.playwright = MagicMock()
        self.local = MagicMock()
        self.source = MagicMock()
        self.local.contexts = [self.source]
        self.owned = self.source.new_page.return_value
        self.owned.evaluate.return_value = "D:\\Google缓存\\szwechat8\\Default"
        self.source.cookies.return_value = [
            {
                "name": name, "value": "private-" + name, "domain": ".x.com",
                "path": "/", "expires": -1, "secure": True,
                "httpOnly": name == "auth_token", "sameSite": "None",
            }
            for name in ("auth_token", "ct0")
        ]
        self.remote = MagicMock()
        self.remote_context = MagicMock()
        self.remote.contexts = [self.remote_context]
        self.added_cookies = []
        self.remote_context.add_cookies.side_effect = (
            lambda cookies: self.added_cookies.extend(dict(item) for item in cookies)
        )
        self.page = self.remote_context.new_page.return_value
        self.page.url = "https://x.com/home"
        self.playwright.chromium.connect_over_cdp.side_effect = [self.local, self.remote]

    def probe(self, scrape=None, source="http://[::1]:9222", **kwargs):
        with (
            patch.dict(os.environ, ENV, clear=True),
            patch("playwright.sync_api.sync_playwright") as factory,
            patch.object(kol, "cookies_from_env", side_effect=AssertionError("must not read project cookies")),
            patch.object(kol, "navigate_x_page"),
            patch.object(kol, "wait_for_x_page_ready"),
            patch.object(kol, "ensure_x_page_healthy"),
            patch.object(kol, "scrape_handle_url", side_effect=scrape) as scanner,
        ):
            factory.return_value.__enter__.return_value = self.playwright
            result = kol.cloudflare_cdp_probe(
                ROWS, 24, 8, 3, 2500, 900, True, cookie_cdp_url=source, **kwargs,
            )
        return result, scanner

    def assert_local_preserved(self):
        self.owned.close.assert_called_once()
        self.local.close.assert_not_called()
        self.source.close.assert_not_called()
        self.source.add_cookies.assert_not_called()
        self.source.clear_cookies.assert_not_called()
        self.source.route.assert_not_called()
        self.owned.goto.assert_called_once_with(
            "chrome://version", wait_until="domcontentloaded", timeout=10000,
        )

    def test_verified_source_scans_cloud_profiles_and_search_then_closes_remote(self):
        def scrape(page, handle, url, account_page, *args):
            merged = args[-2]
            self.assertIs(page, self.page)
            if account_page and handle == "@first":
                merged["123"] = {
                    "created_at_ms": 123, "created_at": "2026-01-01T00:00:00Z",
                    "text": "public body",
                }
            if not account_page:
                self.page.url = "https://x.com/search"

        result, scanner = self.probe(scrape)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["cookie_source"], "szwechat8")
        self.assertTrue(result["source_profile_verified"])
        self.assertEqual([row["tweet_count"] for row in result["results"]], [1, 0])
        self.assertEqual([row["search_fallback_used"] for row in result["results"]], [False, True])
        self.assertEqual(scanner.call_count, 3)
        self.assertEqual(result["coverage"], "bounded_scan")
        self.remote.close.assert_called_once()
        self.assertTrue(result["remote_closed"])
        added = self.added_cookies
        self.assertEqual({item["name"] for item in added}, {"auth_token", "ct0"})
        self.assertNotIn("expires", added[0])
        self.assert_local_preserved()
        for private in ("private-auth_token", "private-ct0", "private-browser-token", "public body"):
            self.assertNotIn(private, json.dumps(result))

    def test_wrong_profile_stops_before_reading_cookies_or_cloud_connection(self):
        self.owned.evaluate.return_value = "D:\\Google缓存\\other\\Default"
        result, scanner = self.probe()
        self.assertEqual(result["error"], "profile_verification_failed")
        self.source.cookies.assert_not_called()
        self.remote_context.add_cookies.assert_not_called()
        self.assertEqual(self.playwright.chromium.connect_over_cdp.call_count, 1)
        scanner.assert_not_called()
        self.assert_local_preserved()

    def test_missing_expired_or_ambiguous_cookie_stops_before_cloud_connection(self):
        cookies = self.source.cookies.return_value
        variants = (
            cookies[:1],
            [{**cookies[0], "expires": 1}, cookies[1]],
            [*cookies, {**cookies[0], "value": "another-value", "domain": "x.com"}],
        )
        for values in variants:
            with self.subTest(values=len(values)):
                self.setUp()
                self.source.cookies.return_value = values
                result, scanner = self.probe()
                self.assertEqual(result["error"], "source_cookies_failed")
                self.assertEqual(self.playwright.chromium.connect_over_cdp.call_count, 1)
                scanner.assert_not_called()
                self.assert_local_preserved()

    def test_cloud_connect_error_is_redacted(self):
        self.playwright.chromium.connect_over_cdp.side_effect = [
            self.local, RuntimeError("private-browser-token private-auth_token"),
        ]
        result, _ = self.probe()
        self.assertEqual(result["error"], "cloudflare_connection_failed")
        self.assertNotIn("private", json.dumps(result))
        self.assert_local_preserved()

    def test_challenge_stops_without_next_kol_or_retry_and_closes_remote(self):
        result, scanner = self.probe(scrape=RuntimeError(kol.X_VERIFICATION_REQUIRED_ERROR))
        self.assertEqual(result["error"], "verification_required")
        scanner.assert_called_once()
        self.remote.close.assert_called_once()
        self.assert_local_preserved()

    def test_search_errors_are_not_swallowed_as_zero_tweets_and_logs_are_redacted(self):
        with redirect_stderr(io.StringIO()) as stderr:
            result, scanner = self.probe(scrape=[None, RuntimeError("private-auth_token")])
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["failure_phase"], "search")
        self.assertEqual(result["results"], [])
        self.assertEqual(scanner.call_count, 2)
        self.assertNotIn("private-auth_token", json.dumps(result))
        self.assertNotIn("private-auth_token", stderr.getvalue())
        self.remote.close.assert_called_once()

    def test_search_redirect_cannot_be_classified_as_no_recent(self):
        def scrape(page, handle, url, account_page, *args):
            if not account_page:
                page.url = "https://x.com/i/jf/onboarding/web"

        result, _ = self.probe(scrape)
        self.assertEqual(result["error"], "authentication_required")
        self.assertEqual(result["results"], [])
        self.remote.close.assert_called_once()

    def test_home_redirect_stops_before_scanning(self):
        self.page.url = "https://x.com/i/jf/onboarding/web"
        result, scanner = self.probe()
        self.assertEqual(result["error"], "authentication_required")
        scanner.assert_not_called()
        self.remote.close.assert_called_once()

    def test_close_failure_is_reported_without_echoing_exception(self):
        self.remote.close.side_effect = RuntimeError("private-browser-token")
        result, _ = self.probe(scrape=RuntimeError(kol.X_VERIFICATION_REQUIRED_ERROR))
        self.assertFalse(result["remote_closed"])
        self.assertEqual(result["status"], "error")
        self.assertNotIn("private-browser-token", json.dumps(result))

    def test_budget_is_passed_to_every_scan_and_timeout_stops(self):
        result, scanner = self.probe(scrape=kol.RecoveryBudgetExceeded("private error"))
        self.assertEqual(result["status"], "error")
        self.assertIsInstance(scanner.call_args.args[-1], float)
        self.remote.close.assert_called_once()

    def test_project_credentials_never_read_local_browser(self):
        self.playwright.chromium.connect_over_cdp.side_effect = [self.remote]
        self.page.url = "https://x.com/i/flow/login"
        with (
            patch.dict(os.environ, ENV, clear=True),
            patch("playwright.sync_api.sync_playwright") as factory,
            patch.object(kol, "cookies_from_env", return_value=[
                {"name": "auth_token", "value": "project-private", "domain": ".x.com"},
            ]),
            patch.object(kol, "navigate_x_page"),
            patch.object(kol, "wait_for_x_page_ready"),
            patch.object(kol, "ensure_x_page_healthy"),
        ):
            factory.return_value.__enter__.return_value = self.playwright
            result = kol.cloudflare_cdp_probe(ROWS, 24, 8, 3, 2500, 900, True)
        self.assertEqual(result["cookie_source"], "project_env")
        self.source.cookies.assert_not_called()
        self.playwright.chromium.connect_over_cdp.assert_called_once()
        self.remote.close.assert_called_once()

    def test_direct_call_rejects_unbounded_selection_before_reading_credentials(self):
        for rows in ([], ROWS * 2):
            with (
                self.subTest(count=len(rows)),
                patch.object(kol, "cloudflare_browser_account_id") as account,
                self.assertRaises(ValueError),
            ):
                kol.cloudflare_cdp_probe(rows, 24, 8, 3, 2500, 900, True)
            account.assert_not_called()


class CloudflareCdpCliTests(unittest.TestCase):
    def test_invalid_modes_and_unbounded_inputs_fail_before_loading_credentials(self):
        for extra in (
            ["--send"], ["--market-only"], ["--cloudflare-probe"],
            ["--cache-recent", "1"], ["--translate-cache"],
            ["--cdp-url", "http://localhost:9222"],
            ["--limit", "9"], ["--scrolls", "7"], ["--page-wait-ms", "6001"],
            ["--scroll-wait-ms", "2001"],
            ["--cookie-cdp-url", "https://remote.example"],
        ):
            with (
                self.subTest(extra=extra),
                patch.object(kol.sys, "argv", [
                    "x_kol_daily.py", "--cloudflare-cdp-probe", "--max-kols", "1", *extra,
                ]),
                patch.object(kol, "load_dotenv") as load,
                redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit),
            ):
                kol.main()
            load.assert_not_called()

    def test_cookie_source_cannot_be_used_for_normal_scan(self):
        with (
            patch.object(kol.sys, "argv", [
                "x_kol_daily.py", "--cookie-cdp-url", "http://localhost:9222",
            ]),
            patch.object(kol, "load_dotenv") as load,
            redirect_stderr(io.StringIO()),
            self.assertRaises(SystemExit),
        ):
            kol.main()
        load.assert_not_called()

    def test_read_only_command_never_caches_reports_or_sends(self):
        with (
            patch.object(kol.sys, "argv", [
                "x_kol_daily.py", "--cloudflare-cdp-probe", "--max-kols", "2",
                "--cookie-cdp-url", "http://[::1]:9222",
            ]),
            patch.object(kol, "load_dotenv"),
            patch.object(kol, "parse_kols", return_value=ROWS),
            patch.object(kol, "apply_handle_aliases", side_effect=lambda rows: rows),
            patch.object(kol, "cloudflare_cdp_probe", return_value={"status": "ok"}) as probe,
            patch.object(kol, "scrape_all") as scan,
            patch.object(kol, "update_kol_status") as statuses,
            patch.object(kol, "update_tweet_store") as store,
            patch.object(kol, "save_json") as save,
            patch.object(kol, "REPORT_DIR") as reports,
            patch.object(kol, "STATE_DIR") as state,
            patch.object(kol, "telegram_send_reports_once") as telegram,
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(kol.main(), 0)
        self.assertEqual(probe.call_args.args[-1], "http://[::1]:9222")
        for operation in (scan, statuses, store, save, telegram):
            operation.assert_not_called()
        reports.mkdir.assert_not_called()
        state.mkdir.assert_not_called()


if __name__ == "__main__":
    unittest.main()
