# X KOL Watch

X KOL Watch 是一个 X/Twitter KOL 推文监控脚本，用于每天扫描指定账号最近 24 小时推文，翻译英文内容，过滤低信息噪音，并把重点摘要发送到 Telegram。

适合用途：

- 每天固定时间汇总加密市场、链上数据、交易员和新闻账号动态
- 英文推文自动翻译成中文
- Telegram 按 KOL 分组发送，长内容自动拆组
- 过滤广告、抽奖、短回复、URL 残片、长钱包地址和单独币种词
- 支持本地调试，也支持 GitHub Actions 定时运行

## 配置

在本地新建 `.env`，只填写真实值：

```text
X_AUTH=your_x_auth_token
X_CT0=your_x_ct0
TELEGRAM_BOT_TOKEN=1234567890:replace_with_bot_token
TELEGRAM_CHAT_ID=123456789
```

`.env` 已被 `.gitignore` 忽略，不要提交到 Git 仓库。

## GitHub Actions

仓库已内置 `.github/workflows/x-kol-daily.yml`：

- 支持手动运行
- 每天北京时间 `23:30` 自动运行
- 默认 `focus` 重点模式
- 手动运行时可选择 `focus` 或 `full`
- `max_kols=0` 表示扫描全部 KOL，测试时建议先填 `2`

需要在 GitHub 仓库的 `Settings -> Secrets and variables -> Actions -> Repository secrets` 添加：

```text
X_AUTH
X_CT0
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
```

Secret 只填值本身，不要填 `KEY=value` 整行。

## 本地运行

安装依赖：

```powershell
python -m pip install playwright
python -m playwright install chromium
```

默认使用 Playwright 自带的 headless Chromium，不会打开桌面浏览器窗口。

生成报告并发送 Telegram 重点版：

```powershell
python .\x_kol_daily.py
```

只生成报告，不发送 Telegram：

```powershell
python .\x_kol_daily.py --no-send
```

发送全量版：

```powershell
python .\x_kol_daily.py --telegram-mode full
```

只看本地缓存，不打开 X：

```powershell
python .\x_kol_daily.py --cache-recent 48 --telegram-preview --telegram-mode focus
```

把本地缓存发送到 Telegram：

```powershell
python .\x_kol_daily.py --cache-recent 48 --send
```

## 文件说明

```text
kols.txt                      KOL 列表
x_kol_daily.py                主脚本
.github/workflows/            GitHub Actions 定时任务
reports/                      每日 Markdown 报告，本地忽略
state/                        每日状态，本地忽略
cache/tweets.json             本地推文缓存，本地忽略
cache/translations.json       翻译缓存，本地忽略
```

`reports/` 和 `state/` 按日期保存，每天一个文件；`cache/` 用于去重和翻译缓存。

## KOL 列表

编辑 `kols.txt`：

```text
名称 | @handle | 备注
```

示例：

```text
Watcher.Guru | @WatcherGuru | 加密新闻
Lookonchain | @lookonchain | 链上监测
```

## 注意

- X 登录 Cookie 可能过期，抓不到推文时先更新 `X_AUTH` 和 `X_CT0`
- GitHub Actions 运行在 GitHub 服务器，X 可能对机房 IP 有限制
- Telegram Bot Token 和 X Cookie 都属于敏感信息，必须放在 `.env` 或 GitHub Secrets
