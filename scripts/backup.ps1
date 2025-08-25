$tag = "backup-" + (Get-Date -Format "yyyyMMdd-HHmmss")
git add -A | Out-Null
git commit -m "backup: $tag" 2>$null | Out-Null
git tag $tag
Write-Host "Создан тег $tag. Чтобы отправить: git push --follow-tags"
