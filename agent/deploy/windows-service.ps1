param(
    [Parameter(Mandatory = $true)]
    [string]$BinaryPath,
    [string]$ServiceName = "SysRoarAgent",
    [string]$DisplayName = "SysRoar Telemetry Agent"
)

if (-not (Test-Path $BinaryPath)) {
    throw "Agent binary not found at $BinaryPath"
}

$existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existing) {
    Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
    sc.exe delete $ServiceName | Out-Null
}

New-Service -Name $ServiceName -BinaryPathName "`"$BinaryPath`"" -DisplayName $DisplayName -StartupType Automatic
Start-Service -Name $ServiceName
