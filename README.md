# X KOL Watch

每天扫描 `kols.txt` 里的 X/Twitter KOL，抓取最近 24 小时推文，英文自动翻译成中文，过滤低信息内容后发送 Telegram 摘要。

这个仓库通过 Cloudflare Worker 定时触发 GitHub Actions，不需要在本地长期挂脚本。

## 功能

- 每天北京时间 `23:30` 自动扫描最近 24 小时推文
- 支持在 GitHub Actions 页面手动运行
- 英文推文自动翻译成中文
- Telegram 按 KOL 分组发送，长内容自动拆分
- Telegram 首组显示 USDT、USDC 流通量、全网现货（CEX+DEX）、DEX 现货、估算 CEX 现货、全网合约 24H 成交额及 BTC/ETH 现货 ETF 资金流；ETF 数据来自 Farside Investors
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

进入 GitHub Actions 页面，选择 `X KOL Daily`，点击 `Run workflow` 即可手动触发。默认发送全量版 Telegram 摘要，并继续逐条过滤空内容、明显推广和低信号推文。

本地只生成市场首页、不扫描 KOL：

```text
python x_kol_daily.py --market-only --telegram-preview
```

发送单条市场首页时显式使用 `--send`。需要防止同一次操作重复发送时，提供唯一的 `--send-once-key`：

```text
python x_kol_daily.py --market-only --send --send-once-key "market-YYYYMMDD-purpose"
```

本机扫描使用桌面 `Google szwechat8` 的 X 登录态。先打开这个快捷方式，确认 CDP 地址实际对应 `szwechat8`，再把下方占位符替换为核验后的本机地址：

```text
python x_kol_daily.py --cdp-url "<VERIFIED_LOCAL_CDP_URL>" --max-kols 2 --no-search-fallback --no-translate --no-send
```

`--cdp-url` 必须显式提供本机地址。程序访问 X 前会核验 Chrome 数据目录，不是 `szwechat8` 就停止。多个 Chrome 可能分别监听 IPv4、IPv6 的同一端口，不能只凭 `9222` 判断账号。程序不替换 Cookie，不关闭用户浏览器；扫描结束只关闭自己的标签页。这个模式默认不发送 Telegram，发送需要显式添加 `--send`，且不要同时使用 `--no-send`。它不改变 Cloudflare Worker 或 GitHub Actions 的定时流程，本机 Chrome 必须保持运行。

### Cloudflare 浏览器只读探针

使用前需授权将项目的 `X_AUTH`、`X_CT0` 登录凭据发送给 Cloudflare 官方 Browser Rendering 服务。在本地 `.env` 配置 `CLOUDFLARE_BROWSER_API_TOKEN`；账号从已有 Wrangler 账号缓存读取，也可显式配置 `CLOUDFLARE_ACCOUNT_ID`。凭据不要提交到 Git。

```text
python x_kol_daily.py --cloudflare-probe --max-kols 1
```

探针最多检查两个明确选择的 KOL，只输出脱敏摘要，不写缓存或报告、不翻译、不发送 Telegram，也不改变定时流程。两次请求间等待 12 秒；验证码、登录跳转、限流、缺少准确时间或近时间窗内的正文截断时立即停止，退出码为 `2`，不自动重试。HTTP 200 不等于扫描成功。`coverage=snapshot_no_recent_visible` 只表示首屏推文按时间倒序且最新一条已早于截止时间；`snapshot_recent_visible` 表示首屏存在近期推文但仍不是完整分页扫描；其他覆盖状态不作“无近期推文”结论。

时间优先读取带时区的 `datetime`。已识别的新页面缺少该字段时，按 [X 官方 Snowflake 格式](https://docs.x.com/fundamentals/x-ids) 和 [官方算法](https://github.com/twitter-archive/snowflake/blob/snowflake-2010/src/main/scala/com/twitter/service/snowflake/IdWorker.scala) 解码推文 ID 内的毫秒创建时间，摘要标明 `x_snowflake` 来源及 UTC 时间。非法或未来时间不采用，不按相对日期或采集时刻估算；本机和现有定时扫描的时间口径不变。

跳转到 X 登录页时报告 `authentication_required`；跳转到账号注册或引导页时报告 `account_setup_required`。能读取公开主页不能证明登录态可用于搜索，账号引导页也不能当作空结果。

持续会话探针复用现有推文扫描器，支持滚动和搜索兜底；同样不保存或发送报告，限两位 KOL、扫描预算 90 秒。默认使用项目 Cookie。经明确授权后，可仅在内存中读取核验过的 `szwechat8` 当前登录态并发送给 Cloudflare：

```text
python x_kol_daily.py --cloudflare-cdp-probe --cookie-cdp-url "<VERIFIED_LOCAL_CDP_URL>" --max-kols 2 --scrolls 3
```

`--cookie-cdp-url` 表示明确同意将两个 X 登录 Cookie 发给 Cloudflare 官方服务。程序先核验 `szwechat8` 数据目录，其他配置直接停止；不替换 `.env` 或浏览器 Cookie，不关闭用户 Chrome，只关闭核验标签页和本次云端会话。KOL 页面访问、滚动和搜索在 Cloudflare 执行，本机 Chrome 只提供临时登录态。结果中的 `bounded_scan` 表示受条数、滚动次数和时间预算限制，不承诺全量覆盖；失败不重试，不影响定时任务。

## Cloudflare 定时触发

`cloudflare-worker/` 是触发 GitHub Actions 的 Worker：

- `wrangler.toml` 配置 Worker 名称和北京时间 `23:30` 对应的 UTC cron：`30 15 * * *`
- `src/index.js` 在定时触发时调用 GitHub Actions `workflow_dispatch`
- Worker 会忽略超过 24 小时且没有 job 的孤立排队运行，并传入按北京时间日期生成的稳定 `send_once_key`，避免旧运行恢复后重复发送 Telegram
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
