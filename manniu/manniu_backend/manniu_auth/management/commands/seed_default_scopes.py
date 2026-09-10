from django.core.management.base import BaseCommand

from manniu_auth.models import AuthRole, AuthScope, RoleScope


class Command(BaseCommand):
    help = 'Create the initial read-only market analysis scopes and role.'

    def handle(self, *args, **options):
        scopes = []
        for code, name, description in (
            ('market_analysis:read', 'Market analysis read', 'Read-only market analysis results.'),
            ('market_analysis:history', 'Market analysis history', 'Date-bounded market analysis history.'),
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
        self.stdout.write(
            self.style.SUCCESS(
                'market analysis scopes initialized '
                f'(scopes={[created for _, created in scopes]}, role={role_created}, '
                f'mappings={[relation_created, history_relation_created]})'
            )
        )