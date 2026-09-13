from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.db import models

from market_data.models import Security


class PersonalProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='personal_profile')
    display_name = models.CharField(max_length=128, blank=True, default='')
    email = models.EmailField(max_length=254, blank=True, default='')
    email_verified_at = models.DateTimeField(null=True, blank=True)
    mobile = models.CharField(max_length=32, blank=True, default='')
    mobile_verified_at = models.DateTimeField(null=True, blank=True)
    timezone = models.CharField(max_length=64, default='UTC')
    avatar_url = models.URLField(max_length=512, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class UserSecurityListItem(models.Model):
    class ListType(models.TextChoices):
        WATCHLIST = 'WATCHLIST', 'Watchlist'
        OBSERVATION = 'OBSERVATION', 'Observation'

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='security_list_items')
    security = models.ForeignKey(Security, on_delete=models.PROTECT, related_name='user_list_items')
    list_type = models.CharField(max_length=16, choices=ListType.choices)
    sort_order = models.PositiveIntegerField(default=0)
    note = models.CharField(max_length=512, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'security', 'list_type'],
                name='pu_list_user_sec_type_uq',
            ),
        ]
        indexes = [
            models.Index(fields=['user', 'list_type', 'sort_order'], name='pu_list_user_type_ord_idx'),
        ]


class HoldingPortfolio(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='holding_portfolios')
    name = models.CharField(max_length=128)
    description = models.CharField(max_length=512, blank=True, default='')
    is_default = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'name'], name='pu_port_user_name_uq'),
        ]
        indexes = [
            models.Index(fields=['user', 'archived_at', 'sort_order'], name='pu_port_user_state_idx'),
        ]


class HoldingPosition(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='holding_positions')
    portfolio = models.ForeignKey(HoldingPortfolio, on_delete=models.CASCADE, related_name='positions')
    security = models.ForeignKey(Security, on_delete=models.PROTECT, related_name='holding_positions')
    quantity = models.DecimalField(max_digits=20, decimal_places=4, validators=[MinValueValidator(0)])
    available_quantity = models.DecimalField(
        max_digits=20,
        decimal_places=4,
        validators=[MinValueValidator(0)],
    )
    average_cost = models.DecimalField(max_digits=20, decimal_places=6, validators=[MinValueValidator(0)])
    cost_currency = models.CharField(max_length=3, default='CNY')
    note = models.CharField(max_length=512, blank=True, default='')
    as_of_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['portfolio', 'security'], name='pu_pos_port_sec_uq'),
            models.CheckConstraint(
                condition=models.Q(available_quantity__lte=models.F('quantity')),
                name='pu_pos_avail_lte_qty',
            ),
        ]
        indexes = [
            models.Index(fields=['user', 'portfolio'], name='pu_pos_user_port_idx'),
        ]