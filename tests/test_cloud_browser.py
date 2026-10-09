import io
import unittest
from contextlib import redirect_stderr
from unittest.mock import MagicMock, patch

import x_kol_daily as kol


class CloudBrowserTests(unittest.TestCase):
    def scan_cloud(self, playwright, *, chrome_path="", headless=True, rows=None):
        with (
            patch.dict(kol.os.environ, {"CHROME_PATH": chrome_path}),
            patch("playwright.sync_api.sync_playwright") as factory,
            patch.object(kol, "cookies_from_env", return_value=[]),
            patch.object(kol, "cleanup_chromium_debug_log"),
            patch.object(kol, "wait_for_x_page_ready"),
            patch.object(kol, "ensure_x_page_healthy"),
            redirect_stderr(io.StringIO()),
        ):
            factory.return_value.__enter__.return_value = playwright
            return kol.scrape_all(
                [] if rows is None else rows, 24, 8, 1, headless, 2500, 900, False,
            )

    def test_headless_scan_uses_full_chromium_without_disabling_gpu(self):
        playwright = MagicMock()
        self.scan_cloud(playwright)
        options = playwright.chromium.launch.call_args.kwargs
        self.assertEqual(options["channel"], "chromium")
        self.assertTrue(options["headless"])
        self.assertNotIn("executable_path", options)
        self.assertNotIn("--disable-gpu", options["args"])
        self.assertNotIn("ignore_default_args", options)

    def test_explicit_executable_is_preserved(self):
        playwright = MagicMock()
        self.scan_cloud(playwright, chrome_path="/configured/chromium")
        options = playwright.chromium.launch.call_args.kwargs
        self.assertEqual(options["executable_path"], "/configured/chromium")
        self.assertNotIn("channel", options)
        self.assertTrue(options["headless"])

    def test_headed_scan_preserves_standard_launch(self):
        playwright = MagicMock()
        self.scan_cloud(playwright, headless=False)
        options = playwright.chromium.launch.call_args.kwargs
        self.assertNotIn("channel", options)
        self.assertFalse(options["headless"])

    def test_x_context_does_not_intercept_resources_or_persist_auth(self):
        browser = MagicMock()
        cookies = [{"name": "fixture_session", "value": "placeholder"}]
        context = kol.new_x_context(browser, cookies)
        browser.new_context.assert_called_once_with(
            locale="zh-CN", timezone_id="Asia/Shanghai",
        )
        self.assertIs(context, browser.new_context.return_value)
        context.add_cookies.assert_called_once_with(cookies)
        context.route.assert_not_called()
        context.add_init_script.assert_not_called()
        context.storage_state.assert_not_called()
        context.clear_cookies.assert_not_called()

    def test_recovery_reuses_new_headless_launch_options(self):
        playwright = MagicMock()
        rows = [{"name": "example", "handle": "@example", "note": ""}]
        with (
            patch.object(kol, "scrape_handle", side_effect=RuntimeError(kol.PAGE_RENDER_ERROR)),
            patch.object(kol, "RecoveryBudget") as budget,
            patch.object(kol, "rescan_page_render_failures"),
        ):
            budget.return_value.remaining_seconds = 30.0
            budget.return_value.spent_seconds = 60.0
            budget.return_value.limit_seconds = 90.0
            self.scan_cloud(playwright, rows=rows)
        calls = playwright.chromium.launch.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0].kwargs, calls[1].kwargs)
        self.assertEqual(calls[1].kwargs["channel"], "chromium")


class VerificationLogTests(unittest.TestCase):
    def test_header_diagnostic_does_not_log_url_or_response_secrets(self):
        page = MagicMock()
        response = page.goto.return_value
        response.request.resource_type = "document"
        response.frame = page.main_frame
        response.header_value.return_value = "challenge"
        response.status = 403
        response.url = "https://x.com/?private=fixture-secret"
        log = io.StringIO()
        with (
            redirect_stderr(log),
            self.assertRaisesRegex(RuntimeError, kol.X_VERIFICATION_REQUIRED_ERROR),
        ):
            kol.navigate_x_page(page, response.url, {}, "home")
        self.assertIn('"http_status": 403', log.getvalue())
        self.assertIn('"source": "response_header"', log.getvalue())
        self.assertNotIn("fixture-secret", log.getvalue())
        response.header_value.assert_called_with("cf-mitigated")
        response.all_headers.assert_not_called()
        response.text.assert_not_called()

    def test_page_diagnostic_does_not_log_page_text(self):
        page = MagicMock()
        page.evaluate.return_value = {
            "verificationRequired": True,
            "cloudflareChallenge": True,
            "textSample": "fixture-private-page-text",
        }
        log = io.StringIO()
        with (
            redirect_stderr(log),
            self.assertRaisesRegex(RuntimeError, kol.X_VERIFICATION_REQUIRED_ERROR),
        ):
            kol.ensure_x_page_healthy(page, diagnostics={}, phase="profile")
        self.assertIn('"source": "page"', log.getvalue())
        self.assertIn('"cloudflare_challenge": true', log.getvalue())
        self.assertNotIn("fixture-private-page-text", log.getvalue())
        page.reload.assert_not_called()


if __name__ == "__main__":
    unittest.main()
