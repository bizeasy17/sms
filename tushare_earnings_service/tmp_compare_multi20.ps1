$base=Import-Csv .\tmp_baseline_20.csv
$new=Import-Csv .\tmp_new_multi20_v2.csv
$joined=@()
foreach($n in $new){
  $b=$base | Where-Object { $_.ts_code -eq $n.ts_code } | Select-Object -First 1
  if($null -ne $b){
    $baseElapsed=[double]$b.symbol_elapsed
    $newElapsed=[double]$n.elapsed
    $improvePct=0.0
    if($baseElapsed -gt 0){
      $improvePct=[math]::Round((($baseElapsed-$newElapsed)/$baseElapsed)*100,2)
    }
    $joined += [pscustomobject]@{
      ts_code=$n.ts_code
      base_elapsed=$baseElapsed
      new_elapsed=$newElapsed
      base_latest=[double]$b.latest
      base_fusion=[double]$b.fusion
      new_predict=[double]$n.predict
      new_persist=[double]$n.persist
      delta=[math]::Round(($newElapsed-$baseElapsed),3)
      improve_pct=$improvePct
    }
  }
}
if(-not $joined){ throw 'No joined rows' }
$allBase=($joined.base_elapsed|Measure-Object -Average).Average
$allNew=($joined.new_elapsed|Measure-Object -Average).Average
$tail=$joined | Select-Object -Skip 1
$tailBase=($tail.base_elapsed|Measure-Object -Average).Average
$tailNew=($tail.new_elapsed|Measure-Object -Average).Average
"JOINED_COUNT=$($joined.Count)"
"AVG_ALL base=$([math]::Round($allBase,3)) new=$([math]::Round($allNew,3)) improve_pct=$([math]::Round((($allBase-$allNew)/$allBase)*100,2))"
"AVG_EXCL_FIRST base=$([math]::Round($tailBase,3)) new=$([math]::Round($tailNew,3)) improve_pct=$([math]::Round((($tailBase-$tailNew)/$tailBase)*100,2))"
"WORST5"
$joined | Sort-Object improve_pct | Select-Object -First 5 | Format-Table ts_code,base_elapsed,new_elapsed,improve_pct -AutoSize
"BEST5"
$joined | Sort-Object improve_pct -Descending | Select-Object -First 5 | Format-Table ts_code,base_elapsed,new_elapsed,improve_pct -AutoSize
