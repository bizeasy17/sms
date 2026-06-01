$base=Import-Csv .\tmp_baseline_20.csv
$r1=Import-Csv .\tmp_new_multi20_v2.csv
$r2=Import-Csv .\tmp_new_multi20_v3.csv

function Join-ByCode($left,$right,$leftName,$rightName){
  $out=@()
  foreach($l in $left){
    $r=$right | Where-Object { $_.ts_code -eq $l.ts_code } | Select-Object -First 1
    if($null -ne $r){
      $out += [pscustomobject]@{
        ts_code=$l.ts_code
        left=[double]$l.$leftName
        right=[double]$r.$rightName
      }
    }
  }
  return $out
}

$jr1=Join-ByCode $base $r1 'symbol_elapsed' 'elapsed'
$jr2=Join-ByCode $base $r2 'symbol_elapsed' 'elapsed'
$j12=Join-ByCode $r1 $r2 'elapsed' 'elapsed'

if(-not $jr1 -or -not $jr2 -or -not $j12){ throw 'join failed' }

function Avg($arr,$prop){ return ($arr | Measure-Object -Property $prop -Average).Average }

$avgBase=Avg $jr1 'left'
$avgR1=Avg $jr1 'right'
$avgR2=Avg $jr2 'right'

$tailR1=$jr1|Select-Object -Skip 1
$tailR2=$jr2|Select-Object -Skip 1
$tailBase=Avg $tailR1 'left'
$tailAvgR1=Avg $tailR1 'right'
$tailAvgR2=Avg $tailR2 'right'

"COUNT base-r1=$($jr1.Count) base-r2=$($jr2.Count) r1-r2=$($j12.Count)"
"AVG_ALL base=$([math]::Round($avgBase,3)) r1=$([math]::Round($avgR1,3)) r2=$([math]::Round($avgR2,3))"
"IMPROVE_VS_BASE r1=$([math]::Round((($avgBase-$avgR1)/$avgBase)*100,2))% r2=$([math]::Round((($avgBase-$avgR2)/$avgBase)*100,2))%"
"R2_VS_R1 delta_pct=$([math]::Round((($avgR2-$avgR1)/$avgR1)*100,2))%"
"AVG_EXCL_FIRST base=$([math]::Round($tailBase,3)) r1=$([math]::Round($tailAvgR1,3)) r2=$([math]::Round($tailAvgR2,3))"
"EXCL_FIRST_IMPROVE_VS_BASE r1=$([math]::Round((($tailBase-$tailAvgR1)/$tailBase)*100,2))% r2=$([math]::Round((($tailBase-$tailAvgR2)/$tailBase)*100,2))%"
"EXCL_FIRST_R2_VS_R1 delta_pct=$([math]::Round((($tailAvgR2-$tailAvgR1)/$tailAvgR1)*100,2))%"

"R2_SLOWEST_DELTA_TOP5"
($j12 | ForEach-Object { [pscustomobject]@{ ts_code=$_.ts_code; r1=$_.left; r2=$_.right; delta=[math]::Round(($_.right-$_.left),3); delta_pct=[math]::Round((($_.right-$_.left)/$_.left)*100,2) } } | Sort-Object delta_pct -Descending | Select-Object -First 5) | Format-Table -AutoSize
