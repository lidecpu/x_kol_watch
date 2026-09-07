const GITHUB_TIMEOUT_MS = 20_000;
const ORPHAN_QUEUED_AGE_MS = 24 * 60 * 60 * 1000;
const ACTIVE_RUN_STATUSES = new Set([
  "queued",
  "in_progress",
  "waiting",
  "pending",
  "requested",
]);

export default {
  async fetch(request, env) {
    if (request.method === "GET") {
      return jsonResponse({ ok: true, message: "x-kol-watch-trigger ready" });
    }

    if (request.method !== "POST") {
      return jsonResponse(
        { ok: false, error: "method not allowed" },
        405,
        { allow: "GET, POST" },
      );
    }

    const runKey = request.headers.get("X-Run-Key");
    if (!env.RUN_KEY || !runKey || runKey !== env.RUN_KEY) {
      return jsonResponse({ ok: false, error: "unauthorized" }, 401);
    }

    try {
      const result = await triggerGithub(env, "manual");
      logDispatch(result);
      return jsonResponse(result);
    } catch (error) {
      logDispatch({ ok: false, source: "manual", error: errorMessage(error) }, "error");
      return jsonResponse({ ok: false, error: "GitHub dispatch failed" }, 502);
    }
  },

  async scheduled(_event, env, ctx) {
    ctx.waitUntil(runScheduled(env));
  },
};

async function runScheduled(env) {
  try {
    const result = await triggerGithub(env, "cron");
    logDispatch(result);
  } catch (error) {
    logDispatch({ ok: false, source: "cron", error: errorMessage(error) }, "error");
    throw error;
  }
}

async function triggerGithub(env, source) {
  requireEnv(env, "GITHUB_TOKEN");

  const owner = env.GITHUB_OWNER || "lidecpu";
  const repo = env.GITHUB_REPO || "x_kol_watch";
  const workflow = env.GITHUB_WORKFLOW || "x-kol-daily.yml";
  const ref = env.GITHUB_REF || "main";
  const { activeRuns, ignoredRuns } = await listActiveRuns(env, owner, repo, workflow, ref);
  const sendOnceKey = beijingSendOnceKey();
  if (activeRuns.length) {
    return {
      ok: true,
      source,
      skipped: true,
      reason: "active-run",
      active_runs: activeRuns.slice(0, 3).map((run) => ({
        id: run.id,
        number: run.run_number,
        status: run.status,
        created_at: run.created_at,
      })),
      ignored_runs: summarizeIgnoredRuns(ignoredRuns),
      time: new Date().toISOString(),
    };
  }
  const apiUrl = `https://api.github.com/repos/${owner}/${repo}/actions/workflows/${workflow}/dispatches`;

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), GITHUB_TIMEOUT_MS);
  let response;
  try {
    response = await fetch(apiUrl, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GITHUB_TOKEN}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "x-kol-watch-trigger",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        ref,
        inputs: {
          send_once_key: sendOnceKey,
        },
      }),
      signal: controller.signal,
    });
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      throw new Error("GitHub dispatch timed out");
    }
    throw new Error("GitHub dispatch request failed");
  } finally {
    clearTimeout(timeout);
  }

  if (!response.ok) {
    throw new Error(`GitHub dispatch failed ${response.status}`);
  }

  return {
    ok: true,
    source,
    status: response.status,
    workflow,
    ref,
    send_once_key: sendOnceKey,
    ignored_runs: summarizeIgnoredRuns(ignoredRuns),
    time: new Date().toISOString(),
  };
}

async function listActiveRuns(env, owner, repo, workflow, ref) {
  const query = new URLSearchParams({
    workflow_id: workflow,
    branch: ref,
    event: "workflow_dispatch",
    per_page: "20",
  });
  const apiUrl = `https://api.github.com/repos/${owner}/${repo}/actions/runs?${query}`;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), GITHUB_TIMEOUT_MS);
  let response;
  try {
    response = await fetch(apiUrl, {
      headers: {
        Authorization: `Bearer ${env.GITHUB_TOKEN}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "x-kol-watch-trigger",
      },
      signal: controller.signal,
    });
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      throw new Error("GitHub active-run check timed out");
    }
    throw new Error("GitHub active-run check failed");
  } finally {
    clearTimeout(timeout);
  }
  if (!response.ok) {
    throw new Error(`GitHub active-run check failed ${response.status}`);
  }
  const payload = await response.json();
  const runs = Array.isArray(payload?.workflow_runs) ? payload.workflow_runs : [];
  const activeRuns = [];
  const ignoredRuns = [];
  for (const run of runs) {
    if (!ACTIVE_RUN_STATUSES.has(run?.status)) continue;
    if (await isOrphanQueuedRun(env, owner, repo, run)) {
      ignoredRuns.push(run);
      continue;
    }
    activeRuns.push(run);
  }
  return { activeRuns, ignoredRuns };
}

async function isOrphanQueuedRun(env, owner, repo, run) {
  if (run?.status !== "queued") return false;
  const createdAt = Date.parse(String(run.created_at || ""));
  if (!Number.isFinite(createdAt) || Date.now() - createdAt < ORPHAN_QUEUED_AGE_MS) {
    return false;
  }
  const jobsUrl = run.jobs_url || `https://api.github.com/repos/${owner}/${repo}/actions/runs/${run.id}/jobs?per_page=1`;
  const payload = await githubJson(env, jobsUrl, "GitHub jobs check");
  if (!Array.isArray(payload?.jobs)) {
    throw new Error("GitHub jobs check returned invalid payload");
  }
  return payload.jobs.length === 0;
}

async function githubJson(env, apiUrl, label) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), GITHUB_TIMEOUT_MS);
  let response;
  try {
    response = await fetch(apiUrl, {
      headers: {
        Authorization: `Bearer ${env.GITHUB_TOKEN}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "x-kol-watch-trigger",
      },
      signal: controller.signal,
    });
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      throw new Error(`${label} timed out`);
    }
    throw new Error(`${label} request failed`);
  } finally {
    clearTimeout(timeout);
  }
  if (!response.ok) throw new Error(`${label} failed ${response.status}`);
  return response.json();
}

function beijingSendOnceKey(date = new Date()) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(date);
  const values = Object.fromEntries(parts.map(({ type, value }) => [type, value]));
  return `${values.year}${values.month}${values.day}:24h:full`;
}

function summarizeIgnoredRuns(runs) {
  return runs.slice(0, 3).map((run) => ({
    id: run.id,
    number: run.run_number,
    status: run.status,
    created_at: run.created_at,
    reason: "stale-queued-no-jobs",
  }));
}

function errorMessage(error) {
  return error instanceof Error ? error.message : "unknown error";
}

function logDispatch(result, level = "log") {
  const entry = {
    event: "github_dispatch",
    ok: Boolean(result.ok),
    source: result.source,
  };
  if (result.status) entry.status = result.status;
  if (result.skipped) entry.skipped = true;
  if (result.reason) entry.reason = result.reason;
  if (result.active_runs) entry.active_runs = result.active_runs;
  if (result.ignored_runs?.length) entry.ignored_runs = result.ignored_runs;
  if (result.workflow) entry.workflow = result.workflow;
  if (result.ref) entry.ref = result.ref;
  if (result.send_once_key) entry.send_once_key = result.send_once_key;
  if (result.error) entry.error = result.error;
  console[level](JSON.stringify(entry));
}

function requireEnv(env, name) {
  if (!env[name]) {
    throw new Error(`Missing Worker secret: ${name}`);
  }
}

function jsonResponse(data, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(data, null, 2), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      ...extraHeaders,
    },
  });
}
