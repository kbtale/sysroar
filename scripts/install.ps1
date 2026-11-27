param(
    [string]$ApiUrl = $env:SYSROAR_API_BASE_URL,
    [string]$EnrollmentToken = $env:SYSROAR_ENROLLMENT_TOKEN,
    [string]$Repo = "kbtale/sysroar",
    [string]$Version = "latest",
    [string]$InstallDir = "C:\Program Files\SysRoarAgent"
)

$ErrorActionPreference = "Stop"
$Target = "x86_64-pc-windows-msvc"
$Archive = "sysroar-agent-$Target.zip"
if ($Version -eq "latest") {
    $BaseDownload = "https://github.com/$Repo/releases/latest/download"
} else {
    $BaseDownload = "https://github.com/$Repo/releases/download/$Version"
}

$TmpDir = Join-Path $env:TEMP ("sysroar-install-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $TmpDir | Out-Null

try {
    $ZipPath = Join-Path $TmpDir $Archive
    $ShaPath = Join-Path $TmpDir "$Archive.sha256"
    Invoke-WebRequest -UseBasicParsing -Uri "$BaseDownload/$Archive" -OutFile $ZipPath
    Invoke-WebRequest -UseBasicParsing -Uri "$BaseDownload/$Archive.sha256" -OutFile $ShaPath

    $ExpectedHash = (Get-Content $ShaPath -Raw).Trim().Split()[0].ToLower()
    $ActualHash = (Get-FileHash $ZipPath -Algorithm SHA256).Hash.ToLower()
    if ($ExpectedHash -ne $ActualHash) {
        throw "Checksum verification failed for $Archive"
    }

    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    Expand-Archive -Path $ZipPath -DestinationPath $InstallDir -Force
    $BinPath = Join-Path $InstallDir "sysroar-agent.exe"

    if ($ApiUrl -and $EnrollmentToken) {
        $BaseUrl = $ApiUrl.TrimEnd('/')
        $Body = @{
            enrollment_token = $EnrollmentToken
            name = $env:COMPUTERNAME
            hostname = $env:COMPUTERNAME
        } | ConvertTo-Json
        $Res = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/telemetry/enroll/" -ContentType "application/json" -Body $Body
        [Environment]::SetEnvironmentVariable("SYSROAR_API_BASE_URL", $BaseUrl, "Machine")
        [Environment]::SetEnvironmentVariable("SYSROAR_SERVER_ID", $Res.server_id, "Machine")
        [Environment]::SetEnvironmentVariable("SYSROAR_AGENT_KEY", $Res.agent_key, "Machine")
        [Environment]::SetEnvironmentVariable("SYSROAR_BUFFER_PATH", (Join-Path $InstallDir "buffer.db"), "Machine")

        $ServiceScript = Join-Path $TmpDir "windows-service.ps1"
        Invoke-WebRequest -UseBasicParsing -Uri "https://raw.githubusercontent.com/$Repo/main/agent/deploy/windows-service.ps1" -OutFile $ServiceScript
        & $ServiceScript -BinaryPath $BinPath
    }

    Write-Host "SysRoar agent installed successfully at $BinPath"
} finally {
    Remove-Item -Recurse -Force $TmpDir -ErrorAction SilentlyContinue
}
