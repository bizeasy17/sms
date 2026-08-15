import json

from django.http import JsonResponse
from django.views.decorators.http import require_POST

from .services import ScreenRequest, screen_financial_performance


@require_POST
def screen(request):
    try:
        payload = json.loads(request.body or "{}")
        request_data = ScreenRequest(
            candidate_codes=payload.get("candidate_codes") or [],
            fiscal_year=int(payload.get("fiscal_year")),
            report_type=str(payload.get("report_type") or "").upper(),
            filters=payload.get("filters") or {},
            sort_by=str((payload.get("sort") or {}).get("by") or "financial_score"),
            sort_order=str((payload.get("sort") or {}).get("order") or "desc"),
        )
        rows = screen_financial_performance(request_data)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({"data": {"items": rows, "total": len(rows)}})