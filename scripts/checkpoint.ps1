param(
    [Parameter(Mandatory=$true)]
    [string]$Msg
)

$date = Get-Date -Format "yyyy-MM-dd HH:mm"
$user = $env:USERNAME
$line = "[$date] [$user] — $Msg"

if (Test-Path CHECKPOINT.md) {
    $existing = Get-Content CHECKPOINT.md -Raw
    ($line + "`r`n" + $existing) | Set-Content CHECKPOINT.md -Encoding utf8
} else {
    Set-Content CHECKPOINT.md -Value $line -Encoding utf8
}

git add CHECKPOINT.md | Out-Null
git commit -m "checkpoint: $Msg" 2>$null | Out-Null
Write-Host "Добавлен чекпоинт: $line"
