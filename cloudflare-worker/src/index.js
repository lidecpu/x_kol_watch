const GITHUB_TIMEOUT_MS = 20_000;

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
      body: JSON.stringify({ ref }),
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
    time: new Date().toISOString(),
  };
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
  if (result.workflow) entry.workflow = result.workflow;
  if (result.ref) entry.ref = result.ref;
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
