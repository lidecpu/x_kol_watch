import io
import json
import os
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import MagicMock, patch

import x_kol_daily as kol


NOW = kol.dt.datetime(2026, 1, 3, 12, tzinfo=kol.dt.timezone.utc)
ENV = {
    "CLOUDFLARE_ACCOUNT_ID": "0" * 32,
    "CLOUDFLARE_BROWSER_API_TOKEN": "test-browser-token",
    "X_AUTH": "test-auth",
    "X_CT0": "test-ct0",
}
KOLS = [
    {"name": "first", "handle": "@first", "note": ""},
    {"name": "second", "handle": "@second", "note": ""},
]


def article(handle="first", stamp="2026-01-03T10:00:00Z", text="public body", tail=""):
    return (
        f'<article><a href="/{handle}/status/123">'
        f'<time datetime="{stamp}">2h</time></a>'
        f'<div data-testid="tweetText">{text}</div>{tail}</article>'
    )


def snapshot(html, handle="@first"):
    parser = kol.CloudflareTweetParser(handle)
    parser.feed(html)
    return parser.snapshot(24, NOW)


def response(html, **meta):
    data = {
        "success": True,
        "result": html,
        "meta": {"status": 200, "headers": {}, "finalUrl": "https://x.com/first", **meta},
    }
    result = MagicMock()
    result.status = 200
    result.headers = {"X-Browser-Ms-Used": "1000.5"}
    result.read.return_value = json.dumps(data).encode()
    result.__enter__.return_value = result
    return result


def snowflake_id(created):
    milliseconds = (created - kol.dt.datetime(1970, 1, 1, tzinfo=kol.dt.timezone.utc)) // kol.dt.timedelta(milliseconds=1)
    return str((milliseconds - 1288834974657) << 22 | 17)


def alternate_article(created=NOW - kol.dt.timedelta(hours=2), handle="first", text="public body"):
    return (
        f'<article><a href="/{handle}/status/{snowflake_id(created)}">2h</a>'
        f'<div class="text-primary whitespace-pre-wrap">{text}</div></article>'
    )


class SnowflakeTimeTests(unittest.TestCase):
    def test_official_source_example_matches_observed_detail_date(self):
        created = kol.x_snowflake_created_at(
            "https://x.com/jackli727/status/2108528776762327538",
            kol.dt.datetime(2026, 10, 10, tzinfo=kol.dt.timezone.utc),
        )
        self.assertEqual(created.isoformat(), "2026-10-09T12:03:29.607000+00:00")

    def test_exact_milliseconds_survive_integer_decoding(self):
        created = NOW - kol.dt.timedelta(hours=1, milliseconds=123)
        self.assertEqual(
            kol.x_snowflake_created_at(f"https://x.com/first/status/{snowflake_id(created)}", NOW),
            created,
        )

    def test_invalid_hosts_ids_urls_and_future_times_fail_closed(self):
        identifier = snowflake_id(NOW)
        for url in (
            f"https://example.com/first/status/{identifier}",
            f"https://x.com.evil.example/first/status/{identifier}",
            f"http://x.com/first/status/{identifier}",
            f"https://user:secret@x.com/first/status/{identifier}",
            f"https://x.com:443/first/status/{identifier}",
            f"https://x.com/first/status/{identifier}?private=value",
            f"https://x.com/first/status/{identifier}#fragment",
            "https://x.com/first/status/123",
            "https://x.com/first/status/9223372036854775808",
            "https://x.com/first/status/not-a-number",
            "https://[invalid/first/status/123",
            f"https://x.com/first/status/{snowflake_id(NOW + kol.dt.timedelta(milliseconds=1))}",
        ):
            with self.subTest(url=url):
                self.assertIsNone(kol.x_snowflake_created_at(url, NOW))


class CloudflareParserTests(unittest.TestCase):
    def test_exact_time_can_be_parsed_but_snapshot_is_not_a_full_scan(self):
        result = snapshot(article())
        self.assertEqual(result["status"], "snapshot_ok")
        self.assertEqual(result["parsed_tweets"], 1)
        self.assertEqual(result["coverage"], "snapshot_recent_visible")
        self.assertNotIn("tweets", result)

    def test_strict_cutoff_and_deduplication(self):
        html = (
            article(stamp="2026-01-02T12:00:00Z") * 2
            + article(stamp="2026-01-02T11:59:59Z")
        )
        self.assertEqual(snapshot(html)["parsed_tweets"], 1)

    def test_naive_invalid_future_and_relative_times_fail_closed(self):
        for stamp in ("", "10h", "Jan 3", "2026-01-03T10:00:00", "2026-01-04T00:00:00Z"):
            with self.subTest(stamp=stamp):
                result = snapshot(article(stamp=stamp))
                self.assertEqual(result["error"], "timestamp_missing")
                self.assertEqual(result["missing_timestamps"], 1)

    def test_alternate_body_is_recognized_without_inventing_time(self):
        html = (
            '<article><a href="/first/status/123">10h</a>'
            '<div class="text-primary whitespace-pre-wrap wrap-break-word">'
            '<span>public body</span></div></article>'
        )
        result = snapshot(html)
        self.assertEqual(result["page_format"], "alternate")
        self.assertEqual(result["matching_articles"], 1)
        self.assertEqual(result["error"], "timestamp_missing")
        self.assertEqual(result["parsed_tweets"], 0)

    def test_alternate_body_decodes_exact_time_and_reports_provenance(self):
        result = snapshot(alternate_article())
        self.assertEqual(result["status"], "snapshot_ok")
        self.assertEqual(result["parsed_tweets"], 1)
        self.assertEqual(result["timestamp_sources"], {"x_snowflake": 1})
        self.assertEqual(result["recent_created_at_utc"], ["2026-01-03T10:00:00.000+00:00"])
        self.assertEqual(result["coverage"], "snapshot_recent_visible")

    def test_snowflake_cutoff_is_exact_to_the_millisecond(self):
        result = snapshot(
            alternate_article(NOW - kol.dt.timedelta(hours=24))
            + alternate_article(NOW - kol.dt.timedelta(hours=24, milliseconds=1))
        )
        self.assertEqual(result["parsed_tweets"], 1)

    def test_invalid_dom_timestamp_is_not_replaced_by_snowflake(self):
        html = alternate_article().replace(
            ">2h</a>", '><time datetime="invalid">2h</time></a>',
        )
        self.assertEqual(snapshot(html)["error"], "timestamp_missing")

    def test_standard_dom_remains_the_preferred_source(self):
        result = snapshot(article())
        self.assertEqual(result["timestamp_sources"], {"dom_datetime": 1})

    def test_snowflake_does_not_hide_recent_truncated_body(self):
        result = snapshot(alternate_article(text="partial <button>Show more</button>"))
        self.assertEqual(result["error"], "text_truncated")
        self.assertEqual(result["parsed_tweets"], 0)
        self.assertEqual(result["timestamp_sources"], {"x_snowflake": 1})

    def test_invalid_link_authority_is_not_normalized_into_valid_snowflake(self):
        for authority in ("user:secret@x.com", "x.com:443", "x.com.evil.example", "[invalid"):
            with self.subTest(authority=authority):
                html = alternate_article().replace('href="/', f'href="https://{authority}/')
                self.assertEqual(snapshot(html)["error"], "profile_not_verified")

    def test_quote_time_cannot_supply_the_author_time(self):
        html = (
            '<article><a href="/first/status/123">10h</a>'
            '<div data-testid="tweetText">author body</div>'
            '<a href="/other/status/456"><time datetime="2026-01-03T10:00:00Z">2h</time></a>'
            '<div data-testid="tweetText">quote body</div></article>'
        )
        self.assertEqual(snapshot(html)["error"], "timestamp_missing")

    def test_other_authors_do_not_exclude_the_entire_kol(self):
        result = snapshot(article("other", stamp="") + article())
        self.assertEqual(result["status"], "snapshot_ok")
        self.assertEqual(result["matching_articles"], 1)
        self.assertEqual(result["parsed_tweets"], 1)

    def test_nested_quote_does_not_supply_missing_body(self):
        html = (
            '<article><a href="/first/status/123">'
            '<time datetime="2026-01-03T10:00:00Z">2h</time></a>'
            + article("other") + "</article>"
        )
        self.assertEqual(snapshot(html)["error"], "body_missing")

    def test_non_nested_quote_does_not_supply_missing_body(self):
        html = (
            '<article><a href="/first/status/123">'
            '<time datetime="2026-01-03T10:00:00Z">2h</time></a>'
            '<a href="/other/status/456">quote author</a>'
            '<div data-testid="tweetText">quote body</div></article>'
        )
        self.assertEqual(snapshot(html)["error"], "body_missing")

    def test_show_more_does_not_count_as_complete_body(self):
        for button in (
            "<button>Show more</button>",
            '<button data-testid="tweet-text-show-more-link">more</button>',
        ):
            with self.subTest(button=button):
                result = snapshot(article(text="partial " + button))
                self.assertEqual(result["error"], "text_truncated")
                self.assertEqual(result["parsed_tweets"], 0)

    def test_missing_body_and_unknown_page_are_errors_not_no_recent(self):
        self.assertEqual(snapshot(article(text=""))["error"], "body_missing")
        self.assertEqual(snapshot("<main>empty</main>")["error"], "profile_not_verified")

    def test_missing_time_still_reports_body_truncation(self):
        result = snapshot(article(stamp="", text="partial <button>Show more</button>"))
        self.assertEqual(result["error"], "timestamp_missing")
        self.assertEqual(result["truncated_tweets"], 1)

    def test_old_truncated_tweet_does_not_block_valid_snapshot(self):
        result = snapshot(article(
            stamp="2020-01-01T00:00:00Z", text="partial <button>Show more</button>",
        ))
        self.assertEqual(result["status"], "snapshot_ok")
        self.assertEqual(result["parsed_tweets"], 0)
        self.assertEqual(result["coverage"], "snapshot_no_recent_visible")

    def test_title_challenge_does_not_become_an_empty_success(self):
        result = snapshot("<title>Just a moment...</title>" + article())
        self.assertEqual(result["error"], "verification_required")

    def test_order_and_visibility_distinguish_no_recent_from_partial_recent(self):
        old = snapshot(article(stamp="2020-01-01T00:00:00Z"))
        recent = snapshot(alternate_article())
        self.assertEqual(old["coverage"], "snapshot_no_recent_visible")
        self.assertEqual(old["visible_order_descending"], True)
        self.assertEqual(recent["coverage"], "snapshot_recent_visible")

    def test_pinned_old_tweet_does_not_hide_recent_records_or_fake_order(self):
        result = snapshot(
            alternate_article(NOW - kol.dt.timedelta(days=90))
            + alternate_article(NOW - kol.dt.timedelta(hours=2))
            + alternate_article(NOW - kol.dt.timedelta(days=2))
        )
        self.assertFalse(result["visible_order_descending"])
        self.assertEqual(result["coverage"], "snapshot_recent_visible")
        self.assertEqual(result["parsed_tweets"], 1)
        self.assertEqual(result["visible_newest_created_at_utc"], "2026-01-03T10:00:00.000+00:00")

    def test_out_of_order_old_records_do_not_imply_ordered_no_recent(self):
        result = snapshot(
            alternate_article(NOW - kol.dt.timedelta(days=90))
            + alternate_article(NOW - kol.dt.timedelta(days=2))
        )
        self.assertFalse(result["visible_order_descending"])
        self.assertEqual(result["coverage"], "snapshot_order_unknown")

    def test_unknown_snapshot_does_not_report_descending_order(self):
        result = snapshot("<main>empty</main>")
        self.assertEqual(result["coverage"], "snapshot_error")
        self.assertFalse(result["visible_order_descending"])


class CloudflareRequestTests(unittest.TestCase):
    def run_probe(self, responses, rows=None):
        with (
            patch.dict(os.environ, ENV, clear=True),
            patch.object(kol.urllib.request, "urlopen", side_effect=responses) as opened,
            patch.object(kol.time, "sleep") as sleep,
        ):
            result = kol.cloudflare_probe(KOLS[:1] if rows is None else rows, 24)
        return result, opened, sleep

    def test_official_endpoint_headers_and_cookie_scope(self):
        result, opened, _ = self.run_probe([response(article(stamp="2020-01-01T00:00:00Z"))])
        request = opened.call_args.args[0]
        self.assertTrue(request.full_url.endswith("/browser-rendering/content?cacheTTL=0"))
        payload = json.loads(request.data)
        self.assertNotIn("cacheTTL", payload)
        self.assertEqual({cookie["domain"] for cookie in payload["cookies"]}, {".x.com"})
        self.assertEqual(request.get_header("Authorization"), "Bearer test-browser-token")
        self.assertEqual(result[0]["status"], "snapshot_ok")
        self.assertEqual(result[0]["browser_ms"], 1000.5)
        output = json.dumps(result)
        for secret in ENV.values():
            self.assertNotIn(secret, output)

    def test_challenge_login_origin_rate_and_wrong_profile_stop_remaining_requests(self):
        for meta, error in (
            ({"status": 403, "headers": {"cf-mitigated": "challenge"}}, "verification_required"),
            ({"finalUrl": "https://x.com/i/flow/login"}, "authentication_required"),
            ({"finalUrl": "https://x.com/i/jf/onboarding/web"}, "account_setup_required"),
            ({"finalUrl": "https://x.com/i/flow/signup"}, "account_setup_required"),
            ({"status": 429}, "x_rate_limit"),
            ({"status": 403}, "x_http_error"),
            ({"finalUrl": "https://example.com/first"}, "profile_not_verified"),
            ({"finalUrl": "https://x.com/other"}, "profile_not_verified"),
        ):
            with self.subTest(meta=meta):
                result, opened, sleep = self.run_probe([response(article(), **meta)], KOLS)
                self.assertEqual(result[0]["error"], error)
                opened.assert_called_once()
                sleep.assert_not_called()

    def test_unparseable_time_stops_without_retry(self):
        result, opened, sleep = self.run_probe([response(article(stamp=""))], KOLS)
        self.assertEqual(result[0]["error"], "timestamp_missing")
        opened.assert_called_once()
        sleep.assert_not_called()

    def test_successful_probes_are_paced_from_previous_response(self):
        old = "2020-01-01T00:00:00Z"
        result, opened, sleep = self.run_probe([
            response(article(stamp=old)),
            response(article("second", stamp=old), finalUrl="https://x.com/second"),
        ], KOLS)
        self.assertEqual(len(result), 2)
        self.assertEqual(opened.call_count, 2)
        sleep.assert_called_once_with(12)

    def test_429_stops_and_redacts_daily_quota_message(self):
        body = io.BytesIO(json.dumps({
            "errors": [{"message": "Daily quota limit reached; test-auth"}],
        }).encode())
        failure = urllib.error.HTTPError(
            "https://api.cloudflare.com/private", 429, "test-browser-token",
            {"Retry-After": "60"}, body,
        )
        result, opened, _ = self.run_probe([failure], KOLS)
        self.assertEqual(result[0]["error"], "cloudflare_daily_quota")
        self.assertEqual(result[0]["retry_after_seconds"], 60)
        self.assertTrue(body.closed)
        self.assertNotIn("test-auth", json.dumps(result))
        self.assertNotIn("test-browser-token", json.dumps(result))
        opened.assert_called_once()

    def test_network_error_is_redacted_and_not_retried(self):
        result, opened, _ = self.run_probe([urllib.error.URLError("test-auth test-browser-token")])
        self.assertEqual(result[0]["error"], "cloudflare_request_failed")
        self.assertNotIn("test-auth", json.dumps(result))
        opened.assert_called_once()

    def test_invalid_metadata_is_redacted(self):
        for meta in (
            {"status": "test-auth"},
            {"finalUrl": "https://[test-auth"},
        ):
            with self.subTest(meta=meta):
                result, opened, _ = self.run_probe([response(article(), **meta)])
                self.assertEqual(result[0]["error"], "cloudflare_invalid_response")
                self.assertNotIn("test-auth", json.dumps(result))
                opened.assert_called_once()

    def test_bounds_are_checked_before_credentials_or_network(self):
        for rows in ([], KOLS * 2):
            with (
                self.subTest(rows=len(rows)),
                patch.object(kol, "cookies_from_env") as cookies,
                self.assertRaises(ValueError),
            ):
                kol.cloudflare_probe(rows, 24)
            cookies.assert_not_called()

    def test_malformed_account_cache_does_not_echo_contents(self):
        path = MagicMock()
        path.exists.return_value = True
        path.read_text.return_value = '{"private":"test-auth"}'
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(kol, "ROOT") as root,
            self.assertRaisesRegex(RuntimeError, "invalid Cloudflare account cache") as failure,
        ):
            root.__truediv__.return_value = root
            root.read_text.return_value = path.read_text.return_value
            root.exists.return_value = True
            kol.cloudflare_browser_account_id()
        self.assertNotIn("test-auth", str(failure.exception))


class CloudflareCliTests(unittest.TestCase):
    def test_incompatible_modes_fail_before_loading_credentials(self):
        for arguments in (
            ["--send"],
            ["--market-only"],
            ["--cache-recent", "1"],
            ["--translate-cache"],
            ["--cdp-url", "http://localhost:9222"],
        ):
            with (
                self.subTest(arguments=arguments),
                patch.object(kol.sys, "argv", ["x_kol_daily.py", "--cloudflare-probe", "--max-kols", "1", *arguments]),
                patch.object(kol, "load_dotenv") as load,
                redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit),
            ):
                kol.main()
            load.assert_not_called()

    def test_probe_requires_an_explicit_small_selection(self):
        with (
            patch.object(kol.sys, "argv", ["x_kol_daily.py", "--cloudflare-probe"]),
            patch.object(kol, "load_dotenv") as load,
            redirect_stderr(io.StringIO()),
            self.assertRaises(SystemExit),
        ):
            kol.main()
        load.assert_not_called()

    def test_probe_cannot_write_cache_reports_or_send_telegram(self):
        with (
            patch.object(kol.sys, "argv", ["x_kol_daily.py", "--cloudflare-probe", "--max-kols", "1"]),
            patch.object(kol, "load_dotenv"),
            patch.object(kol, "parse_kols", return_value=KOLS),
            patch.object(kol, "apply_handle_aliases", side_effect=lambda rows: rows),
            patch.object(kol, "cloudflare_probe", return_value=[{"status": "error", "error": "timestamp_missing"}]),
            patch.object(kol, "apply_unavailable_recheck_policy") as policy,
            patch.object(kol, "REPORT_DIR") as reports,
            patch.object(kol, "STATE_DIR") as state,
            patch.object(kol, "scrape_all") as scan,
            patch.object(kol, "update_kol_status") as statuses,
            patch.object(kol, "update_tweet_store") as store,
            patch.object(kol, "save_json") as save,
            patch.object(kol, "telegram_send_reports_once") as telegram,
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(kol.main(), 2)
        for operation in (policy, scan, statuses, store, save, telegram):
            operation.assert_not_called()
        reports.mkdir.assert_not_called()
        state.mkdir.assert_not_called()


if __name__ == "__main__":
    unittest.main()
