import argparse
import io
import unittest
from contextlib import redirect_stderr
from unittest.mock import MagicMock, patch

import x_kol_daily as kol


class LocalCdpUrlTests(unittest.TestCase):
    def test_accepts_loopback_endpoints(self):
        for endpoint in (
            "http://127.0.0.1:9222",
            "http://localhost:9222",
            "ws://[::1]:9222/devtools/browser/example",
        ):
            with self.subTest(endpoint=endpoint):
                self.assertEqual(kol.local_cdp_url(endpoint), endpoint)

    def test_rejects_remote_and_credential_urls(self):
        for endpoint in (
            "https://example.com:9222",
            "http://127.0.0.1.example.com:9222",
            "http://user:password@localhost:9222",
            "http://localhost:9222?token=secret",
            "http://localhost:9222#secret",
            "file://localhost/browser",
            "http://localhost:not-a-port",
            "http://localhost:0",
        ):
            with self.subTest(endpoint=endpoint):
                with self.assertRaises(argparse.ArgumentTypeError):
                    kol.local_cdp_url(endpoint)


class LocalCdpScanTests(unittest.TestCase):
    def setUp(self):
        self.playwright = MagicMock()
        self.browser = self.playwright.chromium.connect_over_cdp.return_value
        self.context = MagicMock()
        self.browser.contexts = [self.context]
        self.page = self.context.new_page.return_value
        self.page.evaluate.return_value = "D:\\Google缓存\\szwechat8\\Default"
        self.rows = [
            {"name": "first", "handle": "@first", "note": ""},
            {"name": "second", "handle": "@second", "note": ""},
        ]

    def scan(self, rows=None, search_fallback=False):
        return kol.scrape_all_cdp(
            self.playwright, "http://127.0.0.1:9222",
            self.rows if rows is None else rows, 24, 8, 2, 2500, 900, search_fallback,
        )

    def assert_user_browser_preserved(self):
        self.page.close.assert_called_once()
        self.context.close.assert_not_called()
        self.context.add_cookies.assert_not_called()
        self.context.clear_cookies.assert_not_called()
        self.context.route.assert_not_called()
        self.browser.close.assert_not_called()
        self.browser.new_context.assert_not_called()

    @patch.object(kol, "cookies_from_env", side_effect=AssertionError("must not read cookies"))
    @patch.object(kol, "ensure_x_page_healthy")
    @patch.object(kol, "wait_for_x_page_ready")
    @patch.object(kol, "scrape_handle", side_effect=[[{"url": "example"}], []])
    def test_reuses_selected_profile_and_existing_scraper(self, scrape, wait, healthy, cookies):
        with redirect_stderr(io.StringIO()):
            results, timings = self.scan()
        self.assertEqual([item["status"] for item in results], ["ok", "ok"])
        self.assertEqual([len(item["tweets"]) for item in results], [1, 0])
        self.assertIn("x_total", timings)
        self.assertEqual(scrape.call_count, 2)
        self.playwright.chromium.connect_over_cdp.assert_called_once_with(
            "http://127.0.0.1:9222", no_defaults=True, timeout=15000,
        )
        self.assert_user_browser_preserved()

    @patch.object(kol, "ensure_x_page_healthy")
    @patch.object(kol, "wait_for_x_page_ready")
    @patch.object(kol, "scrape_handle", side_effect=RuntimeError(kol.X_VERIFICATION_REQUIRED_ERROR))
    def test_verification_stops_without_retrying_other_accounts(self, scrape, wait, healthy):
        with self.assertRaisesRegex(RuntimeError, kol.X_VERIFICATION_REQUIRED_ERROR):
            self.scan()
        scrape.assert_called_once()
        self.assert_user_browser_preserved()

    @patch.object(kol, "ensure_x_page_healthy")
    @patch.object(kol, "wait_for_x_page_ready")
    def test_access_restrictions_carry_prior_results_and_evidence(self, wait, healthy):
        tweet = {"url": "https://x.com/first/status/123", "text": "Public update"}

        def scrape(page, handle, *args):
            if handle == "@first":
                return [tweet]
            args[-1]["page_health"] = {
                "phase": "search_fallback",
                "cloudflare_challenge": True,
                "http_status": 403,
            }
            raise RuntimeError(kol.X_VERIFICATION_REQUIRED_ERROR)

        with (
            patch.object(kol, "scrape_handle", side_effect=scrape),
            redirect_stderr(io.StringIO()),
            self.assertRaises(kol.XScanInterrupted) as failure,
        ):
            self.scan()
        self.assertEqual(failure.exception.results[0]["tweets"], [tweet])
        self.assertEqual(failure.exception.handle, "@second")
        self.assertEqual(failure.exception.phase, "search_fallback")
        self.assertEqual(failure.exception.diagnostics["page_health"]["http_status"], 403)
        self.assert_user_browser_preserved()

    @patch.object(kol, "ensure_x_page_healthy")
    @patch.object(kol, "wait_for_x_page_ready")
    def test_owned_tab_cleanup_failure_cannot_replace_interruption(self, wait, healthy):
        tweet = {"url": "https://x.com/first/status/123"}
        self.page.close.side_effect = RuntimeError("private cleanup details")
        output = io.StringIO()
        with (
            patch.object(kol, "scrape_handle", side_effect=[
                [tweet], RuntimeError(kol.X_VERIFICATION_REQUIRED_ERROR),
            ]),
            redirect_stderr(output),
            self.assertRaises(kol.XScanInterrupted) as failure,
        ):
            self.scan()
        self.assertEqual(failure.exception.results[0]["tweets"], [tweet])
        self.assertEqual(str(failure.exception), kol.X_VERIFICATION_REQUIRED_ERROR)
        self.assertNotIn("private cleanup details", output.getvalue())
        self.assert_user_browser_preserved()

    def test_home_restriction_carries_evidence_and_does_not_start_profiles(self):
        response = MagicMock()
        response.request.resource_type = "document"
        response.frame = self.page.main_frame
        response.status = 429
        response.header_value.return_value = None
        self.page.goto.side_effect = [None, response]
        with (
            patch.object(kol, "scrape_handle", side_effect=AssertionError("must stop at home")),
            self.assertRaises(kol.XScanInterrupted) as failure,
        ):
            self.scan()
        self.assertEqual(failure.exception.phase, "home")
        self.assertEqual(failure.exception.results, [])
        self.assertEqual(failure.exception.diagnostics["page_health"]["http_status"], 429)
        self.assert_user_browser_preserved()

    @patch.object(kol, "ensure_x_page_healthy")
    @patch.object(kol, "wait_for_x_page_ready")
    def test_consecutive_render_failures_stop_before_next_profile(self, wait, healthy):
        rows = self.rows + [{"name": "third", "handle": "@third", "note": ""}]
        with (
            patch.object(kol, "scrape_handle", side_effect=[
                RuntimeError(kol.PAGE_RENDER_ERROR),
                RuntimeError(kol.PAGE_RENDER_ERROR),
                AssertionError("must not visit third"),
            ]),
            redirect_stderr(io.StringIO()),
            self.assertRaises(kol.XScanInterrupted) as failure,
        ):
            self.scan(rows)
        self.assertEqual(str(failure.exception), kol.GLOBAL_PAGE_DEFERRED_ERROR)
        self.assertEqual(failure.exception.handle, "@second")
        self.assertEqual(len(failure.exception.results), 2)
        self.assert_user_browser_preserved()

    @patch.object(kol, "ensure_x_page_healthy")
    @patch.object(kol, "wait_for_x_page_ready")
    def test_isolated_render_failure_keeps_later_success_but_is_not_complete(self, wait, healthy):
        tweet = {"url": "https://x.com/second/status/123"}
        with (
            patch.object(kol, "scrape_handle", side_effect=[
                RuntimeError(kol.PAGE_RENDER_ERROR), [tweet],
            ]),
            redirect_stderr(io.StringIO()),
            self.assertRaises(kol.XScanInterrupted) as failure,
        ):
            self.scan()
        self.assertEqual(str(failure.exception), kol.PAGE_RENDER_ERROR)
        self.assertEqual(failure.exception.handle, "@first")
        self.assertEqual(failure.exception.results[1]["tweets"], [tweet])
        self.assert_user_browser_preserved()

    @patch.object(kol, "ensure_x_page_healthy")
    @patch.object(kol, "wait_for_x_page_ready")
    def test_search_render_failure_is_not_reported_as_an_empty_success(self, wait, healthy):
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        for error in (RuntimeError(kol.PAGE_RENDER_ERROR), PlaywrightTimeoutError("timeout")):
            with self.subTest(error=type(error).__name__):
                with (
                    patch.object(kol, "scrape_handle_url", side_effect=[None, error]),
                    redirect_stderr(io.StringIO()),
                    self.assertRaises(kol.XScanInterrupted) as failure,
                ):
                    self.scan(self.rows[:1], search_fallback=True)
                self.assertEqual(failure.exception.results[0]["status"], "error")
                self.assertEqual(str(failure.exception), kol.PAGE_RENDER_ERROR)

    @patch.object(kol, "ensure_x_page_healthy")
    @patch.object(kol, "wait_for_x_page_ready")
    @patch.object(kol, "scrape_handle", side_effect=RuntimeError(kol.ACCOUNT_UNAVAILABLE_ERROR))
    def test_preserves_account_error_and_paused_status(self, scrape, wait, healthy):
        rows = [self.rows[0], {**self.rows[1], "auto_recheck_paused": True}]
        with redirect_stderr(io.StringIO()):
            results, _ = self.scan(rows)
        self.assertEqual([item["status"] for item in results], ["error", "paused"])
        self.assertTrue(results[0]["error"].endswith(kol.ACCOUNT_UNAVAILABLE_ERROR))
        scrape.assert_called_once()
        self.assert_user_browser_preserved()

    def test_navigation_failure_still_closes_only_owned_tab(self):
        self.page.goto.side_effect = RuntimeError("navigation failed")
        with self.assertRaisesRegex(RuntimeError, "navigation failed"):
            self.scan()
        self.assert_user_browser_preserved()

    def test_connection_errors_do_not_echo_endpoint_details(self):
        self.playwright.chromium.connect_over_cdp.side_effect = RuntimeError("private details")
        with self.assertRaisesRegex(RuntimeError, "cannot connect to local Chrome") as failure:
            self.scan()
        self.assertNotIn("private details", str(failure.exception))
        self.context.new_page.assert_not_called()

    def test_wrong_profile_is_rejected_before_accessing_x(self):
        self.page.evaluate.return_value = "D:\\Google缓存\\other-profile\\Default"
        with self.assertRaisesRegex(RuntimeError, "not connected to Google szwechat8"):
            self.scan()
        self.page.goto.assert_called_once_with(
            "chrome://version", wait_until="domcontentloaded", timeout=10000,
        )
        self.assert_user_browser_preserved()

    def test_missing_profile_is_rejected_before_accessing_x(self):
        self.page.evaluate.return_value = ""
        with self.assertRaisesRegex(RuntimeError, "not connected to Google szwechat8"):
            self.scan()
        self.assert_user_browser_preserved()


class LocalCdpCliTests(unittest.TestCase):
    def run_dry(self, arguments):
        with (
            patch.object(kol.sys, "argv", ["x_kol_daily.py", *arguments]),
            patch.object(kol, "load_dotenv"),
            patch.object(kol, "parse_kols", return_value=[]),
            patch.object(kol, "apply_handle_aliases", side_effect=lambda rows: rows),
            patch("builtins.print"),
        ):
            return kol.main()

    def test_local_mode_parses_explicit_urls(self):
        self.assertEqual(
            self.run_dry(["--cdp-url", "http://localhost:9222", "--dry-run"]), 0,
        )

    def test_local_mode_requires_explicit_url(self):
        with (
            redirect_stderr(io.StringIO()),
            self.assertRaises(SystemExit),
        ):
            self.run_dry(["--cdp-url", "--dry-run"])

    def test_remote_endpoint_is_rejected_before_loading_secrets(self):
        with (
            patch.object(kol.sys, "argv", ["x_kol_daily.py", "--cdp-url", "https://example.com"]),
            patch.object(kol, "load_dotenv") as load,
            redirect_stderr(io.StringIO()),
            self.assertRaises(SystemExit),
        ):
            kol.main()
        load.assert_not_called()


if __name__ == "__main__":
    unittest.main()
