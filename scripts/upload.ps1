param(
  [Parameter(Mandatory=$true)]
  [string]$Path
)

if (-not (Test-Path $Path)) {
  Write-Error "file not found: $Path"
  exit 1
}

# Важно: экранируем кавычки вокруг пути (из-за пробела в "Life PC")
$resp = curl.exe -sS -F "file=@`"$Path`";type=application/pdf" "http://127.0.0.1:8000/upload"

try {
  $j = $resp | ConvertFrom-Json
  if (-not $j.job_id) { throw "no job_id in response: $resp" }
  Write-Output "job_id=$($j.job_id)"
} catch {
  Write-Error "upload failed: $resp"
  exit 1
}
