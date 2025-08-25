param(
  [Parameter(Mandatory=$true)]
  [string]$Name
)

# POST на /enqueue через curl.exe
$resp = curl.exe -sS -X POST "http://127.0.0.1:8000/enqueue?name=$Name"

try {
  $json = $resp | ConvertFrom-Json
  $jid = $json.job_id
  if (-not $jid) { throw "no job_id in response" }
  # печатаем только job_id без префиксов
  Write-Output $jid
} catch {
  Write-Error "enqueue failed: $($_.Exception.Message)"
  Write-Error "raw response: $resp"
  exit 1
}