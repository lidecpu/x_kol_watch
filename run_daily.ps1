param(
  [switch]$NoSend,
  [ValidateSet('focus', 'full')]
  [string]$TelegramMode = 'focus'
)
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Here

$Candidates = @(
  (Join-Path $Here ".venv\Scripts\python.exe"),
  "py",
  "python",
  "C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
)

$Python = $null
foreach ($Candidate in $Candidates) {
  if ($Candidate -eq "py") {
    $cmd = Get-Command py -ErrorAction SilentlyContinue
    if ($cmd) { $Python = "py"; break }
  } elseif ($Candidate -eq "python") {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { $Python = "python"; break }
  } elseif (Test-Path -LiteralPath $Candidate) {
    $Python = $Candidate
    break
  }
}

if (-not $Python) {
  throw 'Python not found. Install Python or create .venv first.'
}

$ScriptArgs = @('.\x_kol_daily.py')
if (-not $NoSend) {
  $ScriptArgs += @('--send', '--telegram-mode', $TelegramMode)
}

if ($Python -eq 'py') {
  if ($ScriptArgs.Count -gt 1) {
    & py -3 @ScriptArgs
  } else {
    & py -3 '.\x_kol_daily.py'
  }
} else {
  & $Python @ScriptArgs
}
