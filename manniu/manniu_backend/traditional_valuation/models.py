from django.db import models


class TraditionalValuationParameterVersion(models.Model):
	parameter_version = models.CharField(max_length=64)
	market = models.CharField(max_length=8, default='CN')
	sw_level = models.CharField(max_length=8, default='GLOBAL')
	sw_code = models.CharField(max_length=32, blank=True)
	sw_name = models.CharField(max_length=128, blank=True)
	effective_from = models.DateField(null=True, blank=True)
	effective_to = models.DateField(null=True, blank=True)
	parameters = models.JSONField(default=dict)
	source_hash = models.CharField(max_length=128)
	engine_compatibility = models.CharField(max_length=32, default='1')
	source_trade_date = models.DateField(null=True, blank=True)
	is_active = models.BooleanField(default=False)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		db_table = 'traditional_valuation_parameter_version'
		constraints = [
			models.UniqueConstraint(
				fields=['market', 'sw_level', 'sw_code', 'parameter_version'],
				name='tv_param_version_uniq',
			),
		]
		indexes = [
			models.Index(fields=['market', 'sw_level', 'sw_code'], name='tv_param_lookup_idx'),
			models.Index(fields=['is_active', '-created_at'], name='tv_param_active_idx'),
		]


class TraditionalValuationSnapshot(models.Model):
	security = models.ForeignKey(
		'market_data.Security', on_delete=models.CASCADE, related_name='traditional_valuation_snapshots'
	)
	asof_date = models.DateField(db_index=True)
	source_trade_date = models.DateField(null=True, blank=True)
	report_type = models.CharField(max_length=16)
	financial_end_date = models.DateField(null=True, blank=True)
	financial_ann_date = models.DateField(null=True, blank=True)
	profit_bucket = models.CharField(max_length=16, default='formal')
	valuation_variant = models.CharField(max_length=128, default='default')
	style_profile = models.CharField(max_length=64, default='baseline')
	parameter_version = models.CharField(max_length=64)
	parameter_source_hash = models.CharField(max_length=128, blank=True)
	valuation_engine_version = models.CharField(max_length=32, default='1.0')
	trigger_type = models.CharField(max_length=32, default='MANUAL')
	current_price = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
	composite_valuation_price_raw = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
	composite_valuation_price_optimized = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
	conservative_valuation_price_raw = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
	conservative_valuation_price_optimized = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
	methods = models.JSONField(default=dict)
	summary = models.JSONField(default=dict)
	provenance = models.JSONField(default=dict)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		db_table = 'traditional_valuation_snapshot'
		constraints = [
			models.UniqueConstraint(
				fields=[
					'security', 'asof_date', 'source_trade_date', 'report_type',
					'financial_end_date', 'profit_bucket', 'valuation_variant',
					'parameter_version', 'valuation_engine_version',
				],
				name='tv_snapshot_identity_uniq',
			),
		]
		indexes = [
			models.Index(fields=['security', '-asof_date'], name='tv_snapshot_sec_dt'),
			models.Index(fields=['report_type', 'profit_bucket', '-asof_date'], name='tv_snapshot_report_dt'),
		]


class TraditionalValuationSnapshotLatest(models.Model):
	security = models.ForeignKey(
		'market_data.Security', on_delete=models.CASCADE, related_name='latest_traditional_valuations'
	)
	report_type = models.CharField(max_length=16)
	profit_bucket = models.CharField(max_length=16, default='formal')
	valuation_variant = models.CharField(max_length=128, default='default')
	style_profile = models.CharField(max_length=64, default='baseline')
	snapshot = models.ForeignKey(TraditionalValuationSnapshot, on_delete=models.PROTECT, related_name='+')
	asof_date = models.DateField(db_index=True)
	source_trade_date = models.DateField(null=True, blank=True)
	composite_valuation_price = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
	conservative_valuation_price = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
	risk_snapshot = models.ForeignKey('TraditionalValuationRiskSnapshot', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
	parameter_version = models.CharField(max_length=64)
	valuation_engine_version = models.CharField(max_length=32, default='1.0')
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		db_table = 'traditional_valuation_snapshot_latest'
		constraints = [
			models.UniqueConstraint(
				fields=['security', 'report_type', 'profit_bucket', 'valuation_variant', 'style_profile'],
				name='tv_snapshot_latest_uniq',
			),
		]
		indexes = [
			models.Index(fields=['report_type', 'profit_bucket', '-asof_date'], name='tv_latest_report_dt'),
		]


class TraditionalValuationVariantSummaryLatest(models.Model):
	security = models.ForeignKey(
		'market_data.Security', on_delete=models.CASCADE, related_name='latest_traditional_valuation_variant_summaries'
	)
	report_type = models.CharField(max_length=16)
	profit_bucket = models.CharField(max_length=16, default='formal')
	valuation_variant = models.CharField(max_length=128, default='default')
	style_profile = models.CharField(max_length=64, default='baseline')
	snapshot = models.ForeignKey(TraditionalValuationSnapshot, on_delete=models.PROTECT, related_name='+')
	asof_date = models.DateField(db_index=True)
	compare_group = models.CharField(max_length=32, blank=True)
	industry_level = models.CharField(max_length=8, blank=True)
	industry_code = models.CharField(max_length=32, blank=True)
	industry_name = models.CharField(max_length=128, blank=True)
	match_rank = models.PositiveSmallIntegerField(null=True, blank=True)
	match_score = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
	composite_valuation_price = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
	conservative_valuation_price = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
	method_coverage = models.PositiveSmallIntegerField(default=0)
	is_active_variant = models.BooleanField(default=False)
	provenance = models.JSONField(default=dict, blank=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		db_table = 'traditional_valuation_variant_summary_latest'
		constraints = [
			models.UniqueConstraint(
				fields=['security', 'report_type', 'profit_bucket', 'valuation_variant', 'style_profile'],
				name='tv_variant_summary_latest_uniq',
			),
		]
		indexes = [
			models.Index(fields=['security', 'report_type', 'profit_bucket'], name='tv_variant_summary_lookup'),
			models.Index(fields=['is_active_variant', '-updated_at'], name='tv_variant_summary_active'),
		]


class TraditionalValuationRiskSnapshot(models.Model):
	snapshot = models.OneToOneField(TraditionalValuationSnapshot, on_delete=models.CASCADE, related_name='risk_snapshot')
	risk_engine_version = models.CharField(max_length=32, default='1.5')
	risk_score = models.DecimalField(max_digits=8, decimal_places=4)
	risk_level = models.CharField(max_length=16)
	confidence = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True)
	factors = models.JSONField(default=dict)
	adjustment = models.JSONField(default=dict)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		db_table = 'traditional_valuation_risk_snapshot'
		indexes = [
			models.Index(fields=['risk_level', '-created_at'], name='tv_risk_level_ct'),
		]


class TraditionalValuationEventState(models.Model):
	class Status(models.TextChoices):
		PENDING = 'PENDING', 'Pending'
		CLAIMED = 'CLAIMED', 'Claimed'
		SUCCEEDED = 'SUCCEEDED', 'Succeeded'
		FAILED = 'FAILED', 'Failed'
		DEAD_LETTER = 'DEAD_LETTER', 'Dead letter'

	security = models.ForeignKey(
		'market_data.Security', null=True, blank=True, on_delete=models.CASCADE,
		related_name='traditional_valuation_events',
	)
	event_type = models.CharField(max_length=32)
	event_key = models.CharField(max_length=128)
	scope_key = models.CharField(max_length=128)
	source_version = models.CharField(max_length=128, blank=True)
	asof_date = models.DateField(null=True, blank=True)
	payload = models.JSONField(default=dict)
	status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
	attempt_count = models.PositiveIntegerField(default=0)
	next_retry_at = models.DateTimeField(null=True, blank=True)
	last_error_code = models.CharField(max_length=64, blank=True)
	last_error_message = models.TextField(blank=True)
	coalesced_event_count = models.PositiveIntegerField(default=0)
	claimed_at = models.DateTimeField(null=True, blank=True)
	completed_at = models.DateTimeField(null=True, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		db_table = 'traditional_valuation_event_state'
		constraints = [
			models.UniqueConstraint(fields=['event_type', 'event_key'], name='tv_event_key_uniq'),
		]
		indexes = [
			models.Index(fields=['status', 'next_retry_at'], name='tv_event_status_retry'),
			models.Index(fields=['scope_key', 'event_type'], name='tv_event_scope_type'),
		]


class TraditionalValuationRun(models.Model):
	class Status(models.TextChoices):
		PENDING = 'PENDING', 'Pending'
		RUNNING = 'RUNNING', 'Running'
		SUCCEEDED = 'SUCCEEDED', 'Succeeded'
		FAILED = 'FAILED', 'Failed'

	run_key = models.CharField(max_length=64, unique=True)
	command = models.CharField(max_length=32)
	scope = models.CharField(max_length=128, blank=True)
	params = models.JSONField(default=dict)
	status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
	planned_count = models.PositiveIntegerField(default=0)
	completed_count = models.PositiveIntegerField(default=0)
	failed_count = models.PositiveIntegerField(default=0)
	summary = models.JSONField(default=dict)
	error_message = models.TextField(blank=True)
	started_at = models.DateTimeField(null=True, blank=True)
	finished_at = models.DateTimeField(null=True, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		db_table = 'traditional_valuation_run'
		indexes = [
			models.Index(fields=['status', '-created_at'], name='tv_run_status_ct'),
		]
