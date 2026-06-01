from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.health, name="health"),
    path("signal/", views.signal_snapshot, name="signal-snapshot"),
    path("signal/batch/", views.signal_snapshot_batch, name="signal-snapshot-batch"),
    path("prepare/", views.prepare_dataset, name="prepare-dataset"),
    path("train/", views.train_model, name="train-model"),
    path("predict/", views.predict_latest, name="predict-latest"),
]
