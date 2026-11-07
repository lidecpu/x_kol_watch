import assert from "node:assert/strict";
import test from "node:test";
import worker from "../src/index.js";

const env = {
  RUN_KEY: "test-run-key",
  GITHUB_TOKEN: "test-github-token",
};

test("scheduled events dispatch only the market report with the scheduled Beijing date", async (t) => {
  const requests = [];
  const pending = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    requests.push({ url: String(url), options });
    return String(url).includes("/dispatches")
      ? new Response(null, { status: 204 })
      : Response.json({ workflow_runs: [] });
  });
  await worker.scheduled?.({
    scheduledTime: Date.parse("2026-11-08T15:30:00Z"),
  }, { ...env, GITHUB_REF: "unreleased" }, {
    waitUntil(promise) { pending.push(promise); },
  });
  await Promise.all(pending);
  assert.equal(requests.length, 2);
  assert.equal(
    requests[1].url,
    "https://api.github.com/repos/lidecpu/x_kol_watch/actions/workflows/x-kol-daily.yml/dispatches",
  );
  const payload = JSON.parse(requests[1].options.body);
  assert.equal(payload.ref, "main");
  assert.deepEqual(payload.inputs, {
    send_once_key: "20261108:24h:full",
    scan_kol: "false",
    send_kol: "false",
  });
});

test("scheduled dispatch failures remain failures", async (t) => {
  t.mock.method(globalThis, "fetch", async (url) =>
    String(url).includes("/dispatches")
      ? new Response(null, { status: 403 })
      : Response.json({ workflow_runs: [] }),
  );
  const pending = [];
  await worker.scheduled?.({
    scheduledTime: Date.parse("2026-11-08T15:30:00Z"),
  }, env, {
    waitUntil(promise) { pending.push(promise); },
  });
  assert.equal(pending.length, 1);
  await assert.rejects(pending[0], /GitHub dispatch failed 403/);
});

test("scheduled events do not start another workflow while one is active", async (t) => {
  const requests = [];
  const pending = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    requests.push({ url: String(url), options });
    return Response.json({
      workflow_runs: [{
        id: 123,
        run_number: 1,
        status: "in_progress",
        created_at: "2026-11-08T15:29:00Z",
      }],
    });
  });
  await worker.scheduled?.({
    scheduledTime: Date.parse("2026-11-08T15:30:00Z"),
  }, env, {
    waitUntil(promise) { pending.push(promise); },
  });
  await Promise.all(pending);
  assert.equal(requests.length, 1);
  assert.equal(requests[0].options.method, undefined);
});

test("authenticated manual requests still dispatch the production workflow", async (t) => {
  const requests = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    requests.push({ url: String(url), options });
    return String(url).includes("/dispatches")
      ? new Response(null, { status: 204 })
      : Response.json({ workflow_runs: [] });
  });
  const response = await worker.fetch(new Request("https://worker.test/", {
    method: "POST",
    headers: { "X-Run-Key": env.RUN_KEY },
  }), env);
  assert.equal(response.status, 200);
  const result = await response.json();
  assert.equal(result.source, "manual");
  assert.equal(result.status, 204);
  assert.equal(requests.length, 2);
  assert.equal(
    requests[1].url,
    "https://api.github.com/repos/lidecpu/x_kol_watch/actions/workflows/x-kol-daily.yml/dispatches",
  );
  const payload = JSON.parse(requests[1].options.body);
  assert.equal(payload.ref, "main");
  assert.match(payload.inputs.send_once_key, /^\d{8}:24h:full$/);
  assert.equal(payload.inputs.scan_kol, "false");
  assert.equal(payload.inputs.send_kol, "false");
});

test("health checks and unauthorized requests never dispatch workflows", async (t) => {
  const requests = [];
  t.mock.method(globalThis, "fetch", async (url) => {
    requests.push(url);
    throw new Error("Unexpected outbound request");
  });
  const health = await worker.fetch(new Request("https://worker.test/"), env);
  const unauthorized = await worker.fetch(new Request("https://worker.test/", {
    method: "POST",
  }), env);
  assert.equal(health.status, 200);
  assert.equal((await health.json()).ok, true);
  assert.equal(unauthorized.status, 401);
  assert.equal(requests.length, 0);
});
