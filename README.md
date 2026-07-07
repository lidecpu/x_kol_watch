# X KOL Watch

每天扫描 `kols.txt` 里的 X/Twitter KOL，抓取最近 24 小时推文，英文自动翻译成中文，过滤低信息内容后发送 Telegram 摘要。

这个仓库主要通过 GitHub Actions 定时运行，不需要在本地长期挂脚本。

## 功能

- 每天北京时间 `23:30` 自动扫描最近 24 小时推文
- 支持在 GitHub Actions 页面手动运行
- 英文推文自动翻译成中文
- Telegram 按 KOL 分组发送，长内容自动拆分
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

打开：

```text
Actions -> X KOL Daily -> Run workflow
```

参数说明：

- `telegram_mode`: `focus` 为重点版，`full` 为全量版
- `send_telegram`: 是否发送 Telegram
- `max_kols`: 测试填 `2`，正式扫描全部填 `0`

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
