from django.urls import path

from .views import (
    list_backtest_batch_candidates,
    get_backtest_run_detail,
    health,
    list_backtest_runs,
    predict_latest,
    prepare_dataset,
    run_backtest,
    signal_snapshot,
    signal_snapshot_batch,
    train_model,
)

urlpatterns = [
    path("health/", health, name="health"),
    path("signal/", signal_snapshot, name="signal-snapshot"),
    path("signal/batch/", signal_snapshot_batch, name="signal-snapshot-batch"),
    path("backtest/run/", run_backtest, name="run-backtest"),
    path("backtest/batch-candidates/", list_backtest_batch_candidates, name="list-backtest-batch-candidates"),
    path("backtest/runs/", list_backtest_runs, name="list-backtest-runs"),
    path("backtest/runs/<int:run_id>/", get_backtest_run_detail, name="get-backtest-run-detail"),
    path("prepare/", prepare_dataset, name="prepare-dataset"),
    path("train/", train_model, name="train-model"),
    path("predict/", predict_latest, name="predict-latest"),
]
