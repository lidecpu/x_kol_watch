# X KOL Watch

每天扫描 KOL 最近 24 小时 X 推文，英文翻译成中文，生成报告并可发送 Telegram。

## 配置

复制 `.env.example` 为 `.env`，填入：

```text
X_AUTH=你的 auth_token
X_CT0=你的 ct0
TELEGRAM_BOT_TOKEN=你的 Telegram bot token
TELEGRAM_CHAT_ID=你的 chat id
```

`.env` 已被 `.gitignore` 忽略，不要提交。

## 安装依赖

```powershell
py -3 -m pip install playwright
py -3 -m playwright install chromium
```

默认使用 Playwright 自带的 headless Chromium，不会打开桌面浏览器窗口。

`CHROME_PATH` 默认留空。只有排查浏览器问题时，才临时指定本机 Chrome：

```text
CHROME_PATH=C:\Program Files\Google\Chrome\Application\chrome.exe
```

## 运行

日常隐藏入口：扫描完成后自动发送 Telegram 重点版，不会弹出控制台黑窗：

```text
run_daily_hidden.vbs
```

兼容入口，同样会自动发送 Telegram 重点版，适合放到计划任务：

```text
run_daily_send_hidden.vbs
```

调试时再手动运行 PowerShell 脚本：

```powershell
.\run_daily.ps1
```

PowerShell 默认也会在扫描完成后自动发送 Telegram 重点版。只扫不发：

```powershell
.\run_daily.ps1 -NoSend
```

如果需要自动发送全量版：

```powershell
.\run_daily.ps1 -TelegramMode full
```

只生成报告，不发送 Telegram：

```powershell
py -3 .\x_kol_daily.py --no-send
```

生成报告并自动发送 Telegram 重点版：

```powershell
py -3 .\x_kol_daily.py
```

Telegram 默认发送全量版：最近 24 小时推文按 KOL 聚合，同一个 KOL 放在一起；每组最多 20 条，并按 Telegram 长度自动拆组；本地 `reports/` 仍保存完整报告。

Telegram 默认会过滤短回复、低信息 CTA、孤立英文短句和 URL 残片；本地报告和缓存仍保留原始内容。

```powershell
py -3 .\x_kol_daily.py --send
```

只发送重点版：过滤明显噪音，合并同一时间连发 thread，适合日常快速看。

```powershell
py -3 .\x_kol_daily.py --telegram-mode focus
```

发送全量版：

```powershell
py -3 .\x_kol_daily.py --telegram-mode full
```

如果需要连低信息短回复也一起发送：

```powershell
py -3 .\x_kol_daily.py --telegram-mode full --include-low-signal
```

调整 Telegram 分组大小：

```powershell
py -3 .\x_kol_daily.py --send --telegram-group-size 20
```

只看本地已保存推文，不打开 X：

```powershell
py -3 .\x_kol_daily.py --cache-recent 3
```

把本地缓存摘要发送到 Telegram，不重新扫描 X：

```powershell
py -3 .\x_kol_daily.py --cache-recent 48 --send
```

预览 Telegram 重点版，不发送：

```powershell
py -3 .\x_kol_daily.py --cache-recent 48 --telegram-preview --telegram-mode focus
```

报告目录：

```text
reports/
```

状态和翻译缓存：

```text
state/
cache/
```

去重后的本地推文库：

```text
cache/tweets.json
```

脚本会自动清理旧输出：

```text
reports/ 只保留最近 5 个报告
state/   只保留最近 5 个状态快照
```
