param(
    [Parameter(Mandatory=$true)]
    [string]$Url,
    [string]$Container,
    [string]$InternalUrl
)

# 1) Сначала пробуем реальный curl.exe (обходит прокси PowerShell)
try {
    & curl.exe -sS $Url
    exit 0
} catch {}

# 2) Если указаны контейнер и внутренний URL — проверим изнутри контейнера
if ($Container -and $InternalUrl) {
    $py = @'
import sys, urllib.request
u = sys.argv[1]
print(urllib.request.urlopen(u).read().decode())
'@
    try {
        docker exec -i $Container python -c $py $InternalUrl
        exit 0
    } catch {
        Write-Host "Не удалось получить $InternalUrl из контейнера $Container"
        exit 1
    }
}

Write-Host "Не удалось получить $Url (и контейнер не указан для fallback)."
exit 1