param(
  [Parameter(Mandatory=\True)][string]\
)
\ = Get-Date -Format "yyyy-MM-dd HH:mm"
\ = \Life PC
\ = "[\] [\] — \"
if (Test-Path CHECKPOINT.md) {
  \ = Get-Content CHECKPOINT.md -Raw
  ("\
" + \) | Set-Content CHECKPOINT.md -Encoding utf8
} else {
  Set-Content CHECKPOINT.md -Value \ -Encoding utf8
}
git add CHECKPOINT.md | Out-Null
git commit -m "checkpoint: \" 2>\ | Out-Null
Write-Host "Добавлен чекпоинт: \"
