from metrics.models import MetricsScoreSnapshot


def list_score_snapshots(*, filters, ordering, page, page_size):
    queryset = MetricsScoreSnapshot.objects.select_related('security').prefetch_related('dimensions')
    query_filters = {}
    if filters['score_type']:
        query_filters['score_type'] = filters['score_type']
    if filters['ts_code']:
        query_filters['security__ts_code'] = filters['ts_code']
    if filters['name']:
        query_filters['security__name__icontains'] = filters['name']
    if filters['asof_from']:
        query_filters['asof_date__gte'] = filters['asof_from']
    if filters['asof_to']:
        query_filters['asof_date__lte'] = filters['asof_to']
    if filters['financial_end_date']:
        query_filters['financial_end_date'] = filters['financial_end_date']
    if filters['score_status']:
        query_filters['score_status'] = filters['score_status']
    if filters['min_score'] is not None:
        query_filters['score__gte'] = filters['min_score']
    if filters['max_score'] is not None:
        query_filters['score__lte'] = filters['max_score']
    if filters['label']:
        query_filters['label'] = filters['label']
    if filters['dimension_key']:
        query_filters['dimensions__dimension_key'] = filters['dimension_key']
    if filters['dimension_min_score'] is not None:
        query_filters['dimensions__score__gte'] = filters['dimension_min_score']
    if filters['dimension_max_score'] is not None:
        query_filters['dimensions__score__lte'] = filters['dimension_max_score']
    queryset = queryset.filter(**query_filters).distinct().order_by(*ordering)
    total = queryset.count()
    offset = (page - 1) * page_size
    return list(queryset[offset:offset + page_size]), total


def get_score_snapshot(snapshot_id):
    return (
        MetricsScoreSnapshot.objects
        .select_related('security')
        .prefetch_related('dimensions')
        .filter(pk=snapshot_id)
        .first()
    )