from rest_framework.decorators import api_view
from rest_framework.response import Response
from stockdata.models import (
    StockCostHistory,
    StockFundamentalHistory,
    StockTradingHistory,
)


# Create your views here.
@api_view(["GET"])
def get_stock_trading_history(request, ts_code, freq, date_from, limit):
    if date_from:
        data = list(
            StockTradingHistory.objects.filter(
                trade_date__lte=date_from, ts_code=ts_code, freq=freq
            )
            .values()
            .order_by("-trade_date")[:limit]
        )
        return Response(data)
    else:
        return Response({"error": "date_from parameter is required."}, status=400)


@api_view(["GET"])
def get_all_trading_history_not_pulled(request, freq):
    data = list(
        StockTradingHistory.objects.filter(freq=freq, is_pulled_by_client=False)
        .values()
        .order_by("ts_code", "trade_date")
    )
    if data:
        return Response(data)
    return Response({"message": "No unpulled trading history found."}, status=404)


@api_view(["PUT", "UPDATE", "POST"])
def update_trading_history_pull_status(request, freq):
    ts_codes = request.data.get("ts_codes")
    if not ts_codes:
        return Response({"error": "ts_codes parameter is required."}, status=400)

    ts_code_list = [code.strip() for code in ts_codes.split(",") if code.strip()]
    updated_count = StockTradingHistory.objects.filter(
        freq=freq, ts_code__in=ts_code_list, is_pulled_by_client=False
    ).update(is_pulled_by_client=True)
    return Response({"updated_count": updated_count}, status=200)


@api_view(["GET"])
def get_trading_history_from(request, ts_code, freq, date_from):
    if date_from:
        data = list(
            StockTradingHistory.objects.filter(
                trade_date__gte=date_from, ts_code=ts_code, freq=freq
            )
            .values()
            .order_by("trade_date")
        )
        return Response(data)
    else:
        return Response({"error": "date_from parameter is required."}, status=400)


@api_view(["GET"])
def get_stock_fundamental_history(request, ts_code, freq, date_from, limit):
    if date_from:
        data = list(
            StockFundamentalHistory.objects.filter(
                trade_date__lte=date_from, ts_code=ts_code, freq=freq
            )
            .values()
            .order_by("-trade_date")[:limit]
        )
        return Response(data)
    else:
        return Response({"error": "date_from parameter is required."}, status=400)


@api_view(["GET"])
def get_all_fundamental_history_not_pulled(request, freq):
    data = list(
        StockFundamentalHistory.objects.filter(freq=freq, is_pulled_by_client=False)
        .values()
        .order_by("ts_code", "trade_date")
    )
    if data:
        return Response(data)
    return Response({"message": "No unpulled fundamental history found."}, status=404)


@api_view(["PUT", "UPDATE", "POST"])
def update_fundamental_history_pull_status(request, freq):
    ts_codes = request.data.get("ts_codes")
    if not ts_codes:
        return Response({"error": "ts_codes parameter is required."}, status=400)

    ts_code_list = [code.strip() for code in ts_codes.split(",") if code.strip()]
    updated_count = StockFundamentalHistory.objects.filter(
        freq=freq, ts_code__in=ts_code_list, is_pulled_by_client=False
    ).update(is_pulled_by_client=True)
    return Response({"updated_count": updated_count})


@api_view(["GET"])
def get_fundamental_history_from(request, ts_code, freq, date_from):
    if date_from:
        data = list(
            StockFundamentalHistory.objects.filter(
                trade_date__gte=date_from, ts_code=ts_code, freq=freq
            )
            .values()
            .order_by("trade_date")
        )
        return Response(data)
    else:
        return Response({"error": "date_from parameter is required."}, status=400)


@api_view(["GET"])
def get_stock_cost_history(request, ts_code, freq, date_from, limit):
    if date_from:
        data = list(
            StockCostHistory.objects.filter(
                trade_date__lte=date_from, ts_code=ts_code, freq=freq
            )
            .values()
            .order_by("-trade_date")[:limit]
        )
        return Response(data)
    else:
        return Response({"error": "date_from parameter is required."}, status=400)


@api_view(["GET"])
def get_all_cost_history_not_pulled(request, freq):
    data = list(
        StockCostHistory.objects.filter(freq=freq, is_pulled_by_client=False)
        .values()
        .order_by("ts_code", "trade_date")
    )
    if data:
        return Response(data)
    return Response({"message": "No unpulled cost history found."}, status=404)


@api_view(["PUT", "UPDATE", "POST"])
def update_cost_history_pull_status(request, freq):
    ts_codes = request.data.get("ts_codes")
    if not ts_codes:
        return Response({"error": "ts_codes parameter is required."}, status=400)

    ts_code_list = [code.strip() for code in ts_codes.split(",") if code.strip()]
    updated_count = StockCostHistory.objects.filter(
        freq=freq, ts_code__in=ts_code_list, is_pulled_by_client=False
    ).update(is_pulled_by_client=True)
    return Response({"updated_count": updated_count})


@api_view(["GET"])
def get_cost_history_from(request, ts_code, freq, date_from):
    if date_from:
        data = list(
            StockCostHistory.objects.filter(
                trade_date__gte=date_from, ts_code=ts_code, freq=freq
            )
            .values()
            .order_by("trade_date")
        )
        return Response(data)
    else:
        return Response({"error": "date_from parameter is required."}, status=400)


# def get_stock_features(request, ts_code, freq, feature_type):
#     try:
#         records = StockFeature.objects.filter(
#             ts_code=ts_code, freq=freq, feature_type=feature_type
#         ).order_by("-trade_date")
#         data = [{**r.to_dict()} for r in records]
#         if not data:
#             return Response(
#                 {"error": "No stock features found for given ts_code and freq."},
#                 status=404,
#             )
#         return Response(
#             {"data": data, "ts_code": ts_code, "freq": freq, "feature_type": feature_type}
#         )
#     except Exception as e:
#         return Response({"error": str(e)}, status=500)


# def get_all_stock_features(request, freq, feature_type, from_index, to_index):
#     try:
#         records = StockFeature.objects.filter(
#             freq=freq, feature_type=feature_type
#         ).order_by("-trade_date")[from_index:to_index]
#         data = [{**r.to_dict()} for r in records]
#         if not data:
#             return Response(
#                 {"error": "No stock features found for given freq and feature_type."},
#                 status=404,
#             )
#         return Response(
#             {"data": data, "freq": freq, "feature_type": feature_type}
#         )
#     except Exception as e:
#         return Response({"error": str(e)}, status=500)
