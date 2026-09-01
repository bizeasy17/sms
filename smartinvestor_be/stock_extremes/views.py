from django.db.models import DecimalField, F, OuterRef, Subquery
from rest_framework.decorators import api_view
from rest_framework.response import Response

from datastore.models import StockFundamentalHistory
from stock_extremes.models import StockExtremeSnapshot


FREQUENCY_FIELDS = {
    "daily": ("daily_max_return", "daily_min_return"),
    "weekly": ("weekly_max_return", "weekly_min_return"),
    "monthly": ("monthly_max_return", "monthly_min_return"),
}
SORT_FIELDS = {
    "code": "ts_code",
    "name": "name",
    "daily_max_return": "daily_max_return",
    "daily_min_return": "daily_min_return",
    "weekly_max_return": "weekly_max_return",
    "weekly_min_return": "weekly_min_return",
    "monthly_max_return": "monthly_max_return",
    "monthly_min_return": "monthly_min_return",
    "max_runup": "max_runup",
    "max_drawdown": "max_drawdown",
    "PE": "pe",
    "PB": "pb",
    "PS": "ps",
}


def _positive_int(value, default, maximum=None):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed < 0:
        return None
    if maximum is not None:
        parsed = min(parsed, maximum)
    return parsed


def _serialize(snapshot, frequency):
    payload = {
        "code": snapshot.ts_code,
        "name": snapshot.name,
        "max_runup": float(snapshot.max_runup) if snapshot.max_runup is not None else None,
        "max_drawdown": float(snapshot.max_drawdown) if snapshot.max_drawdown is not None else None,
        "PE": float(snapshot.pe) if snapshot.pe is not None else None,
        "PB": float(snapshot.pb) if snapshot.pb is not None else None,
        "PS": float(snapshot.ps) if snapshot.ps is not None else None,
        "source_start_date": snapshot.source_start_date.isoformat() if snapshot.source_start_date else None,
        "source_end_date": snapshot.source_end_date.isoformat() if snapshot.source_end_date else None,
        "price_type": snapshot.price_type,
        "calculated_at": snapshot.calculated_at.isoformat(),
    }
    selected = FREQUENCY_FIELDS.values() if frequency == "all" else (FREQUENCY_FIELDS[frequency],)
    for fields in selected:
        for field in fields:
            value = getattr(snapshot, field)
            payload[field] = float(value) if value is not None else None
    return payload


@api_view(["GET"])
def get_stock_extremes(request):
    frequency = request.query_params.get("frequency", "all").lower()
    if frequency not in {*FREQUENCY_FIELDS, "all"}:
        return Response({"code": 400, "message": "frequency must be daily, weekly, monthly, or all", "data": None}, status=400)

    limit = _positive_int(request.query_params.get("limit", 100), 100, maximum=1000)
    offset = _positive_int(request.query_params.get("offset", 0), 0)
    if limit is None or limit == 0 or offset is None:
        return Response({"code": 400, "message": "limit must be 1-1000 and offset must be non-negative", "data": None}, status=400)

    sort_by = request.query_params.get("sort_by", "code")
    order = request.query_params.get("order", "asc").lower()
    if sort_by not in SORT_FIELDS or order not in {"asc", "desc"}:
        return Response({"code": 400, "message": "invalid sort_by or order", "data": None}, status=400)

    latest_fundamental = StockFundamentalHistory.objects.filter(
        ts_code=OuterRef("ts_code")
    ).order_by(F("trade_date").desc(nulls_last=True), "-id")
    decimal_output = DecimalField(max_digits=16, decimal_places=4)
    queryset = StockExtremeSnapshot.objects.annotate(
        pe=Subquery(latest_fundamental.values("pe")[:1], output_field=decimal_output),
        pb=Subquery(latest_fundamental.values("pb")[:1], output_field=decimal_output),
        ps=Subquery(latest_fundamental.values("ps")[:1], output_field=decimal_output),
    )
    code = request.query_params.get("code")
    if code:
        queryset = queryset.filter(ts_code=code.upper())

    count = queryset.count()
    ordering = SORT_FIELDS[sort_by]
    if order == "desc":
        ordering = f"-{ordering}"
    rows = queryset.order_by(ordering, "ts_code")[offset:offset + limit]
    return Response({
        "code": 0,
        "message": "success",
        "data": {
            "count": count,
            "limit": limit,
            "offset": offset,
            "results": [_serialize(row, frequency) for row in rows],
        },
    })
