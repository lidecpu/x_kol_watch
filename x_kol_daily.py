#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
KOLS_FILE = ROOT / "kols.txt"
REPORT_DIR = ROOT / "reports"
STATE_DIR = ROOT / "state"
CACHE_DIR = ROOT / "cache"
TRANSLATION_CACHE = CACHE_DIR / "translations.json"
TWEET_STORE = CACHE_DIR / "tweets.json"
SENT_STATE = CACHE_DIR / "sent.json"
TELEGRAM_MESSAGE_LIMIT = 3900
CN_TZ = dt.timezone(dt.timedelta(hours=8))


def cn_now() -> dt.datetime:
    return dt.datetime.now(CN_TZ)


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def parse_kols(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = re.sub(r"^\d+[.)]\s*", "", line)
        parts = [p.strip() for p in line.split("|")]
        handle_match = re.search(r"@([A-Za-z0-9_]{1,32})", line)
        if not handle_match:
            continue
        handle = "@" + handle_match.group(1)
        key = handle.lower()
        if key in seen:
            continue
        seen.add(key)
        name = parts[0] if parts else handle
        note = parts[2] if len(parts) >= 3 else ""
        rows.append({"name": name, "handle": handle, "note": note})
    return rows


def cookies_from_env() -> list[dict[str, Any]]:
    auth = os.environ.get("X_AUTH", "").strip()
    ct0 = os.environ.get("X_CT0", "").strip()
    if not auth or not ct0:
        raise RuntimeError("missing X_AUTH or X_CT0")
    cookies = []
    for domain in [".x.com", "x.com", ".twitter.com", "twitter.com"]:
        cookies.append({
            "name": "auth_token",
            "value": auth,
            "domain": domain,
            "path": "/",
            "httpOnly": True,
            "secure": True,
            "sameSite": "None",
        })
        cookies.append({
            "name": "ct0",
            "value": ct0,
            "domain": domain,
            "path": "/",
            "httpOnly": False,
            "secure": True,
            "sameSite": "None",
        })
    return cookies


def route_static_assets(route: Any) -> None:
    req = route.request
    if req.resource_type in {"image", "media", "font"}:
        route.abort()
        return
    route.continue_()


EXTRACT_JS = r"""
({handle, cutoffMs, maxItems}) => {
  const clean = s => (s || '').replace(/\s+/g, ' ').trim();
  const out = [];
  const seen = new Set();
  for (const art of Array.from(document.querySelectorAll('article'))) {
    const timeEl = art.querySelector('time');
    const datetime = timeEl ? timeEl.getAttribute('datetime') : '';
    const ms = datetime ? Date.parse(datetime) : NaN;
    if (!Number.isFinite(ms) || ms < cutoffMs) continue;
    const text = Array.from(art.querySelectorAll('[data-testid="tweetText"]'))
      .map(n => clean(n.innerText || n.textContent || ''))
      .filter(Boolean)
      .join('\n');
    if (!text) continue;
    let link = '';
    for (const a of Array.from(art.querySelectorAll('a[href*="/status/"]'))) {
      const href = a.getAttribute('href') || '';
      if (href.includes('/status/')) { link = href; break; }
    }
    if (link.startsWith('/')) link = 'https://x.com' + link;
    const key = link || `${handle}:${datetime}:${text.slice(0, 80)}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({
      handle,
      text,
      url: link,
      created_at: datetime,
      created_at_ms: ms
    });
  }
  out.sort((a, b) => b.created_at_ms - a.created_at_ms);
  return out.slice(0, maxItems);
}
"""


def scrape_handle(
    page: Any,
    handle: str,
    hours: int,
    limit: int,
    scrolls: int,
    page_wait_ms: int,
    scroll_wait_ms: int,
    search_fallback: bool,
) -> list[dict[str, Any]]:
    clean_handle = handle.lstrip("@")
    cutoff_ms = int((dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)).timestamp() * 1000)
    urls = [
        f"https://x.com/{urllib.parse.quote(clean_handle)}",
        "https://x.com/search?" + urllib.parse.urlencode({"q": f"from:{clean_handle}", "src": "typed_query", "f": "live"}),
    ]
    if not search_fallback:
        urls = urls[:1]
    merged: dict[str, dict[str, Any]] = {}
    for url_index, url in enumerate(urls):
        if len(merged) >= limit:
            break
        page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        page.wait_for_timeout(page_wait_ms)
        for _ in range(scrolls + 1):
            rows = page.evaluate(EXTRACT_JS, {"handle": handle, "cutoffMs": cutoff_ms, "maxItems": limit * 2})
            for row in rows:
                key = str(row.get("url") or f"{handle}:{row.get('created_at')}:{row.get('text','')[:80]}")
                merged[key] = row
            if len(merged) >= limit:
                break
            page.mouse.wheel(0, 1800)
            page.wait_for_timeout(scroll_wait_ms)
    rows = sorted(merged.values(), key=lambda x: x.get("created_at_ms", 0), reverse=True)
    return rows[:limit]


def fmt_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    minutes, sec = divmod(seconds, 60)
    if minutes:
        return f"{minutes}m{sec:02d}s"
    return f"{sec}s"


def scrape_all(
    kols: list[dict[str, str]],
    hours: int,
    limit: int,
    scrolls: int,
    headless: bool,
    page_wait_ms: int,
    scroll_wait_ms: int,
    search_fallback: bool,
) -> list[dict[str, Any]]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise RuntimeError("missing playwright; run: python -m pip install playwright && python -m playwright install chromium") from exc

    cookies = cookies_from_env()
    chrome_path = os.environ.get("CHROME_PATH", "").strip() or None
    results: list[dict[str, Any]] = []
    with sync_playwright() as p:
        launch_args = ["--disable-gpu", "--no-first-run", "--no-default-browser-check"]
        launch_kwargs: dict[str, Any] = {"headless": headless, "args": launch_args}
        if chrome_path:
            launch_kwargs["executable_path"] = chrome_path
        browser = p.chromium.launch(**launch_kwargs)
        try:
            context = browser.new_context(locale="zh-CN", timezone_id="Asia/Shanghai")
            try:
                context.route("**/*", route_static_assets)
                context.add_cookies(cookies)
                page = context.new_page()
                page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=45_000)
                page.wait_for_timeout(1500)
                print(
                    f"[x-home] url={page.url} title={page.title()[:80]}",
                    file=sys.stderr,
                    flush=True,
                )
                total_kols = len(kols)
                durations: list[float] = []
                for index, kol in enumerate(kols, 1):
                    handle = kol["handle"]
                    started = time.time()
                    print(f"[scan {index}/{total_kols}] {handle} start", file=sys.stderr, flush=True)
                    try:
                        tweets = scrape_handle(page, handle, hours, limit, scrolls, page_wait_ms, scroll_wait_ms, search_fallback)
                        status = "ok"
                        error = ""
                    except Exception as exc:
                        tweets = []
                        status = "error"
                        error = f"{type(exc).__name__}: {exc}"
                    elapsed = time.time() - started
                    durations.append(elapsed)
                    avg = sum(durations) / len(durations)
                    eta = fmt_duration(avg * (total_kols - index))
                    suffix = f" error={error}" if error else ""
                    print(
                        f"[scan {index}/{total_kols}] {handle} {status} tweets={len(tweets)} {elapsed:.1f}s eta={eta}{suffix}",
                        file=sys.stderr,
                        flush=True,
                    )
                    results.append({**kol, "status": status, "error": error, "tweets": tweets})
            finally:
                context.close()
        finally:
            browser.close()
    return results


def is_mostly_english(text: str) -> bool:
    if re.search(r"[\u4e00-\u9fff]", text):
        return False
    letters = re.findall(r"[A-Za-z]", text)
    return len(letters) >= 20


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def prune_daily_outputs() -> None:
    for folder, pattern in [(REPORT_DIR, "*.md"), (STATE_DIR, "*.json")]:
        if not folder.exists():
            continue
        by_day: dict[str, list[Path]] = {}
        for path in folder.glob(pattern):
            match = re.match(r"^(\d{8})(?:-\d{6})?\.(?:md|json)$", path.name)
            if not match:
                continue
            by_day.setdefault(match.group(1), []).append(path)
        for day, paths in by_day.items():
            preferred = folder / f"{day}{Path(pattern).suffix}"
            keep = preferred if preferred in paths else max(paths, key=lambda p: p.stat().st_mtime)
            for path in paths:
                if path != keep:
                    path.unlink(missing_ok=True)


def tweet_id(tweet: dict[str, Any]) -> str:
    url = str(tweet.get("url") or "").strip()
    if "/status/" in url:
        return url.rstrip("/").split("/status/", 1)[1].split("?", 1)[0]
    seed = "|".join([
        str(tweet.get("handle") or ""),
        str(tweet.get("created_at") or ""),
        str(tweet.get("text") or "")[:160],
    ])
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def update_tweet_store(results: list[dict[str, Any]], stamp: str) -> dict[str, Any]:
    store = load_json(TWEET_STORE, {"version": 1, "tweets": {}})
    tweets = store.setdefault("tweets", {})
    now = dt.datetime.now().isoformat(timespec="seconds")
    added = 0
    updated = 0
    for item in results:
        for tw in item.get("tweets", []):
            tid = tweet_id(tw)
            existing = tweets.get(tid)
            record = {
                "id": tid,
                "handle": item.get("handle", ""),
                "name": item.get("name", ""),
                "note": item.get("note", ""),
                "created_at": tw.get("created_at", ""),
                "created_at_ms": tw.get("created_at_ms", 0),
                "text": tw.get("text", ""),
                "translation_zh": tw.get("translation_zh") or (existing or {}).get("translation_zh", ""),
                "url": tw.get("url", ""),
                "last_seen_at": now,
                "last_run": stamp,
            }
            if existing:
                record["first_seen_at"] = existing.get("first_seen_at", now)
                record["seen_count"] = int(existing.get("seen_count", 1)) + 1
                tweets[tid] = {**existing, **record}
                updated += 1
            else:
                record["first_seen_at"] = now
                record["seen_count"] = 1
                tweets[tid] = record
                added += 1
    store["updated_at"] = now
    store["total"] = len(tweets)
    store["last_run"] = stamp
    save_json(TWEET_STORE, store)
    return {"store": str(TWEET_STORE), "total": len(tweets), "added": added, "updated": updated}


def translate_tweet_store(limit: int) -> dict[str, int]:
    store = load_json(TWEET_STORE, {"version": 1, "tweets": {}})
    tweets = store.get("tweets", {})
    rows = sorted(tweets.values(), key=lambda x: x.get("created_at_ms", 0), reverse=True)
    translated = 0
    skipped = 0
    failed = 0
    for row in rows:
        if limit > 0 and translated >= limit:
            break
        text = str(row.get("text") or "")
        if row.get("translation_zh") or not is_mostly_english(text):
            skipped += 1
            continue
        try:
            row["translation_zh"] = translate_to_zh(text)
            row.pop("translation_error", None)
            translated += 1
        except Exception as exc:
            row["translation_error"] = f"{type(exc).__name__}: {exc}"
            failed += 1
    store["updated_at"] = dt.datetime.now().isoformat(timespec="seconds")
    save_json(TWEET_STORE, store)
    return {"translated": translated, "skipped": skipped, "failed": failed}


def apply_store_translations(results: list[dict[str, Any]]) -> None:
    store = load_json(TWEET_STORE, {"version": 1, "tweets": {}})
    tweets = store.get("tweets", {})
    for item in results:
        for tw in item.get("tweets", []):
            record = tweets.get(tweet_id(tw))
            if record and record.get("translation_zh"):
                tw["translation_zh"] = record["translation_zh"]


def translate_to_zh(text: str) -> str:
    cache = load_json(TRANSLATION_CACHE, {})
    key = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if key in cache:
        return str(cache[key])
    query = urllib.parse.urlencode({
        "client": "gtx",
        "sl": "auto",
        "tl": "zh-CN",
        "dt": "t",
        "q": text[:4500],
    })
    url = "https://translate.googleapis.com/translate_a/single?" + query
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    translated = "".join(part[0] for part in data[0] if part and part[0]).strip()
    cache[key] = translated
    save_json(TRANSLATION_CACHE, cache)
    time.sleep(0.2)
    return translated


def fmt_time(value: str) -> str:
    if not value:
        return ""
    try:
        d = dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(dt.timezone(dt.timedelta(hours=8)))
        return d.strftime("%m-%d %H:%M")
    except Exception:
        return value


URL_RE = re.compile(
    r"https?://\s*\S+|www\.\S+|\b(?:x\.com|twitter\.com)/\S+",
    re.IGNORECASE,
)


def clean_report_text(text: str) -> str:
    replacements = {
        "It's unwise to fade $MSTR": "不宜看空 $MSTR",
        "He's down 709K at the moment. Track this whale with Hyperbot:": "该鲸鱼目前浮亏约 70.9 万美元：",
        "Track this whale with Hyperbot:": "在 Hyperbot 追踪该鲸鱼：",
        "Address:": "地址：",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = URL_RE.sub("", text)
    text = re.sub(r"\b(?:x\.com|twitter\.com)\s*/\s*\S+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"地址[:：]\s*\S+(?:\s*…)?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bs/\d+\S*(?:\s*…)?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:y|ss|dress|ost|announcement/detail|proposal)/\S+(?:\s*…)?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\S+\?(?:activeTab|_dp|utm_|ref=)\S*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\S{48,}", "", text)
    text = re.sub(r"感谢\s+@\w+\s+作为.*?赞助商。?", "", text)
    text = re.sub(r"\b0x[0-9a-f]{10,}(?:[.#/][\w.-]+)?(?:\s*…|\s*\.\.\.)?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b[0-9a-f]{24,}(?:[.#/][\w.-]+)?(?:\s*…|\s*\.\.\.)?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b[1-9A-HJ-NP-Za-km-z]{32,}(?:[.#/][\w.-]+)?(?:\s*…|\s*\.\.\.)?", "", text)
    text = re.sub(r"\s+(?=[，。！？、；：,.!?;:])", "", text)
    text = re.sub(r"(?:\s*…|\s*\.\.\.)\s*$", "", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def shorten_text(text: str, limit: int) -> str:
    text = clean_report_text(text).replace("\n", " ")
    if limit > 0 and len(text) > limit:
        return trim_text(text, limit)
    return text


def trim_text(text: str, limit: int) -> str:
    if limit <= 0 or len(text) <= limit:
        return text
    head = text[:limit]
    min_pos = max(40, int(limit * 0.55))
    for mark in ["。", "！", "？", ". ", "! ", "? ", "；", ";", "，", ","]:
        pos = head.rfind(mark)
        if pos >= min_pos:
            return head[:pos + len(mark)].rstrip(" ，,。:：;；") + "..."
    return head.rstrip(" ，,。:：;；") + "..."


def compact_text(text: str, limit: int) -> str:
    text = clean_report_text(text).replace("\n", " ")
    text = re.sub(r"^\s*(刚刚消息|刚刚|BREAKING|JUST IN)\s*[:：]\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^\s*\d+\s*/\s*", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if limit > 0 and len(text) > limit:
        return trim_text(text, limit)
    return text


def topic_of(item: dict[str, Any]) -> str:
    blob = " ".join([
        str(item.get("name") or ""),
        str(item.get("note") or ""),
        " ".join(str(t.get("translation_zh") or t.get("text") or "") for t in item.get("tweets", [])[:3]),
    ]).lower()
    if any(k in blob for k in ["slowmist", "安全", "aml", "漏洞", "攻击", "lazarus", "drainer", "洗钱"]):
        return "安全"
    if any(k in blob for k in ["btc", "bitcoin", "eth", "sol", "行情", "止盈", "抄底", "空单", "多单", "回踩", "$"]):
        return "市场"
    if any(k in blob for k in ["openai", "ai", "google", "模型"]):
        return "AI"
    if any(k in blob for k in ["breaking", "just in", "vanguard", "spacex", "sec", "监管", "银行"]):
        return "快讯"
    return "其他"


def item_priority(item: dict[str, Any]) -> tuple[int, int]:
    topic_rank = {"市场": 0, "快讯": 1, "安全": 2, "AI": 3, "其他": 4}
    topic = topic_of(item)
    newest = max((int(t.get("created_at_ms") or 0) for t in item.get("tweets", [])), default=0)
    return (topic_rank.get(topic, 9), -newest)


def headline_text(text: str, limit: int) -> str:
    text = compact_text(text, limit=0)
    text = re.sub(r"^(消息|新闻|快讯)\s*[:：]\s*", "", text)
    parts = re.split(r"(?<=[。！？!?])\s+|[；;]\s*", text)
    text = parts[0].strip() if parts and parts[0].strip() else text
    if limit > 0 and len(text) > limit:
        return trim_text(text, limit)
    return text


def summarize_item(item: dict[str, Any], tweet_chars: int) -> str:
    tweets = item.get("tweets", [])
    heads: list[str] = []
    for tw in tweets[:2]:
        text = headline_text(str(tw.get("translation_zh") or tw.get("text") or ""), tweet_chars)
        if text and text not in heads:
            heads.append(text)
    return "；".join(heads)


def build_report(results: list[dict[str, Any]], hours: int) -> str:
    now = cn_now().strftime("%m-%d %H:%M")
    total = sum(len(x.get("tweets", [])) for x in results)
    lines = [
        f"X KOL {hours}H | {len(results)}人 | {total}条 | {now}",
        "",
    ]
    for item in results:
        tweets = item.get("tweets", [])
        if not tweets:
            continue
        lines.append(f"## {item.get('name')} {item.get('handle')}")
        for index, tw in enumerate(tweets, 1):
            body = clean_report_text(str(tw.get("translation_zh") or tw.get("text") or ""))
            if tw.get("translation_zh"):
                original = clean_report_text(str(tw.get("text", "")))
                if original:
                    body = f"{body}\n原文：{original}"
            when = fmt_time(str(tw.get("created_at", "")))
            lines.append("")
            lines.append(f"{index}. {when}")
            lines.append(body)
        lines.append("")
    if total == 0:
        lines.append("最近 24 小时没有抓到可读推文。")
    return "\n".join(lines).strip() + "\n"


def report_total(results: list[dict[str, Any]]) -> int:
    global_total = max((int(x.get("_global_total_24h") or 0) for x in results), default=0)
    if global_total:
        return global_total
    meta_total = sum(int(x.get("_total_24h") or 0) for x in results)
    if meta_total:
        return meta_total
    return sum(len(x.get("tweets", [])) for x in results)


def report_kol_count(results: list[dict[str, Any]]) -> int:
    global_count = max((int(x.get("_global_kol_24h") or 0) for x in results), default=0)
    return global_count or len([x for x in results if x.get("tweets")])


IMPORTANT_TERMS = [
    "btc", "bitcoin", "eth", "ethereum", "sol", "hype", "mstr", "strategy",
    "etf", "fed", "fomc", "降息", "加息", "资金", "流入", "流出", "储备",
    "抄底", "止盈", "回踩", "突破", "空单", "多单", "杠杆", "爆仓",
    "链上", "巨鲸", "持仓", "资金费率", "稳定币", "监管", "安全", "漏洞",
    "攻击", "洗钱", "lazarus", "drainer", "hack", "exploit", "blackrock",
    "coinbase", "whale", "钱包", "转移", "gold", "黄金", "oil", "石油",
    "伊朗", "霍尔木兹", "制裁", "openai", "ai", "模型", "cursor", "google",
]

LOW_SIGNAL_TERMS = [
    "世界杯", "阿根廷", "埃及", "就你", "朋友圈", "亏麻了", "心都要碎了",
    "不能按时完成任务", "做事方法", "马斯克说，传统媒体", "了解更多",
    "track the address", "not looking so good", "current meta",
]
HARD_LOW_SIGNAL_TERMS = [
    "下载coinbase", "做个三明治", "法律条款", "资本有风险", "交易竞赛",
    "瓜分", "抽奖", "门票", "报名成功", "活动页面", "现在申购",
    "立即开始", "交易赚币", "折价买币奖池", "观赛季", "看球",
    "女团", "德州", "竞猜区", "奖池", "赞助。有观点",
]
TOKEN_ONLY_TERMS = {
    "btc", "bitcoin", "eth", "ethereum", "sol", "hype", "mstr",
    "crypto", "比特币", "加密", "加密货币",
    "$btc", "$eth", "$sol", "$hype", "$mstr",
}
EXCLUDED_TELEGRAM_TERMS = ["slowmist", "慢雾"]
FOCUS_SOURCE_TERMS = [
    "coindesk", "coinmarketcap", "lookonchain", "spot on chain", "whale alert",
    "wublockchain", "吴说", "arkham", "nansen", "peckshield", "hyperbot",
    "ethereum foundation", "binance", "币安", "okx", "coinbase",
    "openai", "sam altman", "sundar pichai",
]
DEFAULT_FOCUS_PER_KOL = 6


def tweet_body(tweet: dict[str, Any], limit: int) -> str:
    override = str(tweet.get("_body") or "")
    if override:
        return compact_text(override, limit)
    return compact_text(str(tweet.get("translation_zh") or tweet.get("text") or ""), limit)


def tweet_time_text(tweet: dict[str, Any]) -> str:
    return fmt_time(str(tweet.get("created_at", ""))).split(" ", 1)[-1]


def row_signal_score(row: dict[str, Any]) -> int:
    tweet = row["tweet"]
    body = tweet_body(tweet, 900)
    blob = body.lower()
    score = 0
    score += sum(2 for term in IMPORTANT_TERMS if term.lower() in blob)
    score -= sum(3 for term in LOW_SIGNAL_TERMS if term.lower() in blob)
    if len(body) < 12:
        score -= 4
    if "$" in body:
        score += 2
    if str(tweet.get("_thread_count") or ""):
        score += 2
    return score


def has_important_signal(text: str) -> bool:
    blob = text.lower()
    return "$" in text or any(term.lower() in blob for term in IMPORTANT_TERMS)


def is_focus_row(row: dict[str, Any]) -> bool:
    body = tweet_body(row["tweet"], 900)
    source = f"{row.get('name', '')} {row.get('handle', '')}".lower()
    return has_important_signal(body) or any(term in source for term in FOCUS_SOURCE_TERMS) or row_signal_score(row) > 0


def is_token_only_text(text: str) -> bool:
    token_text = re.sub(r"[#＃$＄]", "", text.strip().lower())
    token_text = re.sub(r"[，,。.!！?？；;：:、/|()\[\]【】]+", " ", token_text)
    tokens = [token for token in re.split(r"\s+", token_text) if token]
    return bool(tokens) and len(tokens) <= 5 and all(token in TOKEN_ONLY_TERMS for token in tokens)


def is_low_signal_row(row: dict[str, Any]) -> bool:
    body = tweet_body(row["tweet"], 900)
    compact = re.sub(r"\s+", " ", body).strip()
    lower = compact.lower()
    if not compact:
        return True
    if is_token_only_text(compact):
        return True
    if any(term.lower() in lower for term in HARD_LOW_SIGNAL_TERMS):
        return True
    if any(term.lower() in lower for term in LOW_SIGNAL_TERMS):
        return not has_important_signal(compact)
    cjk = sum("\u4e00" <= ch <= "\u9fff" for ch in compact)
    letters = sum(ch.isascii() and ch.isalpha() for ch in compact)
    if letters >= 8 and cjk == 0 and len(compact) <= 40 and not has_important_signal(compact):
        return True
    if re.fullmatch(r"\d+\s*[-.)/]\s*[A-Za-z0-9_.-]{1,20}", compact) and not has_important_signal(compact):
        return True
    if len(compact) <= 8 and not has_important_signal(compact):
        return True
    if len(compact) <= 24 and not has_important_signal(compact) and not re.search(r"\d", compact):
        return True
    return False


def is_excluded_telegram_row(row: dict[str, Any]) -> bool:
    body = tweet_body(row["tweet"], 900).lower()
    name = str(row.get("name") or "").lower()
    handle = str(row.get("handle") or "").lower()
    blob = f"{name} {handle} {body}"
    return any(term in blob for term in EXCLUDED_TELEGRAM_TERMS)


def telegram_row_sort_key(row: dict[str, Any]) -> tuple[int, int]:
    kol_order = int(row.get("_kol_order", 999999))
    tweet_time = int(row.get("tweet", {}).get("created_at_ms") or 0)
    return (kol_order, -tweet_time)


def telegram_rows(results: list[dict[str, Any]], per_kol: int, include_low_signal: bool) -> list[dict[str, Any]]:
    active = [x for x in results if x.get("tweets")]
    effective_per_kol = per_kol
    if effective_per_kol > 1 and len(active) > 20:
        effective_per_kol = 1
    rows: list[dict[str, Any]] = []
    for kol_order, item in enumerate(active):
        tweets = item.get("tweets", [])
        name = str(item.get("name") or item.get("handle") or "").strip()
        handle = str(item.get("handle") or "").strip()
        shown = tweets[:effective_per_kol] if effective_per_kol > 0 else tweets
        for tw in shown:
            row = {"name": name, "handle": handle, "tweet": tw, "_kol_order": kol_order}
            if is_excluded_telegram_row(row):
                continue
            if include_low_signal or not is_low_signal_row(row):
                rows.append(row)
    rows.sort(key=telegram_row_sort_key)
    return rows


def merge_thread_rows(rows: list[dict[str, Any]], tweet_chars: int) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = {}
    order: list[tuple[str, str]] = []
    for row in rows:
        tweet = row["tweet"]
        key = (str(row.get("name") or ""), tweet_time_text(tweet))
        if key not in buckets:
            order.append(key)
            buckets[key] = []
        buckets[key].append(row)

    merged: list[dict[str, Any]] = []
    for key in order:
        group = buckets[key]
        if len(group) < 3:
            merged.extend(group)
            continue
        bodies = [tweet_body(row["tweet"], 160) for row in group if tweet_body(row["tweet"], 160)]
        numbered = sum(1 for body in bodies if re.match(r"^\s*\d+\s*/", body))
        same_time_thread = numbered >= 2 or len(group) >= 4
        if not same_time_thread:
            merged.extend(group)
            continue
        first = dict(group[0]["tweet"])
        parts = []
        for body in bodies[:5]:
            head = headline_text(body, max(70, tweet_chars // 2))
            if head and head not in parts:
                parts.append(head)
        first["_thread_count"] = len(group)
        first["_body"] = f"thread {len(group)}条合并：" + "；".join(parts)
        merged.append({
            "name": group[0]["name"],
            "handle": group[0].get("handle", ""),
            "tweet": first,
            "_kol_order": group[0].get("_kol_order", 999999),
        })
    merged.sort(key=telegram_row_sort_key)
    return merged


def focus_rows(rows: list[dict[str, Any]], tweet_chars: int, limit: int, per_kol: int) -> list[dict[str, Any]]:
    merged = [row for row in merge_thread_rows(rows, tweet_chars) if is_focus_row(row)]
    merged.sort(key=telegram_row_sort_key)
    if per_kol > 0:
        counts: dict[tuple[str, str], int] = {}
        capped: list[dict[str, Any]] = []
        for row in merged:
            key = (str(row.get("name") or ""), str(row.get("handle") or ""))
            if counts.get(key, 0) >= per_kol:
                continue
            counts[key] = counts.get(key, 0) + 1
            capped.append(row)
        merged = capped
    return merged[:limit] if limit > 0 else merged


def telegram_section(number: int, row: dict[str, Any], tweet_chars: int, show_name: bool = True) -> str:
    tw = row["tweet"]
    body = tweet_body(tw, tweet_chars)
    if not body:
        return ""
    when = tweet_time_text(tw)
    name = str(row.get("name") or row.get("handle") or "").strip() or "unknown"
    handle = str(row.get("handle") or "").strip()
    author = name
    if show_name and handle and handle not in author:
        author = f"{author} {handle}"
    title = f"{number}. {author} | {when}" if show_name else f"{number}. {when}"
    return "\n".join([title, body])


def telegram_kol_blocks(rows: list[dict[str, Any]], tweet_chars: int) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    number = 1
    for row in rows:
        section = telegram_section(number, row, tweet_chars, show_name=True)
        if not section:
            continue
        blocks.append({"title": "", "sections": [section], "count": 1})
        number += 1
    return blocks


def block_text(title: str, sections: list[str], continued: bool = False) -> str:
    if not title:
        return "\n\n".join(sections)
    suffix = " 续" if continued else ""
    return "\n\n".join([f"## {title}{suffix}", *sections])


def split_large_block(block: dict[str, Any], group_size: int, limit: int) -> list[dict[str, Any]]:
    title = str(block["title"])
    sections = list(block["sections"])
    max_items = group_size if group_size > 0 else len(sections)
    parts: list[dict[str, Any]] = []
    current: list[str] = []
    for section in sections:
        candidate = [*current, section]
        candidate_text = block_text(title, candidate, continued=bool(parts))
        too_many = len(candidate) > max_items
        too_long = len(candidate_text) > limit
        if current and (too_many or too_long):
            parts.append({"text": block_text(title, current, continued=bool(parts)), "count": len(current)})
            current = [section]
        else:
            current = candidate
    if current:
        parts.append({"text": block_text(title, current, continued=bool(parts)), "count": len(current)})
    return parts


def pack_telegram_blocks(blocks: list[dict[str, Any]], group_size: int, limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[list[dict[str, Any]]]:
    size_limit = max(600, limit - 180)
    max_items = group_size if group_size > 0 else sum(int(block.get("count") or 0) for block in blocks)
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_len = 0
    current_count = 0
    for block in blocks:
        if not block.get("sections"):
            continue
        title = str(block["title"])
        sections = list(block["sections"])
        sent = 0
        while sent < len(sections):
            if current_count >= max_items:
                groups.append(current)
                current = []
                current_len = 0
                current_count = 0
            room = max_items - current_count if max_items > 0 else len(sections) - sent
            take = min(room, len(sections) - sent)
            continued = sent > 0
            text = block_text(title, sections[sent:sent + take], continued=continued)
            while take > 1 and current_len + len(text) + 2 > size_limit:
                take -= 1
                text = block_text(title, sections[sent:sent + take], continued=continued)
            if current and current_len + len(text) + 2 > size_limit:
                groups.append(current)
                current = []
                current_len = 0
                current_count = 0
                continue
            current.append({"text": text, "count": take})
            current_len += len(text) + 2
            current_count += take
            sent += take
    if current:
        groups.append(current)
    return groups or [[]]


def build_telegram_reports(
    results: list[dict[str, Any]],
    hours: int,
    tweet_chars: int,
    per_kol: int,
    style: str,
    group_size: int,
    mode: str = "full",
    focus_limit: int = 0,
    focus_per_kol: int = DEFAULT_FOCUS_PER_KOL,
    include_low_signal: bool = False,
) -> list[str]:
    active = [x for x in results if x.get("tweets")]
    rows = telegram_rows(active, per_kol, include_low_signal)
    if mode == "focus":
        rows = focus_rows(rows, tweet_chars, focus_limit, focus_per_kol)
    now = cn_now().strftime("%m-%d %H:%M")
    if not rows:
        return [f"X KOL {hours}H | 活跃KOL:0/{len(results)} | 推文:0 | 本组:0 | {now}\n\n最近 24 小时没有抓到可读推文。\n"]

    blocks = telegram_kol_blocks(rows, tweet_chars)
    display_total = sum(int(block.get("count") or 0) for block in blocks)
    display_kol_count = len({
        (str(row.get("name") or "").strip(), str(row.get("handle") or "").strip())
        for row in rows
    })
    scanned_kol_count = len(results)
    kol_label = f"{display_kol_count}/{scanned_kol_count}" if scanned_kol_count else str(display_kol_count)
    groups = pack_telegram_blocks(blocks, group_size)
    reports: list[str] = []
    for group_index, group in enumerate(groups, 1):
        mode_label = "重点" if mode == "focus" else "全量"
        group_count = sum(int(part.get("count") or 0) for part in group)
        header = (
            f"X KOL {hours}H {mode_label} | 组:{group_index}/{len(groups)} | "
            f"活跃KOL:{kol_label} | 推文:{display_total} | 本组:{group_count} | {now}"
        )
        lines = [header]
        for part in group:
            lines.extend(["", str(part.get("text") or "").strip()])
        reports.append("\n".join(lines).strip() + "\n")
    return reports


def build_telegram_report(
    results: list[dict[str, Any]],
    hours: int,
    tweet_chars: int,
    per_kol: int,
    style: str,
    group_size: int = 20,
    mode: str = "full",
    focus_limit: int = 0,
    focus_per_kol: int = DEFAULT_FOCUS_PER_KOL,
    include_low_signal: bool = False,
) -> str:
    return "\n---\n\n".join(
        report.strip()
        for report in build_telegram_reports(
            results,
            hours,
            tweet_chars,
            per_kol,
            style,
            group_size,
            mode,
            focus_limit,
            focus_per_kol,
            include_low_signal,
        )
    ) + "\n"


def build_telegram_digest(results: list[dict[str, Any]], hours: int, tweet_chars: int) -> str:
    return build_telegram_report(results, hours, tweet_chars, per_kol=1, style="hermes")


def build_telegram_list(results: list[dict[str, Any]], hours: int, tweet_chars: int, per_kol: int) -> str:
    return build_telegram_report(results, hours, tweet_chars, per_kol, style="hermes")


def cached_results(limit: int, hours: int, handles: str = "") -> list[dict[str, Any]]:
    store = load_json(TWEET_STORE, {"tweets": {}})
    wanted = {"@" + x.strip().lstrip("@").lower() for x in handles.split(",") if x.strip()}
    allowed = wanted or {row["handle"].lower() for row in parse_kols(KOLS_FILE)}
    cutoff_ms = int((dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)).timestamp() * 1000)
    rows = sorted(store.get("tweets", {}).values(), key=lambda x: x.get("created_at_ms", 0), reverse=True)
    rows_24h = []
    handles_24h = set()
    for row in rows:
        if int(row.get("created_at_ms") or 0) < cutoff_ms:
            continue
        handle = str(row.get("handle") or "")
        if handle.lower() not in allowed:
            continue
        rows_24h.append(row)
        handles_24h.add(handle.lower())
    selected = rows_24h[:limit] if limit > 0 else rows_24h
    grouped: dict[str, dict[str, Any]] = {}
    for row in selected:
        handle = str(row.get("handle") or "")
        item = grouped.setdefault(handle, {
            "name": row.get("name", ""),
            "handle": handle,
            "note": row.get("note", ""),
            "_total_24h": sum(1 for x in rows_24h if str(x.get("handle") or "").lower() == handle.lower()),
            "_global_total_24h": len(rows_24h),
            "_global_kol_24h": len(handles_24h),
            "tweets": [],
        })
        item["tweets"].append(row)
    return list(grouped.values())


def split_message(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in text.splitlines():
        line_size = len(line) + 1
        if current and size + line_size > limit:
            chunks.append("\n".join(current).strip())
            current = []
            size = 0
        if line_size > limit:
            chunks.append(line[:limit - 3].rstrip() + "...")
            continue
        current.append(line)
        size += line_size
    if current:
        chunks.append("\n".join(current).strip())
    return chunks or [text]


def telegram_send(text: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise RuntimeError("missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")
    if token.startswith("TELEGRAM_BOT_TOKEN=") or token.startswith("@") or not re.fullmatch(r"\d+:[A-Za-z0-9_-]{20,}", token):
        raise RuntimeError("invalid TELEGRAM_BOT_TOKEN secret: put only the token value, not the bot name or TELEGRAM_BOT_TOKEN=...")
    if chat_id.startswith("TELEGRAM_CHAT_ID="):
        raise RuntimeError("invalid TELEGRAM_CHAT_ID secret: put only the chat id value, not TELEGRAM_CHAT_ID=...")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    chunks = split_message(text)
    for chunk in chunks:
        payload = urllib.parse.urlencode({
            "chat_id": chat_id,
            "text": chunk,
            "disable_web_page_preview": "true",
        }).encode()
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"telegram HTTP {exc.code}: check TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID secrets; response={body}") from exc
        data = json.loads(body)
        if not data.get("ok"):
            raise RuntimeError(f"telegram send failed: {body}")


def telegram_report_row_count(report: str) -> int:
    return len(re.findall(r"(?m)^\d+\.\s+", report))


def telegram_send_reports(reports: list[str]) -> dict[str, int]:
    rows = sum(telegram_report_row_count(report) for report in reports)
    for report in reports:
        telegram_send(report)
    return {"groups": len(reports), "rows": rows}


def scheduled_send_key(args: argparse.Namespace) -> str:
    if os.environ.get("GITHUB_EVENT_NAME") != "schedule":
        return ""
    return os.environ.get("X_KOL_SEND_ONCE_KEY", "").strip() or ":".join([
        cn_now().strftime("%Y%m%d"),
        f"{args.hours}h",
        args.telegram_mode,
    ])


def telegram_send_reports_once(reports: list[str], args: argparse.Namespace) -> dict[str, int]:
    key = scheduled_send_key(args)
    if not key:
        return telegram_send_reports(reports)
    state = load_json(SENT_STATE, {"version": 1, "sent": {}})
    sent = state.setdefault("sent", {})
    if key in sent:
        print(f"scheduled send skipped: already sent key={key}")
        return {"groups": 0, "rows": 0, "skipped": 1}
    stats = telegram_send_reports(reports)
    sent[key] = {
        "sent_at": cn_now().isoformat(timespec="seconds"),
        "groups": stats.get("groups", 0),
        "rows": stats.get("rows", 0),
    }
    save_json(SENT_STATE, state)
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--limit", type=int, default=8, help="max tweets per KOL")
    ap.add_argument("--max-kols", type=int, default=0, help="test only: scan first N KOLs")
    ap.add_argument("--handles", default="", help="comma-separated handles for testing, e.g. @OpenAI,@saylor")
    ap.add_argument("--scrolls", type=int, default=6)
    ap.add_argument("--page-wait-ms", type=int, default=2500)
    ap.add_argument("--scroll-wait-ms", type=int, default=900)
    ap.add_argument("--search-fallback", action=argparse.BooleanOptionalAction, default=True, help="try X search only when profile page has no recent tweets")
    ap.add_argument("--headed", action="store_true", help="show browser")
    ap.add_argument("--send", action="store_true", help="send report to Telegram")
    ap.add_argument("--no-send", action="store_true", help="do not send Telegram after a live scan")
    ap.add_argument("--no-translate", action="store_true")
    ap.add_argument("--translate-cache", action="store_true", help="translate missing English tweets in cache only")
    ap.add_argument("--translate-limit", type=int, default=20, help="max cached tweets to translate after scan; 0 means no limit")
    ap.add_argument("--cache-recent", type=int, default=0, help="print recent tweets from local cache, no web scan")
    ap.add_argument("--telegram-chars", type=int, default=260, help="max chars per tweet in Telegram")
    ap.add_argument("--telegram-per-kol", type=int, default=0, help="max tweets per KOL in Telegram; 0 means no limit")
    ap.add_argument("--telegram-group-size", type=int, default=20, help="max tweets per Telegram message group; 0 means one group")
    ap.add_argument("--telegram-style", choices=["digest", "list"], default="list")
    ap.add_argument("--telegram-mode", choices=["full", "focus"], default="focus", help="full sends all selected tweets; focus filters noisy tweets and merges threads")
    ap.add_argument("--telegram-focus-limit", type=int, default=0, help="max tweets/thread summaries in focus mode; 0 means no limit")
    ap.add_argument("--telegram-focus-per-kol", type=int, default=DEFAULT_FOCUS_PER_KOL, help="max focus rows per KOL; 0 means no per-KOL cap")
    ap.add_argument("--include-low-signal", action="store_true", help="include short replies, CTA text, and low-signal tweets in Telegram output")
    ap.add_argument("--telegram-preview", action="store_true", help="print Telegram compact format")
    ap.add_argument("--dry-run", action="store_true", help="parse config only")
    args = ap.parse_args()
    live_scan_send = not args.no_send

    load_dotenv(ROOT / ".env")
    if args.cache_recent > 0:
        results = cached_results(args.cache_recent, args.hours, args.handles)
        if args.telegram_preview:
            report = build_telegram_report(
                results,
                args.hours,
                args.telegram_chars,
                args.telegram_per_kol,
                args.telegram_style,
                args.telegram_group_size,
                args.telegram_mode,
                args.telegram_focus_limit,
                args.telegram_focus_per_kol,
                args.include_low_signal,
            )
            print(report)
        elif args.send:
            report = ""
        else:
            report = build_report(results, args.hours)
            print(report)
        if args.send and not args.no_send:
            reports = build_telegram_reports(
                results,
                args.hours,
                args.telegram_chars,
                args.telegram_per_kol,
                args.telegram_style,
                args.telegram_group_size,
                args.telegram_mode,
                args.telegram_focus_limit,
                args.telegram_focus_per_kol,
                args.include_low_signal,
            )
            stats = telegram_send_reports_once(reports, args)
            print(f"sent groups={stats['groups']} rows={stats['rows']}")
        return 0
    if args.translate_cache:
        stats = translate_tweet_store(args.translate_limit)
        print(json.dumps({"cache": str(TWEET_STORE), **stats}, ensure_ascii=False))
        return 0

    kols = parse_kols(KOLS_FILE)
    if args.dry_run:
        print(json.dumps({"ok": True, "kols": len(kols), "sample": kols[:5]}, ensure_ascii=False, indent=2))
        return 0
    if not kols:
        raise RuntimeError(f"no KOLs found: {KOLS_FILE}")
    if args.handles.strip():
        wanted = {"@" + x.strip().lstrip("@").lower() for x in args.handles.split(",") if x.strip()}
        kols = [x for x in kols if x["handle"].lower() in wanted]
        if not kols:
            raise RuntimeError(f"no matching handles: {args.handles}")
    if args.max_kols > 0:
        kols = kols[:args.max_kols]

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    results = scrape_all(
        kols,
        args.hours,
        args.limit,
        args.scrolls,
        headless=not args.headed,
        page_wait_ms=args.page_wait_ms,
        scroll_wait_ms=args.scroll_wait_ms,
        search_fallback=args.search_fallback,
    )

    stamp = cn_now().strftime("%Y%m%d-%H%M%S")
    day = cn_now().strftime("%Y%m%d")
    store_stats = update_tweet_store(results, stamp)
    translate_stats = {"translated": 0, "skipped": 0, "failed": 0}
    if not args.no_translate:
        translate_stats = translate_tweet_store(args.translate_limit)
        apply_store_translations(results)
    save_json(STATE_DIR / f"{day}.json", {"hours": args.hours, "store": store_stats, "results": results})
    report = build_report(results, args.hours)
    report_path = REPORT_DIR / f"{day}.md"
    report_path.write_text(report, encoding="utf-8")
    prune_daily_outputs()
    print(str(report_path))
    print(json.dumps({"store": store_stats, "translate": translate_stats}, ensure_ascii=False))
    if args.send or live_scan_send:
        reports = build_telegram_reports(
            results,
            args.hours,
            args.telegram_chars,
            args.telegram_per_kol,
            args.telegram_style,
            args.telegram_group_size,
            args.telegram_mode,
            args.telegram_focus_limit,
            args.telegram_focus_per_kol,
            args.include_low_signal,
        )
        stats = telegram_send_reports_once(reports, args)
        print(f"sent groups={stats['groups']} rows={stats['rows']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
