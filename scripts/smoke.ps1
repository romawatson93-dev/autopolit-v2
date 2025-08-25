try {
  \ = Invoke-WebRequest -UseBasicParsing -Proxy \ http://127.0.0.1:8000/healthz
  Write-Host \.Content
} catch {
  Write-Host "Host 502, проверим из контейнера..."
  docker exec -it api python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/healthz').read().decode())"
}
