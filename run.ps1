# One-command startup (Windows replacement for the guide's run.sh).
#   .\run.ps1            demo mode
#   .\run.ps1 -Reload    auto-reload while developing
param([switch]$Reload)
# Not "Stop": PowerShell 5.1 turns any native stderr line (e.g. psql NOTICEs) into a fatal error.
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot
$env:PYTHONUTF8 = "1"

Write-Host "==> starting postgres"
docker compose up -d | Out-Null
do {
    Start-Sleep -Seconds 1
    docker compose exec -T db pg_isready -U nudge -d nudgeos *> $null
} until ($LASTEXITCODE -eq 0)
Write-Host "    postgres ready"

Write-Host "==> applying schema (idempotent)"
Get-Content schema.sql -Raw | docker compose exec -T db psql -U nudge -d nudgeos -q *> $null

Write-Host "==> releasing any messages stuck in processing"
docker compose exec -T db psql -U nudge -d nudgeos -q -c "UPDATE messages SET status='queued' WHERE direction='in' AND status='processing' AND attempts < 3;" *> $null

$port = (Select-String -Path .env -Pattern '^PORT=(\d+)').Matches.Groups[1].Value
if (-not $port) { $port = "8010" }
Write-Host "==> starting app on :$port  (tunnel: cloudflared tunnel --url http://localhost:$port)"
if ($Reload) { uv run python serve.py --reload } else { uv run python serve.py }
