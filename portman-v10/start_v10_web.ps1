$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw "V10-.venv fehlt: $python"
}

Push-Location $PSScriptRoot
$previousPythonPath = $env:PYTHONPATH
$server = $null
try {
    $env:PYTHONPATH = Join-Path $PSScriptRoot 'src'
    & $python -c "from importlib.metadata import version; import flask, portman_parsers; print('Flask', version('Flask'), '| portman-parsers', version('portman-parsers'))"
    if ($LASTEXITCODE -ne 0) {
        throw "Web-Abhaengigkeit oder Parser fehlt in der V10-.venv. Web installieren: .\.venv\Scripts\python.exe -m pip install -e '.[web]'; Parser-Pin installieren: .\.venv\Scripts\python.exe -m pip install -r requirements-parser.txt"
    }

    $portProbe = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Parse('127.0.0.1'), 8765)
    try {
        $portProbe.Start()
    } catch {
        throw 'Port 8765 ist bereits belegt. Beenden Sie gezielt den zugehoerigen V10-Webserver und starten Sie erneut; ein vorhandener /health-Endpunkt wird nicht als eigener Server akzeptiert.'
    } finally {
        $portProbe.Stop()
    }

    $branch = (& git rev-parse --abbrev-ref HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $branch) { throw 'Git-Branch konnte nicht ermittelt werden.' }
    if ($branch -eq 'main' -or $branch -match 'parser') { throw "Start auf unzulaessigem Branch '$branch' abgebrochen." }
    $commit = (& git rev-parse --short HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $commit) { throw 'Git-Commit konnte nicht ermittelt werden.' }

    $dataDir = Join-Path $PSScriptRoot 'data\web-test'
    New-Item -ItemType Directory -Force -Path $dataDir | Out-Null

    $server = Start-Process -FilePath $python -ArgumentList @('-m', 'portman_v10.web.server') -WorkingDirectory $PSScriptRoot -PassThru -NoNewWindow
    $uri = 'http://127.0.0.1:8765/'
    $healthUri = 'http://127.0.0.1:8765/health'
    $ready = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        if ($server.HasExited) { throw "Lokaler Webserver wurde mit Exitcode $($server.ExitCode) beendet. Pruefen Sie die sichtbare Servermeldung oben." }
        try {
            $response = Invoke-WebRequest -Uri $healthUri -TimeoutSec 1 -UseBasicParsing
            if ($response.StatusCode -eq 200 -and $response.Content -eq 'ok') { $ready = $true; break }
        } catch { Start-Sleep -Milliseconds 500 }
    }
    if (-not $ready) { throw 'Lokaler Webserver wurde nicht rechtzeitig erreichbar; pruefen Sie die sichtbare Servermeldung oben.' }

    Write-Host "Web-Testoberfläche bereit: $uri"
    Write-Host "Branch: $branch | Commit: $commit | Datenbankprofil: data/web-test"
    Start-Process $uri
    Write-Host 'Der Server laeuft. Mit Strg+C beenden.'
    Wait-Process -Id $server.Id
} finally {
    if ($server -and -not $server.HasExited) { $server.Kill($true); $server.WaitForExit() }
    $env:PYTHONPATH = $previousPythonPath
    Pop-Location
}
