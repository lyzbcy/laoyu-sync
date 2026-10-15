param(
  [string]$WatchDir = 'd2f144477eaaa2e1',
  [int]$Seconds = 120,
  [string]$LogFile = 'E:\共享\创业\01-捞鱼软件产品\laoyu-sync\verification\win-037\watch-dir.log'
)
$deadline = (Get-Date).AddSeconds($Seconds)
$seen = @{}
while ((Get-Date) -lt $deadline) {
  $procs = Get-CimInstance Win32_Process | Where-Object {
    ($_.ExecutablePath -and $_.ExecutablePath.Contains($WatchDir)) -or
    ($_.CommandLine -and $_.CommandLine.Contains($WatchDir))
  }
  foreach ($p in $procs) {
    $key = "$($p.ProcessId)|$($p.Name)"
    if (-not $seen.ContainsKey($key)) {
      $seen[$key] = $true
      $line = "{0} APPEAR pid={1} ppid={2} name={3} cmd={4}" -f (Get-Date -Format 'HH:mm:ss.fff'), $p.ProcessId, $p.ParentProcessId, $p.Name, ($p.CommandLine -replace $WatchDir, '<DIR>')
      Add-Content -Path $LogFile -Value $line -Encoding UTF8
    }
  }
  foreach ($k in @($seen.Keys)) {
    $pid2 = [int]($k.Split('|')[0])
    if ($pid2 -notin ($procs | ForEach-Object { $_.ProcessId })) {
      $seen.Remove($k)
      $line = "{0} GONE   pid={1}" -f (Get-Date -Format 'HH:mm:ss.fff'), $pid2
      Add-Content -Path $LogFile -Value $line -Encoding UTF8
    }
  }
  Start-Sleep -Milliseconds 200
}
