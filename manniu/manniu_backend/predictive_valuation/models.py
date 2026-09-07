from django.db import models
from market_data.models import Security


class PredictiveFinancialFeatureBase(models.Model):
	"""Point-in-time financial features consumed by predictive valuation bundles."""

	end_date = models.DateField()
	ann_date = models.DateField(null=True, blank=True)
	source_as_of_date = models.DateField()
	fiscal_year = models.IntegerField(null=True, blank=True)
	report_type = models.CharField(max_length=16, blank=True)

	revenue = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
	total_revenue = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
	operate_profit = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
	total_profit = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
	n_income = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
	n_income_attr_p = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
	basic_eps = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
	diluted_eps = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)

	roe = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
	roe_dt = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
	roa = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
	q_dt_roe = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
	tr_yoy = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
	netprofit_yoy = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
	grossprofit_margin = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
	netprofit_margin = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
	debt_to_assets = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
	current_ratio = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
	quick_ratio = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
	cash_ratio = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
	assets_turn = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
	ocf_to_or = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)

	total_assets = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
	total_liab = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
	total_hldr_eqy_exc_min_int = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
	money_cap = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
	accounts_receiv = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
	inventories = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
	st_borr = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
	lt_borr = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)

	n_cashflow_act = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
	n_cashflow_inv_act = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
	n_cash_flows_fnc_act = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
	n_incr_cash_cash_equ = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
	raw_payload = models.JSONField(default=dict, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		abstract = True


class PredictiveFinancialFeaturePanel(PredictiveFinancialFeatureBase):
	security = models.ForeignKey(Security, on_delete=models.CASCADE, related_name='predictive_financial_feature_panels')

	class Meta:
		db_table = 'predictive_valuation_financial_feature_panel'
		constraints = [
			models.UniqueConstraint(
				fields=['security', 'end_date', 'report_type', 'source_as_of_date'],
				name='pv_fin_feature_panel_uniq',
			),
		]
		indexes = [
			models.Index(fields=['security', '-source_as_of_date'], name='pv_fin_panel_sec_asof'),
			models.Index(fields=['end_date', 'report_type', 'security'], name='pv_fin_panel_end_type_sec'),
			models.Index(fields=['ann_date', 'security'], name='pv_fin_panel_ann_sec'),
		]


class PredictiveFinancialFeatureLatest(PredictiveFinancialFeatureBase):
	security = models.OneToOneField(Security, on_delete=models.CASCADE, related_name='latest_predictive_financial_feature')

	class Meta:
		db_table = 'predictive_valuation_financial_feature_latest'
		indexes = [
			models.Index(fields=['-end_date'], name='pv_fin_latest_end'),
		]


class PredictiveValuationSnapshot(models.Model):
	"""Append-only predictive valuation result for one security and as-of date."""

	security = models.ForeignKey(Security, on_delete=models.CASCADE, related_name='predictive_valuation_snapshots')
	asof_date = models.DateField(db_index=True)
	horizon = models.CharField(max_length=16, default='1M')
	model_version = models.CharField(max_length=128, db_index=True)
	feature_contract_version = models.CharField(max_length=64)
	artifact_hash = models.CharField(max_length=64, blank=True)
	source_market_date = models.DateField(null=True, blank=True)
	financial_end_date = models.DateField(null=True, blank=True)
	financial_ann_date = models.DateField(null=True, blank=True)
	financial_source_as_of_date = models.DateField(null=True, blank=True)
	financial_report_type = models.CharField(max_length=16, blank=True)
	feature_data_source = models.CharField(max_length=32, blank=True)
	market_regime = models.CharField(max_length=32, blank=True)
	security_regime = models.CharField(max_length=32, blank=True)
	trigger_type = models.CharField(max_length=32, default='MANUAL')
	signal_score = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
	up_probability = models.DecimalField(max_digits=10, decimal_places=8, null=True, blank=True)
	target_return_pct = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
	target_return_low_pct = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
	target_return_high_pct = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
	target_price = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
	target_price_low = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
	target_price_high = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
	target_market_cap = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
	risk_level = models.CharField(max_length=16, default='MEDIUM')
	explain = models.JSONField(default=dict, blank=True)
	raw_result = models.JSONField(default=dict, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		db_table = 'predictive_valuation_snapshot'
		constraints = [
			models.UniqueConstraint(
				fields=['security', 'asof_date', 'horizon', 'model_version', 'feature_contract_version'],
				name='pv_snapshot_uniq',
			),
		]
		indexes = [
			models.Index(fields=['security', '-asof_date'], name='pv_snapshot_sec_asof'),
			models.Index(fields=['model_version', '-created_at'], name='pv_snapshot_model_ct'),
		]


class PredictiveValuationCurrent(models.Model):
	"""Read-optimized latest predictive valuation projection per security and horizon."""

	security = models.ForeignKey(Security, on_delete=models.CASCADE, related_name='current_predictive_valuations')
	horizon = models.CharField(max_length=16, default='1M')
	snapshot = models.ForeignKey(PredictiveValuationSnapshot, on_delete=models.PROTECT, related_name='+')
	model_version = models.CharField(max_length=128, db_index=True)
	asof_date = models.DateField(db_index=True)
	signal_score = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
	target_return_pct = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
	target_price = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
	risk_level = models.CharField(max_length=16, default='MEDIUM')
	market_regime = models.CharField(max_length=32, blank=True)
	security_regime = models.CharField(max_length=32, blank=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		db_table = 'predictive_valuation_current'
		constraints = [
			models.UniqueConstraint(fields=['security', 'horizon', 'model_version'], name='pv_current_uniq'),
		]
		indexes = [
			models.Index(fields=['horizon', '-asof_date'], name='pv_current_horizon_dt'),
		]


class PredictiveValuationEventState(models.Model):
	class Status(models.TextChoices):
		PENDING = 'PENDING', 'Pending'
		RUNNING = 'RUNNING', 'Running'
		SUCCEEDED = 'SUCCEEDED', 'Succeeded'
		FAILED = 'FAILED', 'Failed'

	security = models.ForeignKey(Security, null=True, blank=True, on_delete=models.CASCADE, related_name='predictive_valuation_events')
	event_type = models.CharField(max_length=32, db_index=True)
	event_key = models.CharField(max_length=128, unique=True)
	asof_date = models.DateField(null=True, blank=True, db_index=True)
	payload = models.JSONField(default=dict, blank=True)
	status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True)
	retry_count = models.PositiveIntegerField(default=0)
	last_error = models.TextField(blank=True)
	claimed_at = models.DateTimeField(null=True, blank=True)
	completed_at = models.DateTimeField(null=True, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		db_table = 'predictive_valuation_event_state'
		indexes = [
			models.Index(fields=['status', 'event_type', 'created_at'], name='pv_event_status_type_ct'),
		]


class PredictiveValuationRun(models.Model):
	class Status(models.TextChoices):
		PENDING = 'PENDING', 'Pending'
		RUNNING = 'RUNNING', 'Running'
		SUCCEEDED = 'SUCCEEDED', 'Succeeded'
		FAILED = 'FAILED', 'Failed'

	run_key = models.CharField(max_length=64, unique=True)
	command = models.CharField(max_length=32)
	status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True)
	params = models.JSONField(default=dict, blank=True)
	summary = models.JSONField(default=dict, blank=True)
	error_message = models.TextField(blank=True)
	started_at = models.DateTimeField(null=True, blank=True)
	finished_at = models.DateTimeField(null=True, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		db_table = 'predictive_valuation_run'
		indexes = [
			models.Index(fields=['status', '-created_at'], name='pv_run_status_created'),
		]
