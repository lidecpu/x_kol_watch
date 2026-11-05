import io
import json
import os
import tempfile
import unittest
from copy import deepcopy
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

import x_kol_daily as kol


class ScanInterruptionTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            {"name": "first", "handle": "@first", "note": ""},
            {"name": "second", "handle": "@second", "note": ""},
            {"name": "third", "handle": "@third", "note": ""},
            {"name": "fourth", "handle": "@fourth", "note": ""},
        ]
        self.tweet = {
            "handle": "@first",
            "url": "https://x.com/first/status/123",
            "text": "A public market update",
            "created_at": "2026-11-06T03:00:00Z",
            "created_at_ms": 1793934000000,
        }
        self.playwright = MagicMock()
        self.browser = self.playwright.chromium.launch.return_value
        self.output = io.StringIO()

    def cloud(self, scrape, rows=None, search=None):
        stack = ExitStack()
        self.addCleanup(stack.close)
        factory = stack.enter_context(patch("playwright.sync_api.sync_playwright"))
        factory.return_value.__enter__.return_value = self.playwright
        stack.enter_context(patch.object(kol, "cookies_from_env", return_value=[]))
        stack.enter_context(patch.object(kol, "cleanup_chromium_debug_log"))
        stack.enter_context(patch.object(kol, "wait_for_x_page_ready"))
        stack.enter_context(patch.object(kol, "ensure_x_page_healthy"))
        stack.enter_context(patch.object(kol, "rescan_page_render_failures"))
        budget = stack.enter_context(patch.object(kol, "RecoveryBudget"))
        budget.return_value.remaining_seconds = 180.0
        budget.return_value.spent_seconds = 0.0
        budget.return_value.limit_seconds = 180.0
        self.fallback_budget = budget.return_value
        stack.enter_context(patch.object(kol, "scrape_handle", side_effect=scrape))
        if search is not None:
            stack.enter_context(
                patch.object(kol, "scrape_handle_search_fallback", side_effect=search)
            )
        stack.enter_context(redirect_stderr(self.output))
        stack.enter_context(redirect_stdout(self.output))
        return self.rows if rows is None else rows

    def scan(self, rows, search=False):
        return kol.scrape_all(rows, 24, 8, 2, True, 2500, 900, search)

    def challenge_after_success(self, page, handle, *args):
        if handle == "@first":
            return [self.tweet]
        args[-1]["page_health"] = {
            "phase": "profile",
            "verification_required": True,
            "cloudflare_challenge": True,
            "challenge_source": "response_header",
            "http_status": 403,
            "text_sample": "private-auth-value private-ct0-value",
            "cookies": {"auth_token": "private-auth-value"},
        }
        raise RuntimeError(kol.X_VERIFICATION_REQUIRED_ERROR)

    def test_challenge_preserves_completed_tweets_and_stop_evidence(self):
        rows = self.cloud(self.challenge_after_success)
        with self.assertRaisesRegex(RuntimeError, kol.X_VERIFICATION_REQUIRED_ERROR) as failure:
            self.scan(rows)
        self.assertTrue(
            hasattr(failure.exception, "results"),
            "interruption must carry completed results instead of discarding them",
        )
        self.assertEqual(failure.exception.results[0]["tweets"], [self.tweet])
        self.assertEqual(failure.exception.handle, "@second")
        self.assertEqual(failure.exception.phase, "profile")
        self.assertEqual(
            failure.exception.diagnostics["page_health"]["http_status"], 403,
        )
        self.assertEqual(self.playwright.chromium.launch.call_count, 1)

    def test_cloud_cleanup_failure_cannot_replace_interruption_or_expose_details(self):
        for resource in (self.browser.new_context.return_value, self.browser):
            with self.subTest(resource="browser" if resource is self.browser else "context"):
                rows = self.cloud(self.challenge_after_success)
                with (
                    patch.object(resource, "close", side_effect=RuntimeError("private cleanup details")),
                    self.assertRaises(kol.XScanInterrupted) as failure,
                ):
                    self.scan(rows)
                self.assertEqual(str(failure.exception), kol.X_VERIFICATION_REQUIRED_ERROR)
                self.assertEqual(failure.exception.results[0]["tweets"], [self.tweet])
                self.assertNotIn("private cleanup details", self.output.getvalue())

    def test_cleanup_failure_on_otherwise_successful_scan_is_not_hidden(self):
        rows = self.cloud([[self.tweet]], self.rows[:1])
        with (
            patch.object(self.browser, "close", side_effect=RuntimeError("cleanup failed")),
            self.assertRaisesRegex(RuntimeError, "cleanup failed"),
        ):
            self.scan(rows)

    def test_isolated_render_failure_is_classified_before_context_cleanup(self):
        rows = self.cloud([
            RuntimeError(kol.PAGE_RENDER_ERROR), [self.tweet],
        ], self.rows[:2])
        with (
            patch.object(
                self.browser.new_context.return_value, "close",
                side_effect=RuntimeError("private cleanup details"),
            ),
            self.assertRaises(kol.XScanInterrupted) as failure,
        ):
            self.scan(rows)
        self.assertEqual(str(failure.exception), kol.PAGE_RENDER_ERROR)
        self.assertEqual(failure.exception.handle, "@first")
        self.assertEqual(failure.exception.results[1]["tweets"], [self.tweet])
        self.assertNotIn("private cleanup details", self.output.getvalue())

    def test_consecutive_page_failures_stop_without_restarting_browser(self):
        rows = self.cloud([
            [self.tweet],
            RuntimeError(kol.PAGE_RENDER_ERROR),
            RuntimeError(kol.PAGE_RENDER_ERROR),
            AssertionError("must not visit the fourth account"),
        ])
        with self.assertRaisesRegex(RuntimeError, kol.GLOBAL_PAGE_DEFERRED_ERROR):
            self.scan(rows)
        self.assertEqual(self.playwright.chromium.launch.call_count, 1)

    def test_rate_limit_and_authentication_stop_before_next_account(self):
        for reason in (kol.X_RATE_LIMIT_ERROR, kol.X_AUTHENTICATION_REQUIRED_ERROR):
            with self.subTest(reason=reason):
                rows = self.cloud([
                    RuntimeError(reason),
                    AssertionError("must not continue after an access restriction"),
                ], self.rows[:2])
                with self.assertRaisesRegex(RuntimeError, reason):
                    self.scan(rows)

    def test_isolated_render_failure_is_not_retried_in_a_new_browser(self):
        rows = self.cloud([
            RuntimeError(kol.PAGE_RENDER_ERROR), [self.tweet],
        ], self.rows[:2])
        with self.assertRaisesRegex(RuntimeError, kol.PAGE_RENDER_ERROR):
            self.scan(rows)
        self.assertEqual(self.playwright.chromium.launch.call_count, 1)

    def test_search_challenge_keeps_profile_results_and_phase(self):
        def search(page, handle, *args):
            args[-2]["page_health"] = {
                "cloudflare_challenge": True,
                "challenge_source": "response_header",
                "http_status": 403,
            }
            raise RuntimeError(kol.X_VERIFICATION_REQUIRED_ERROR)

        rows = self.cloud([[], []], self.rows[:2], search)
        with self.assertRaisesRegex(RuntimeError, kol.X_VERIFICATION_REQUIRED_ERROR) as failure:
            self.scan(rows, search=True)
        self.assertTrue(hasattr(failure.exception, "results"))
        self.assertEqual(len(failure.exception.results), 2)
        self.assertEqual(failure.exception.phase, "search_fallback")

    def test_search_render_failure_at_budget_end_still_interrupts(self):
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        for error in (RuntimeError(kol.PAGE_RENDER_ERROR), PlaywrightTimeoutError("timeout")):
            with self.subTest(error=type(error).__name__):
                def search(*args):
                    self.fallback_budget.remaining_seconds = 0.5
                    raise error

                rows = self.cloud([[], []], self.rows[:2], search)
                with self.assertRaises(kol.XScanInterrupted) as failure:
                    self.scan(rows, search=True)
                self.assertEqual(str(failure.exception), kol.PAGE_RENDER_ERROR)
                self.assertEqual(failure.exception.phase, "search_fallback")
                self.assertEqual(len(failure.exception.results), 2)

    def test_normal_search_budget_exhaustion_keeps_successful_profiles(self):
        def search(*args):
            self.fallback_budget.remaining_seconds = 0.5
            raise kol.RecoveryBudgetExceeded("X recovery budget exhausted")

        rows = self.cloud([[], []], self.rows[:2], search)
        results, _ = self.scan(rows, search=True)
        self.assertEqual([item["status"] for item in results], ["ok", "ok"])
        self.assertTrue(any(
            item["diagnostics"].get("search_fallback_budget_exhausted")
            for item in results
        ))

    def test_global_breaker_snapshot_does_not_count_unvisited_profiles_as_failures(self):
        rows = self.cloud([
            [self.tweet],
            RuntimeError(kol.PAGE_RENDER_ERROR),
            RuntimeError(kol.PAGE_RENDER_ERROR),
        ])
        with self.assertRaises(kol.XScanInterrupted) as failure:
            self.scan(rows)
        with tempfile.TemporaryDirectory() as directory, patch.object(kol, "STATE_DIR", Path(directory)):
            path = kol.save_interrupted_x_scan(failure.exception, rows, 24)
            saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(saved["summary"], {
            "planned": 4, "success": 1, "failed": 2, "paused": 0, "unprocessed": 1,
        })
        self.assertEqual(saved["unprocessed_handles"], ["@fourth"])
        self.assertEqual([row["handle"] for row in saved["results"]], [
            "@first", "@second", "@third",
        ])

    def test_home_interruption_snapshot_lists_all_profiles_as_unprocessed(self):
        interruption = kol.XScanInterrupted(
            kol.X_RATE_LIMIT_ERROR, [], phase="home",
            diagnostics={"page_health": {"http_status": 429}},
        )
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(kol, "STATE_DIR", Path(directory)),
            redirect_stderr(self.output),
        ):
            path = kol.save_interrupted_x_scan(interruption, self.rows, 24)
            saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(saved["results"], [])
        self.assertEqual(saved["summary"], {
            "planned": 4, "success": 0, "failed": 0, "paused": 0, "unprocessed": 4,
        })
        self.assertEqual(saved["unprocessed_handles"], [
            "@first", "@second", "@third", "@fourth",
        ])
        self.assertEqual(saved["stop"]["reason"], "rate_limit")

    def test_snapshot_redacts_secrets_without_mutating_results_or_alias_identity(self):
        result = {
            "name": "first", "handle": "@renamed", "configured_handle": "@first",
            "status": "ok", "error": "", "tweets": [
                {**self.tweet, "text": "private-auth-value private-ct0-value"},
            ],
            "diagnostics": {"page_health": {
                "phase": "search_fallback", "http_status": 429,
                "text_sample": "private-auth-value", "title": "private title",
            }},
        }
        original = deepcopy(result)
        interruption = kol.XScanInterrupted(
            kol.X_RATE_LIMIT_ERROR, [result], phase="search_fallback", handle="@renamed",
            diagnostics=result["diagnostics"],
        )
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(kol, "STATE_DIR", Path(directory)),
            patch.dict(os.environ, {"X_AUTH": "private-auth-value", "X_CT0": "private-ct0-value"}),
            redirect_stderr(self.output),
        ):
            path = kol.save_interrupted_x_scan(interruption, self.rows, 24)
            text = path.read_text(encoding="utf-8")
            saved = json.loads(text)
        self.assertEqual(result, original)
        self.assertEqual(saved["summary"]["failed"], 1)
        self.assertEqual(saved["results"][0]["status"], "interrupted")
        self.assertEqual(saved["results"][0]["tweets"][0]["text"], "[REDACTED] [REDACTED]")
        self.assertEqual(saved["unprocessed_handles"], ["@second", "@third", "@fourth"])
        self.assertNotIn("text_sample", text)
        self.assertNotIn("private title", text)

    def test_write_failure_preserves_original_interruption_and_no_send(self):
        interruption = kol.XScanInterrupted(
            kol.X_VERIFICATION_REQUIRED_ERROR, [], phase="home",
        )
        with (
            patch.object(kol.sys, "argv", ["x_kol_daily.py", "--send"]),
            patch.object(kol, "load_dotenv"),
            patch.object(kol, "parse_kols", return_value=self.rows),
            patch.object(kol, "apply_handle_aliases", side_effect=lambda rows: rows),
            patch.object(kol, "apply_unavailable_recheck_policy", side_effect=lambda rows, **kwargs: rows),
            patch.object(kol, "REPORT_DIR"),
            patch.object(kol, "STATE_DIR"),
            patch.object(kol, "scrape_all", side_effect=interruption),
            patch.object(kol, "save_json", side_effect=PermissionError("private filesystem details")),
            patch.object(kol, "update_tweet_store") as cache,
            patch.object(kol, "update_kol_status") as statuses,
            patch.object(kol, "telegram_send_reports_once") as telegram,
            redirect_stderr(self.output),
            self.assertRaises(kol.XScanInterrupted) as failure,
        ):
            kol.main()
        self.assertIs(failure.exception, interruption)
        self.assertIn("write failed: PermissionError", self.output.getvalue())
        self.assertNotIn("private filesystem details", self.output.getvalue())
        cache.assert_not_called()
        statuses.assert_not_called()
        telegram.assert_not_called()

    def test_main_writes_separate_incomplete_diagnostic_without_cache_or_send(self):
        rows = self.cloud(self.challenge_after_success)
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            state = root / "state"
            reports = root / "reports"
            state.mkdir()
            reports.mkdir()
            normal_state = state / "20261106.json"
            normal_report = reports / "20261106.md"
            normal_state.write_text('{"previous": true}', encoding="utf-8")
            normal_report.write_text("previous report", encoding="utf-8")
            stack.enter_context(patch.dict(os.environ, {
                "X_AUTH": "private-auth-value", "X_CT0": "private-ct0-value",
            }))
            stack.enter_context(patch.object(kol.sys, "argv", ["x_kol_daily.py", "--send"]))
            stack.enter_context(patch.object(kol, "load_dotenv"))
            stack.enter_context(patch.object(kol, "parse_kols", return_value=rows))
            stack.enter_context(patch.object(kol, "apply_handle_aliases", side_effect=lambda value: value))
            stack.enter_context(patch.object(kol, "apply_unavailable_recheck_policy", side_effect=lambda value, **kwargs: value))
            stack.enter_context(patch.object(kol, "STATE_DIR", state))
            stack.enter_context(patch.object(kol, "REPORT_DIR", reports))
            statuses = stack.enter_context(patch.object(kol, "update_kol_status"))
            cache = stack.enter_context(patch.object(kol, "update_tweet_store"))
            telegram = stack.enter_context(patch.object(kol, "telegram_send_reports_once"))
            with self.assertRaisesRegex(RuntimeError, kol.X_VERIFICATION_REQUIRED_ERROR):
                kol.main()
            files = list(state.glob("x-scan-incomplete-*.json"))
            self.assertEqual(len(files), 1, "failed scans need a separate diagnostic artifact")
            text = files[0].read_text(encoding="utf-8")
            saved = json.loads(text)
            self.assertFalse(saved["complete"])
            self.assertEqual(saved["stop"]["reason"], "cloudflare_challenge")
            self.assertEqual(saved["stop"]["handle"], "@second")
            self.assertEqual(saved["stop"]["page_health"]["http_status"], 403)
            self.assertEqual(saved["results"][0]["tweets"], [self.tweet])
            self.assertEqual(saved["unprocessed_handles"], ["@third", "@fourth"])
            self.assertEqual(saved["summary"]["success"], 1)
            self.assertNotIn("private-auth-value", text + self.output.getvalue())
            self.assertNotIn("private-ct0-value", text + self.output.getvalue())
            self.assertNotIn("text_sample", text)
            self.assertNotIn("cookies", text)
            self.assertEqual(normal_state.read_text(encoding="utf-8"), '{"previous": true}')
            self.assertEqual(normal_report.read_text(encoding="utf-8"), "previous report")
            statuses.assert_not_called()
            cache.assert_not_called()
            telegram.assert_not_called()


class RateLimitNavigationTests(unittest.TestCase):
    def test_document_429_is_preserved_when_navigation_raises(self):
        page = MagicMock()
        response = MagicMock()
        response.request.resource_type = "document"
        response.frame = page.main_frame
        response.status = 429
        response.header_value.return_value = None

        def navigate(*args, **kwargs):
            page.on.call_args.args[1](response)
            raise RuntimeError("net::ERR_HTTP_RESPONSE_CODE_FAILURE")

        page.goto.side_effect = navigate
        diagnostics = {}
        with self.assertRaisesRegex(RuntimeError, kol.X_RATE_LIMIT_ERROR):
            kol.navigate_x_page(page, "https://x.com/first", diagnostics, "profile")
        self.assertEqual(diagnostics["page_health"]["http_status"], 429)
        page.remove_listener.assert_called_once()

    def test_document_429_stops_before_render_or_retry(self):
        page = MagicMock()
        response = MagicMock()
        response.request.resource_type = "document"
        response.frame = page.main_frame
        response.status = 429
        response.header_value.return_value = None
        page.goto.return_value = response
        diagnostics = {}
        with self.assertRaisesRegex(RuntimeError, kol.X_RATE_LIMIT_ERROR):
            kol.navigate_x_page(page, "https://x.com/first", diagnostics, "profile")
        self.assertEqual(diagnostics["page_health"]["http_status"], 429)
        self.assertFalse(diagnostics["page_health"]["cloudflare_challenge"])
        page.reload.assert_not_called()
        page.wait_for_timeout.assert_not_called()


if __name__ == "__main__":
    unittest.main()
