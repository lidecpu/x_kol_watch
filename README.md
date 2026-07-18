# X KOL Watch

每天扫描 `kols.txt` 里的 X/Twitter KOL，抓取最近 24 小时推文，英文自动翻译成中文，过滤低信息内容后发送 Telegram 摘要。

这个仓库通过 Cloudflare Worker 定时触发 GitHub Actions，不需要在本地长期挂脚本。

## 功能

- 每天北京时间 `23:30` 自动扫描最近 24 小时推文
- 支持在 GitHub Actions 页面手动运行
- 英文推文自动翻译成中文
- Telegram 按 KOL 分组发送，长内容自动拆分
- 定时任务同一天同模式只发送一次，避免重复发 Telegram
- 过滤广告、抽奖、短回复、URL 残片、长钱包地址和单独币种词

## 配置 Secrets

在 GitHub 仓库页面打开：

```text
Settings -> Secrets and variables -> Actions -> Repository secrets
```

添加以下 4 个 Secret：

```text
X_AUTH
X_CT0
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
```

Secret 只填值本身，不要填 `KEY=value` 整行，也不要把 bot 名称填进 `TELEGRAM_BOT_TOKEN`。

## 手动运行

进入 GitHub Actions 页面，选择 `X KOL Daily`，点击 `Run workflow` 即可手动触发。默认发送重点版 Telegram 摘要。

## Cloudflare 定时触发

`cloudflare-worker/` 是触发 GitHub Actions 的 Worker：

- `wrangler.toml` 配置 Worker 名称和北京时间 `23:30` 对应的 UTC cron：`30 15 * * *`
- `src/index.js` 在定时触发时调用 GitHub Actions `workflow_dispatch`
- Worker Secret 需要配置 `GITHUB_TOKEN` 和 `RUN_KEY`
- `GET` 仅用于健康检查；手动触发必须使用 `POST` 并通过 `X-Run-Key` 请求头传递 `RUN_KEY`
- 不要把 `RUN_KEY` 放入 URL 查询参数、日志或文档

部署：

```text
cd cloudflare-worker
npx -y wrangler@latest deploy
```

更新 Secret：

```text
npx -y wrangler@latest secret put GITHUB_TOKEN
npx -y wrangler@latest secret put RUN_KEY
```

`GITHUB_TOKEN` 使用 fine-grained token，只授权 `lidecpu/x_kol_watch`，权限选择 `Actions: Read and write`。

## KOL 列表

编辑 `kols.txt`，一行一个账号：

```text
名称 | @handle | 备注
```

示例：

```text
Watcher.Guru | @WatcherGuru | 加密新闻
Lookonchain | @lookonchain | 链上监测
```

## 注意

- X Cookie 可能过期，抓不到推文时更新 `X_AUTH` 和 `X_CT0`
- GitHub Actions 运行在 GitHub 服务器，X 可能限制机房 IP
- Telegram Bot Token 和 X Cookie 都是敏感信息，只放 GitHub Secrets
