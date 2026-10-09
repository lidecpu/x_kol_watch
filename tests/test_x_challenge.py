import io
import unittest
from contextlib import redirect_stderr
from unittest.mock import MagicMock, patch

import x_kol_daily as kol


def challenged_response(page, status=403):
    response = MagicMock()
    response.request.resource_type = "document"
    response.frame = page.main_frame
    response.header_value.return_value = "challenge"
    response.status = status
    return response


class ChallengeNavigationTests(unittest.TestCase):
    def test_challenge_header_stops_before_dom_or_waits(self):
        page = MagicMock()
        page.goto.return_value = challenged_response(page)
        diagnostics = {}
        with self.assertRaisesRegex(RuntimeError, kol.X_VERIFICATION_REQUIRED_ERROR):
            kol.navigate_x_page(page, "https://x.com/example", diagnostics, "profile")
        self.assertEqual(diagnostics["page_health"], {
            "phase": "profile",
            "verification_required": True,
            "cloudflare_challenge": True,
            "challenge_source": "response_header",
            "http_status": 403,
        })
        page.evaluate.assert_not_called()
        page.wait_for_timeout.assert_not_called()
        page.remove_listener.assert_called_once_with("response", page.on.call_args.args[1])

    def test_challenge_is_classified_when_goto_raises(self):
        page = MagicMock()

        def navigate(*args, **kwargs):
            page.on.call_args.args[1](challenged_response(page))
            raise RuntimeError("net::ERR_HTTP_RESPONSE_CODE_FAILURE")

        page.goto.side_effect = navigate
        with self.assertRaisesRegex(RuntimeError, kol.X_VERIFICATION_REQUIRED_ERROR):
            kol.navigate_x_page(page, "https://x.com/example")
        page.remove_listener.assert_called_once()

    def test_plain_403_does_not_imply_challenge(self):
        page = MagicMock()
        response = challenged_response(page)
        response.header_value.return_value = None
        page.goto.return_value = response
        kol.navigate_x_page(page, "https://x.com/example")
        page.remove_listener.assert_called_once()

    def test_subresource_and_child_frame_challenges_are_not_document_challenges(self):
        for field in ("resource_type", "frame"):
            with self.subTest(field=field):
                page = MagicMock()
                response = challenged_response(page)
                if field == "resource_type":
                    response.request.resource_type = "image"
                else:
                    response.frame = MagicMock()
                page.goto.return_value = response
                kol.navigate_x_page(page, "https://x.com/example")

    def test_unrelated_navigation_failure_is_preserved(self):
        page = MagicMock()
        page.goto.side_effect = RuntimeError("network unavailable")
        with self.assertRaisesRegex(RuntimeError, "network unavailable"):
            kol.navigate_x_page(page, "https://x.com/example")
        page.remove_listener.assert_called_once()

    def test_reload_challenge_uses_same_detection(self):
        page = MagicMock()
        page.evaluate.return_value = {"hasMain": False}
        page.reload.return_value = challenged_response(page)
        with self.assertRaisesRegex(RuntimeError, kol.X_VERIFICATION_REQUIRED_ERROR):
            kol.ensure_x_page_healthy(page)
        page.reload.assert_called_once()
        page.wait_for_timeout.assert_not_called()


class ChallengeHealthTests(unittest.TestCase):
    def test_readiness_returns_immediately_for_verification(self):
        page = MagicMock()
        page.evaluate.return_value = {"verificationRequired": True}
        kol.wait_for_x_page_ready(page, 5000, None)
        page.evaluate.assert_called_once()
        page.wait_for_timeout.assert_not_called()

    def test_dom_verification_is_recorded_without_reload(self):
        page = MagicMock()
        page.evaluate.return_value = {
            "verificationRequired": True,
            "cloudflareChallenge": True,
            "hasMain": False,
        }
        diagnostics = {}
        with self.assertRaisesRegex(RuntimeError, kol.X_VERIFICATION_REQUIRED_ERROR):
            kol.ensure_x_page_healthy(page, diagnostics=diagnostics)
        self.assertTrue(diagnostics["page_health"]["verification_required"])
        self.assertTrue(diagnostics["page_health"]["cloudflare_challenge"])
        page.reload.assert_not_called()

    def test_generic_render_failure_still_reloads(self):
        page = MagicMock()
        page.evaluate.return_value = {"hasMain": False}
        with self.assertRaisesRegex(RuntimeError, kol.PAGE_RENDER_ERROR):
            kol.ensure_x_page_healthy(page)
        page.reload.assert_called_once()


class ChallengePropagationTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            {"name": "first", "handle": "@first", "note": ""},
            {"name": "second", "handle": "@second", "note": ""},
        ]

    def scan_cloud(self, playwright, **kwargs):
        with (
            patch("playwright.sync_api.sync_playwright") as factory,
            patch.object(kol, "cookies_from_env", return_value=[]),
            patch.object(kol, "cleanup_chromium_debug_log"),
            redirect_stderr(io.StringIO()),
        ):
            factory.return_value.__enter__.return_value = playwright
            return kol.scrape_all(self.rows, 24, 8, 2, True, 2500, 900, **kwargs)

    def test_home_challenge_does_not_start_profiles_or_restart_browser(self):
        playwright = MagicMock()
        browser = playwright.chromium.launch.return_value
        page = browser.new_context.return_value.new_page.return_value
        page.goto.return_value = challenged_response(page)
        with (
            patch.object(kol, "scrape_handle") as scrape,
            patch.object(kol, "RecoveryBudget") as recovery,
            self.assertRaisesRegex(RuntimeError, kol.X_VERIFICATION_REQUIRED_ERROR),
        ):
            self.scan_cloud(playwright, search_fallback=True)
        scrape.assert_not_called()
        recovery.assert_not_called()
        playwright.chromium.launch.assert_called_once()
        browser.new_context.return_value.close.assert_called_once()
        browser.close.assert_called_once()

    def test_profile_challenge_stops_before_next_account_and_recovery(self):
        playwright = MagicMock()
        with (
            patch.object(kol, "wait_for_x_page_ready"),
            patch.object(kol, "ensure_x_page_healthy"),
            patch.object(kol, "scrape_handle", side_effect=RuntimeError(kol.X_VERIFICATION_REQUIRED_ERROR)) as scrape,
            patch.object(kol, "rescan_page_render_failures") as rescan,
            self.assertRaisesRegex(RuntimeError, kol.X_VERIFICATION_REQUIRED_ERROR),
        ):
            self.scan_cloud(playwright, search_fallback=True)
        scrape.assert_called_once()
        rescan.assert_not_called()
        playwright.chromium.launch.assert_called_once()
        playwright.chromium.launch.return_value.close.assert_called_once()

    def test_search_challenge_is_not_swallowed_as_empty_result(self):
        with (
            patch.object(kol, "scrape_handle_url", side_effect=[None, RuntimeError(kol.X_VERIFICATION_REQUIRED_ERROR)]),
            self.assertRaisesRegex(RuntimeError, kol.X_VERIFICATION_REQUIRED_ERROR),
        ):
            kol.scrape_handle(MagicMock(), "@first", 24, 8, 2, 2500, 900, True, {})

    def test_planned_search_challenge_stops_remaining_searches(self):
        playwright = MagicMock()
        with (
            patch.object(kol, "wait_for_x_page_ready"),
            patch.object(kol, "ensure_x_page_healthy"),
            patch.object(kol, "scrape_handle", return_value=[]),
            patch.object(kol, "scrape_handle_search_fallback", side_effect=RuntimeError(kol.X_VERIFICATION_REQUIRED_ERROR)) as search,
            patch.object(kol, "rescan_page_render_failures") as rescan,
            self.assertRaisesRegex(RuntimeError, kol.X_VERIFICATION_REQUIRED_ERROR),
        ):
            self.scan_cloud(playwright, search_fallback=True)
        search.assert_called_once()
        rescan.assert_not_called()

    def test_recovery_home_challenge_closes_context_and_stops(self):
        browser = MagicMock()
        page = browser.new_context.return_value.new_page.return_value
        page.goto.return_value = challenged_response(page)
        pending = [{"status": "error", "error": kol.PAGE_RENDER_ERROR, "diagnostics": {}}]
        budget = kol.RecoveryBudget(90)
        with (
            redirect_stderr(io.StringIO()),
            patch.object(kol, "scrape_handle") as scrape,
            self.assertRaisesRegex(RuntimeError, kol.X_VERIFICATION_REQUIRED_ERROR),
        ):
            kol.rescan_page_render_failures(browser, [], pending, 24, 8, 2500, 900, budget)
        scrape.assert_not_called()
        browser.new_context.return_value.close.assert_called_once()

    def test_recovery_profile_challenge_stops_other_retries(self):
        browser = MagicMock()
        pending = [
            {**row, "status": "error", "error": kol.PAGE_RENDER_ERROR, "diagnostics": {}}
            for row in self.rows
        ]
        with (
            redirect_stderr(io.StringIO()),
            patch.object(kol, "navigate_x_page"),
            patch.object(kol, "recovery_wait_for_timeout"),
            patch.object(kol, "ensure_x_page_healthy"),
            patch.object(kol, "scrape_handle", side_effect=RuntimeError(kol.X_VERIFICATION_REQUIRED_ERROR)) as scrape,
            self.assertRaisesRegex(RuntimeError, kol.X_VERIFICATION_REQUIRED_ERROR),
        ):
            kol.rescan_page_render_failures(
                browser, [], pending, 24, 8, 2500, 900, kol.RecoveryBudget(90),
            )
        scrape.assert_called_once()
        browser.new_context.return_value.close.assert_called_once()

    def test_generic_page_failures_keep_deferred_recovery(self):
        playwright = MagicMock()
        with (
            patch.object(kol, "wait_for_x_page_ready"),
            patch.object(kol, "ensure_x_page_healthy"),
            patch.object(kol, "scrape_handle", side_effect=RuntimeError(kol.PAGE_RENDER_ERROR)),
            patch.object(kol, "RecoveryBudget") as budget,
            patch.object(kol, "rescan_page_render_failures") as rescan,
        ):
            budget.return_value.remaining_seconds = 30.0
            budget.return_value.spent_seconds = 60.0
            budget.return_value.limit_seconds = 90.0
            self.scan_cloud(playwright, search_fallback=False)
        budget.return_value.sleep.assert_called_once_with(kol.RECOVERY_QUIET_SECONDS)
        rescan.assert_called_once()
        self.assertEqual(playwright.chromium.launch.call_count, 2)

    def test_failed_scan_never_writes_cache_or_sends_telegram(self):
        for send_mode in ("--send", "--no-send"):
            with (
                self.subTest(send_mode=send_mode),
                patch.object(kol.sys, "argv", ["x_kol_daily.py", send_mode]),
                patch.object(kol, "load_dotenv"),
                patch.object(kol, "parse_kols", return_value=self.rows),
                patch.object(kol, "apply_handle_aliases", side_effect=lambda rows: rows),
                patch.object(kol, "apply_unavailable_recheck_policy", side_effect=lambda rows, **kwargs: rows),
                patch.object(kol, "REPORT_DIR"),
                patch.object(kol, "STATE_DIR"),
                patch.object(kol, "scrape_all", side_effect=RuntimeError(kol.X_VERIFICATION_REQUIRED_ERROR)),
                patch.object(kol, "update_kol_status") as statuses,
                patch.object(kol, "update_tweet_store") as cache,
                patch.object(kol, "telegram_send_reports_once") as telegram,
                self.assertRaisesRegex(RuntimeError, kol.X_VERIFICATION_REQUIRED_ERROR),
            ):
                kol.main()
            statuses.assert_not_called()
            cache.assert_not_called()
            telegram.assert_not_called()

    def test_rename_probe_does_not_hide_challenge(self):
        with (
            patch.object(kol, "cached_status_ids", return_value=["1", "2"]),
            patch.object(kol, "navigate_x_page", side_effect=RuntimeError(kol.X_VERIFICATION_REQUIRED_ERROR)) as navigate,
            self.assertRaisesRegex(RuntimeError, kol.X_VERIFICATION_REQUIRED_ERROR),
        ):
            kol.recover_renamed_handle(MagicMock(), "@first", 2500)
        navigate.assert_called_once()

    def test_verification_is_not_recoverable(self):
        self.assertNotIn(kol.X_VERIFICATION_REQUIRED_ERROR, kol.RECOVERABLE_X_PAGE_ERRORS)
        self.assertIn(kol.PAGE_RENDER_ERROR, kol.RECOVERABLE_X_PAGE_ERRORS)


if __name__ == "__main__":
    unittest.main()
