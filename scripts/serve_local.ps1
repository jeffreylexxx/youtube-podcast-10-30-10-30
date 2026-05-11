$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Python = "C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe"
$Log = Join-Path $Root "server.log"
$Command = "Set-Location '$Root'; & '$Python' -m http.server 8000 --bind 127.0.0.1 --directory site *> '$Log'"
Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoProfile", "-Command", $Command) -WindowStyle Hidden
Write-Host "Serving http://127.0.0.1:8000"
