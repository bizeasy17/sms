# FY/Q3 优化实验 v1 运行清单

## 目标

在不改动默认配置的前提下，基于 `15y_20260402_r1` 数据集启动 FY/Q3 优化实验版本。

## 实验配置

- 配置文件: `configs/default.fyq3_opt_v1.yaml`
- 模型版本: `dev_20260403_fyq3_opt_v1`
- 关键开关:
  - `label.fy_yoy`: 开启 FY YoY 稳定化
  - `train.sample_weight.time_decay.enabled`: `true`
  - `train.sample_weight.time_decay.apply_report_types`: `[Q3, FY]`

## 运行命令

在项目根目录执行:

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py train_report_type_models --config configs/default.fyq3_opt_v1.yaml --report-types FY --no-rebuild-dataset
```

如 FY 指标可接受，再跑 Q3:

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py train_report_type_models --config configs/default.fyq3_opt_v1.yaml --report-types Q3 --no-rebuild-dataset
```

## 指标对比命令

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe -c "import json; b='outputs/model_versions/dev_20260331_r3_15y'; n='outputs/model_versions/dev_20260403_fyq3_opt_v1';
for rt in ['FY','Q3']:
  bp=f'{b}/metrics_{rt}.json'; np=f'{n}/metrics_{rt}.json';
  print('\\n==',rt,'==');
  for tag,p in [('BASE',bp),('NEW',np)]:
    d=json.load(open(p,'r',encoding='utf-8'));
    print(tag, 'acc=',d.get('cls_acc'),'auc=',d.get('cls_auc'),'mae=',d.get('reg_mae'),'train=',d.get('cls_train_rows_used'),'test=',d.get('cls_test_rows_used'))"
```

## 回滚

该实验不改 `configs/default.yaml`，直接切回原命令即可。
