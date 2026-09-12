import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.http import JsonResponse
from django.test import RequestFactory
from django.test import TestCase
from django.urls import reverse

from api_gateway.permissions import require_scopes
from manniu_auth.models import AuthRole, AuthScope, RoleScope, UserRole


class AuthenticationApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username='analyst', password='Valid-password-123')
        cls.role = AuthRole.objects.create(code='analyst', name='Analyst')
        cls.scope = AuthScope.objects.create(code='market_analysis:read', name='Market read')
        UserRole.objects.create(user=cls.user, role=cls.role)
        RoleScope.objects.create(role=cls.role, scope=cls.scope)

    @patch('manniu_auth.services.token_service._secret', return_value=b'test-secret')
    def test_login_me_and_refresh_rotation(self, _secret):
        login_response = self.client.post(
            reverse('auth-login'),
            data=json.dumps({'username': 'analyst', 'password': 'Valid-password-123'}),
            content_type='application/json',
        )
        self.assertEqual(login_response.status_code, 200)
        payload = login_response.json()['data']
        self.assertEqual(payload['user']['scopes'], ['market_analysis:read'])

        me_response = self.client.get(
            reverse('auth-me'),
            HTTP_AUTHORIZATION=f"Bearer {payload['access_token']}",
        )
        self.assertEqual(me_response.status_code, 200)
        self.assertEqual(me_response.json()['data']['username'], 'analyst')

        refresh_response = self.client.post(
            reverse('auth-token-refresh'),
            data=json.dumps({'refresh_token': payload['refresh_token']}),
            content_type='application/json',
        )
        self.assertEqual(refresh_response.status_code, 200)
        replay_response = self.client.post(
            reverse('auth-token-refresh'),
            data=json.dumps({'refresh_token': payload['refresh_token']}),
            content_type='application/json',
        )
        self.assertEqual(replay_response.status_code, 401)
        self.assertEqual(replay_response.json()['error']['code'], 'REFRESH_TOKEN_REUSED')

        logout_response = self.client.post(
            reverse('auth-logout'),
            HTTP_AUTHORIZATION=f"Bearer {payload['access_token']}",
        )
        self.assertEqual(logout_response.status_code, 200)
        me_after_logout = self.client.get(
            reverse('auth-me'),
            HTTP_AUTHORIZATION=f"Bearer {payload['access_token']}",
        )
        self.assertEqual(me_after_logout.status_code, 401)

    def test_default_scope_command_is_idempotent(self):
        call_command('seed_default_scopes')
        call_command('seed_default_scopes')
        self.assertEqual(AuthScope.objects.filter(code='market_analysis:read').count(), 1)
        role = AuthRole.objects.get(code='market_analysis_reader')
        self.assertEqual(role.role_scopes.count(), 7)

    def test_gateway_scope_boundary(self):
        factory = RequestFactory()

        @require_scopes('market_analysis:read')
        def protected(request):
            return JsonResponse({'ok': True})

        missing = protected(factory.get('/protected'))
        self.assertEqual(missing.status_code, 401)
        self.assertEqual(json.loads(missing.content)['error']['code'], 'AUTHENTICATION_REQUIRED')

        access = type('Access', (), {'scope_snapshot': []})()
        with patch('api_gateway.permissions.authenticate_access_token', return_value=access):
            denied = protected(factory.get('/protected', HTTP_AUTHORIZATION='Bearer raw-token'))
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(json.loads(denied.content)['error']['code'], 'SCOPE_REQUIRED')
