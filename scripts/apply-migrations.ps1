# Applies every file in infra/postgres/migrations in numeric order.
#
# Why this exists: docker-compose only mounts infra/postgres/init.sql into
# docker-entrypoint-initdb.d, and init.sql creates just 9 tables. Everything
# added since — defects, defect_messages, call_logs, agent_prompts,
# app_settings — lives in the numbered migrations, which nothing applies
# automatically. A fresh `docker compose up` therefore comes up with a schema
# the backend expects but does not have (this is what produced the
# `relation "call_logs" does not exist` 500s).
#
# Every migration is written to be idempotent, so re-running this is safe.
#
# Usage:
#   ./scripts/apply-migrations.ps1
#   ./scripts/apply-migrations.ps1 -Container warranty-postgres -Database warranty -User warranty_user

param(
    [string]$Container = "warranty-postgres",
    [string]$Database  = "warranty",
    [string]$User      = "warranty_user"
)

$ErrorActionPreference = "Stop"

$migrationDir = Join-Path $PSScriptRoot "..\infra\postgres\migrations"
if (-not (Test-Path $migrationDir)) {
    throw "Migration directory not found: $migrationDir"
}

$running = docker ps --filter "name=$Container" --format "{{.Names}}"
if ($running -notcontains $Container) {
    throw "Postgres container '$Container' is not running. Start the stack first (docker compose up -d)."
}

$files = Get-ChildItem -Path $migrationDir -Filter "*.sql" | Sort-Object Name
if ($files.Count -eq 0) {
    Write-Host "No migrations found in $migrationDir"
    exit 0
}

Write-Host "Applying $($files.Count) migration(s) to $Database on $Container`n"

$failed = @()
foreach ($file in $files) {
    Write-Host ("-> {0}" -f $file.Name)
    # ON_ERROR_STOP makes psql exit non-zero on the first failing statement
    # instead of plodding on and reporting success.
    Get-Content -Raw -LiteralPath $file.FullName |
        docker exec -i $Container psql -U $User -d $Database -v ON_ERROR_STOP=1 --quiet 1>$null

    if ($LASTEXITCODE -ne 0) {
        Write-Host ("   FAILED ({0})" -f $file.Name) -ForegroundColor Red
        $failed += $file.Name
    } else {
        Write-Host "   ok" -ForegroundColor Green
    }
}

Write-Host ""
if ($failed.Count -gt 0) {
    Write-Host ("{0} migration(s) failed: {1}" -f $failed.Count, ($failed -join ", ")) -ForegroundColor Red
    exit 1
}

Write-Host "All migrations applied." -ForegroundColor Green
