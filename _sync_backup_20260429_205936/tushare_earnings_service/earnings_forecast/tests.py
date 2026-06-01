import datetime
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
from django.test import SimpleTestCase

from earnings_forecast.management.commands.export_updated_financial_codes import (
	_collect_remote_dividend_codes,
)


class ExportUpdatedFinancialCodesTests(SimpleTestCase):
	@patch("earnings_forecast.management.commands.export_updated_financial_codes.timezone.now")
	@patch("earnings_forecast.management.commands.export_updated_financial_codes.os.getenv")
	def test_collect_remote_dividend_codes_respects_scope_prefix(self, mocked_getenv, mocked_now):
		mocked_getenv.side_effect = lambda key: "dummy-token" if key in ("TUSHARE_TOKEN", "TUSHARE_PRO_TOKEN") else None
		mocked_now.return_value = datetime.datetime(2026, 4, 12, 0, 0, 0, tzinfo=datetime.timezone.utc)

		class FakePro:
			def dividend(self, **kwargs):
				return pd.DataFrame(
					[
						{"ts_code": "300627.SZ"},
						{"ts_code": "600519.SH"},
					]
				)

		fake_ts = SimpleNamespace(
			set_token=lambda _token: None,
			pro_api=lambda: FakePro(),
		)

		with patch.dict(sys.modules, {"tushare": fake_ts}):
			codes = _collect_remote_dividend_codes(
				changed_since=datetime.datetime(2026, 4, 11, 0, 0, 0, tzinfo=datetime.timezone.utc),
				prefixes=["30"],
			)

		self.assertEqual(codes, {"300627.SZ"})
