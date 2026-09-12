from django.core.management.base import BaseCommand

from manniu_auth.models import AuthRole, AuthScope, RoleScope


class Command(BaseCommand):
    help = 'Create the initial read-only market analysis scopes and role.'

    def handle(self, *args, **options):
        scopes = []
        for code, name, description in (
            ('market_analysis:read', 'Market analysis read', 'Read-only market analysis results.'),
            ('market_analysis:history', 'Market analysis history', 'Date-bounded market analysis history.'),
            ('market_sentiment:read', 'Market sentiment read', 'Read-only market sentiment snapshots and rankings.'),
            ('market_sentiment:history_read', 'Market sentiment history', 'Date-bounded market sentiment history.'),
            ('predictive_valuation:read', 'Predictive valuation read', 'Read-only predictive valuation results.'),
            ('predictive_valuation:history_read', 'Predictive valuation history', 'Date-bounded predictive valuation history.'),
            ('predictive_valuation:operator_read', 'Predictive valuation operator read', 'Read predictive valuation diagnostics.'),
            ('valuation:diagnostics_read', 'Valuation diagnostics read', 'Read valuation method and provenance diagnostics.'),
        ):
            scope, scope_created = AuthScope.objects.get_or_create(
                code=code,
                defaults={'name': name, 'description': description, 'is_system': True},
            )
            scopes.append((scope, scope_created))
        role, role_created = AuthRole.objects.get_or_create(
            code='market_analysis_reader',
            defaults={
                'name': 'Market analysis reader',
                'description': 'Default read-only market analysis role.',
                'is_system': True,
            },
        )
        read_scope = next(scope for scope, _ in scopes if scope.code == 'market_analysis:read')
        relation_created = RoleScope.objects.get_or_create(role=role, scope=read_scope)[1]
        history_scope = next(scope for scope, _ in scopes if scope.code == 'market_analysis:history')
        history_relation_created = RoleScope.objects.get_or_create(role=role, scope=history_scope)[1]
        sentiment_scope = next(scope for scope, _ in scopes if scope.code == 'market_sentiment:read')
        sentiment_relation_created = RoleScope.objects.get_or_create(role=role, scope=sentiment_scope)[1]
        sentiment_history_scope = next(scope for scope, _ in scopes if scope.code == 'market_sentiment:history_read')
        sentiment_history_relation_created = RoleScope.objects.get_or_create(
            role=role, scope=sentiment_history_scope,
        )[1]
        predictive_scope = next(scope for scope, _ in scopes if scope.code == 'predictive_valuation:read')
        predictive_relation_created = RoleScope.objects.get_or_create(role=role, scope=predictive_scope)[1]
        predictive_history_scope = next(scope for scope, _ in scopes if scope.code == 'predictive_valuation:history_read')
        predictive_history_relation_created = RoleScope.objects.get_or_create(
            role=role, scope=predictive_history_scope,
        )[1]
        predictive_operator_scope = next(scope for scope, _ in scopes if scope.code == 'predictive_valuation:operator_read')
        predictive_operator_relation_created = RoleScope.objects.get_or_create(
            role=role, scope=predictive_operator_scope,
        )[1]
        self.stdout.write(
            self.style.SUCCESS(
                'market analysis scopes initialized '
                f'(scopes={[created for _, created in scopes]}, role={role_created}, '
                f'mappings={[relation_created, history_relation_created, sentiment_relation_created, sentiment_history_relation_created, predictive_relation_created, predictive_history_relation_created, predictive_operator_relation_created]}'
            )
        )