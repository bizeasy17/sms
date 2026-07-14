from rest_framework.decorators import api_view
from rest_framework.response import Response

from supply_chain.services.supply_chain_graph import build_supply_chain_graph_payload


@api_view(["GET"])
def get_supply_chain_graph(request):
    """Build supply-chain graph payload for a given stock code."""

    ts_code = str(request.query_params.get("ts_code") or "").strip().upper()
    if not ts_code:
        return Response({"error": "ts_code is required"}, status=400)

    max_nodes_raw = request.query_params.get("max_nodes")
    min_confidence_raw = request.query_params.get("min_confidence")
    include_concepts_raw = request.query_params.get("include_concepts")
    include_layers_raw = request.query_params.get("include_layers")

    try:
        max_nodes = int(max_nodes_raw) if max_nodes_raw not in (None, "") else 120
    except (TypeError, ValueError):
        max_nodes = 120
    max_nodes = max(10, min(max_nodes, 400))

    try:
        min_confidence = (
            float(min_confidence_raw)
            if min_confidence_raw not in (None, "")
            else 0.35
        )
    except (TypeError, ValueError):
        min_confidence = 0.35
    min_confidence = max(0.0, min(min_confidence, 1.0))

    include_concepts = str(include_concepts_raw or "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    include_layers = str(include_layers_raw or "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }

    try:
        payload = build_supply_chain_graph_payload(
            ts_code=ts_code,
            max_nodes=max_nodes,
            min_confidence=min_confidence,
            include_concepts=include_concepts,
            include_layers=include_layers,
        )
        return Response(payload)
    except ValueError as exc:
        return Response({"error": str(exc)}, status=400)
    except Exception as exc:
        return Response({"error": str(exc)}, status=500)
