from django.db.models import F, Q
from rest_framework.decorators import api_view
from rest_framework.response import Response

from users.models import User, UserWatchlist

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def _query_int(request, key, default, minimum, maximum):
    raw_value = request.query_params.get(key, default)
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return None
    if value < minimum or (maximum is not None and value > maximum):
        return None
    return value


def _build_tags(item):
    tags = ["自"]
    if item.hold_a_position:
        tags.append("持")
    if item.observe_only:
        tags.append("注")
    return tags


@api_view(["GET"])
def get_stock_observation_v1(request):
    """Return enabled observation or holding stocks for the current user."""
    user = request.user if request.user.is_authenticated else User.get_admin_user()
    if not user:
        return Response({"detail": "Authentication required."}, status=401)

    limit = _query_int(request, "limit", DEFAULT_LIMIT, 1, MAX_LIMIT)
    offset = _query_int(request, "offset", 0, 0, None)
    if limit is None or offset is None:
        return Response(
            {
                "detail": "limit must be 1-200 and offset must be a non-negative integer.",
            },
            status=400,
        )

    queryset = (
        UserWatchlist.objects.filter(
            user=user,
            is_enabled=True,
        ).filter(Q(observe_only=True) | Q(hold_a_position=True))
        .select_related("corporation")
        .annotate(industry=F("corporation__sw_l3_name"))
        .order_by("ts_code")
    )
    total = queryset.count()
    items = []
    for item in queryset[offset : offset + limit]:
        items.append(
            {
                "ts_code": str(item.ts_code or "").strip().upper(),
                "name": str(item.name or getattr(item.corporation, "name", "") or ""),
                "industry": str(item.industry or ""),
                "tags": _build_tags(item),
                "is_watchlist": True,
                "is_holding": bool(item.hold_a_position),
                "is_observed": bool(item.observe_only),
            }
        )

    return Response(
        {
            "version": "v1",
            "source": "user_watchlist",
            "total": total,
            "items": items,
        }
    )
