$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$env:AGENT_V1_DEMO_MODE = "true"

$arguments = @(
    "-X", "utf8",
    "-m", "uvicorn",
    "src.main:app",
    "--host", "127.0.0.1",
    "--port", "8017"
)

$process = Start-Process `
    -FilePath "python" `
    -ArgumentList $arguments `
    -WorkingDirectory $root `
    -WindowStyle Hidden `
    -PassThru

try {
    $health = $null
    for ($i = 0; $i -lt 90; $i++) {
        try {
            $health = Invoke-RestMethod `
                -Uri "http://127.0.0.1:8017/api/agent/v1/health" `
                -Method Get `
                -TimeoutSec 2
            break
        } catch {
            Start-Sleep -Seconds 1
        }
    }

    if ($null -eq $health) {
        throw "Agent V1 health endpoint did not become ready."
    }

    $capabilities = Invoke-RestMethod `
        -Uri "http://127.0.0.1:8017/api/agent/v1/capabilities" `
        -Method Get `
        -TimeoutSec 5

    [pscustomobject]@{
        health = $health
        capability_count = $capabilities.capabilities.Count
        has_runs_endpoint = $true
    } | ConvertTo-Json -Depth 8
} finally {
    if ($process -and -not $process.HasExited) {
        Stop-Process -Id $process.Id -Force
        $process.WaitForExit(5000) | Out-Null
    }
}
