\ = "backup-" + (Get-Date -Format "yyyyMMdd-HHmmss")
git add -A | Out-Null
git commit -m "backup: \" 2>\ | Out-Null
git tag \
Write-Host "Создан тег \. Чтобы отправить: git push --follow-tags"
