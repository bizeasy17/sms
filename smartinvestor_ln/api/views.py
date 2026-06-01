from django.shortcuts import render
from rest_framework.decorators import api_view
from rest_framework.response import Response

from analysis.utils.feature_util import read_features_from_yaml
import os

from analysis.models import StockCombinedFeature

root_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# Create your views here.
@api_view(["GET"])
def get_feature_list(request, model, version, ts_code, given_date, freq="D"):
    yaml_path = os.path.join(
        root_path, f"config/features/v{version}/{model}_features.yaml"
    )
    feature_list = read_features_from_yaml(yaml_path)
    feature_qs = StockCombinedFeature.objects.filter(
        ts_code=ts_code, trade_date=given_date, freq=freq
    ).values(*feature_list)
    data = {
        "message": f"Hello from the API! Model: {model}, Version: {version}",
        "features": feature_list,
        "data": list(feature_qs),
    }
    return Response(data)
