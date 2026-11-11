$ErrorActionPreference = 'Stop'
$labRoot = Split-Path -Parent $PSScriptRoot
$labProcessor = $env:PROCESSOR_ARCHITEW6432
if (-not $labProcessor) { $labProcessor = $env:PROCESSOR_ARCHITECTURE }
switch ($labProcessor) {
    'AMD64' { $labArch = 'amd64' }
    'ARM64' { $labArch = 'arm64' }
    default { throw 'Supported Windows CPU architectures: amd64 and arm64.' }
}
$labAsset = "langar-lab-windows-$labArch.exe"
$labUrl = "https://github.com/MohammadAminKoohi/OS-Practical/releases/download/langar-lab-v0.3.0/$labAsset"
$labChecksums = Join-Path $PSScriptRoot 'langar-lab/SHA256SUMS'
$labExpected = @(Get-Content -LiteralPath $labChecksums | Where-Object {
    $_ -match ('^[0-9a-f]{64}  ' + [regex]::Escape($labAsset) + '$')
})
if ($labExpected.Count -ne 1) { throw 'Missing or invalid checksum.' }
$labExpected = $labExpected[0].Substring(0, 64)
$labBin = Join-Path $labRoot '.langar-lab/bin'
New-Item -ItemType Directory -Path $labBin -Force | Out-Null
$labTemporary = Join-Path $labBin ('.install-' + [guid]::NewGuid().ToString() + '.exe')
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    Write-Host "Downloading $labAsset..."
    Invoke-WebRequest -UseBasicParsing -Uri $labUrl -OutFile $labTemporary -TimeoutSec 180
    $labActual = (Get-FileHash -LiteralPath $labTemporary -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($labActual -ne $labExpected) { throw 'Checksum mismatch; nothing installed.' }
    & $labTemporary --version
    if ($LASTEXITCODE -ne 0) { throw 'The downloaded executable could not run.' }
    $labTarget = Join-Path $labBin 'langar-lab.exe'
    Move-Item -LiteralPath $labTemporary -Destination $labTarget -Force
    Write-Host "Installed: $labTarget"
    Write-Host 'Next: .\.langar-lab\bin\langar-lab.exe setup'
} finally {
    if (Test-Path -LiteralPath $labTemporary) { Remove-Item -LiteralPath $labTemporary -Force }
}
