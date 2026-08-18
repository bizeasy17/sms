from django.test import TestCase
from rest_framework.test import APIClient

from users.models import User, UserWatchlist


class StockObservationV1Tests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="opt-observation",
            email="opt-observation@example.com",
            password="test-password",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_returns_observation_and_holding_stocks_with_ordered_tags(self):
        UserWatchlist.objects.create(
            user=self.user,
            ts_code="600001.SH",
            name="观察持仓股",
            hold_a_position=True,
            observe_only=True,
        )
        UserWatchlist.objects.create(
            user=self.user,
            ts_code="000002.SZ",
            name="仅持仓股",
            hold_a_position=True,
            observe_only=False,
        )
        UserWatchlist.objects.create(
            user=self.user,
            ts_code="000001.SZ",
            name="仅自选股",
            observe_only=False,
        )
        UserWatchlist.objects.create(
            user=self.user,
            ts_code="300001.SZ",
            name="已禁用观察股",
            observe_only=True,
            is_enabled=False,
        )

        response = self.client.get("/api/opt/v1/stock-observation/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["version"], "v1")
        self.assertEqual(response.data["source"], "user_watchlist")
        self.assertEqual(response.data["total"], 2)
        self.assertEqual(
            response.data["items"],
            [
                {
                    "ts_code": "000002.SZ",
                    "name": "仅持仓股",
                    "industry": "",
                    "tags": ["自", "持"],
                    "is_watchlist": True,
                    "is_holding": True,
                    "is_observed": False,
                },
                {
                    "ts_code": "600001.SH",
                    "name": "观察持仓股",
                    "industry": "",
                    "tags": ["自", "持", "注"],
                    "is_watchlist": True,
                    "is_holding": True,
                    "is_observed": True,
                }
            ],
        )

    def test_paginates_and_rejects_invalid_parameters(self):
        for code in ("000002.SZ", "000001.SZ"):
            UserWatchlist.objects.create(
                user=self.user,
                ts_code=code,
                name=code,
                hold_a_position=True,
            )

        paged_response = self.client.get("/api/opt/v1/stock-observation/?limit=1&offset=1")
        invalid_response = self.client.get("/api/opt/v1/stock-observation/?limit=0")

        self.assertEqual(paged_response.status_code, 200)
        self.assertEqual(paged_response.data["total"], 2)
        self.assertEqual(paged_response.data["items"][0]["ts_code"], "000002.SZ")
        self.assertEqual(invalid_response.status_code, 400)
