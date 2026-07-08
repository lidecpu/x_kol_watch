export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const runKey = request.headers.get("X-Run-Key") || url.searchParams.get("key");

    if (!env.RUN_KEY || runKey !== env.RUN_KEY) {
      return jsonResponse({ ok: true, message: "x-kol-watch-trigger ready" });
    }

    const result = await triggerGithub(env, "manual");
    return jsonResponse(result);
  },

  async scheduled(event, env, ctx) {
    ctx.waitUntil(triggerGithub(env, "cron"));
  },
};

async function triggerGithub(env, source) {
  requireEnv(env, "GITHUB_TOKEN");

  const owner = env.GITHUB_OWNER || "lidecpu";
  const repo = env.GITHUB_REPO || "x_kol_watch";
  const workflow = env.GITHUB_WORKFLOW || "x-kol-daily.yml";
  const ref = env.GITHUB_REF || "main";
  const apiUrl = `https://api.github.com/repos/${owner}/${repo}/actions/workflows/${workflow}/dispatches`;

  const response = await fetch(apiUrl, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "x-kol-watch-trigger",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ ref }),
  });

  const text = await response.text();
  if (!response.ok) {
    throw new Error(`GitHub dispatch failed ${response.status}: ${text.slice(0, 500)}`);
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

function requireEnv(env, name) {
  if (!env[name]) {
    throw new Error(`Missing Worker secret: ${name}`);
  }
}

function jsonResponse(data, status = 200) {
  return new Response(JSON.stringify(data, null, 2), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
    },
  });
}
