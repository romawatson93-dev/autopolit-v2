param(
    [Parameter(Mandatory=$true)]
    [string]$Url
)

# 1) сначала пробуем реальный curl.exe (обходит прокси PowerShell)
try {
    & curl.exe -sS $Url
    exit 0
} catch {}

# 2) если что-то мешает на хосте — пробуем из контейнера api (python -c)
$py = @'
import sys, urllib.request
u = sys.argv[1]
print(urllib.request.urlopen(u).read().decode())
'@

try {
    docker exec -i api python -c $py $Url
} catch {
    Write-Host "Не удалось получить $Url"
    exit 1
}
