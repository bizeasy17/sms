from django.db import models

# Create your models here.
import uuid
import secrets
from django.contrib.auth.models import AbstractUser
from django.utils import timezone
from django.core.validators import RegexValidator
from datastore.models import Corporation


class User(AbstractUser):
    """
    自定义用户模型，扩展 Django 默认用户模型
    """

    # 基础信息字段
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    last_login_ip = models.GenericIPAddressField(
        blank=True, null=True, verbose_name="最后登录IP"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    # 账户状态
    is_email_verified = models.BooleanField(default=False, verbose_name="邮箱已验证")
    is_phone_verified = models.BooleanField(default=False, verbose_name="手机已验证")
    email_verification_token = models.CharField(
        max_length=255, blank=True, null=True, verbose_name="邮箱验证令牌"
    )
    is_deleted = models.BooleanField(default=False, verbose_name="已删除")
    deleted_at = models.DateTimeField(blank=True, null=True, verbose_name="删除时间")

    @classmethod
    def get_admin_user(cls):
        """获取管理员用户（is_superuser=True）"""
        return cls.objects.filter(
            is_superuser=True, is_active=True, is_deleted=False
        ).first()

    def get_full_name(self):
        """获取完整姓名"""
        full_name = f"{self.first_name} {self.last_name}".strip()
        return full_name if full_name else self.username

    def get_short_name(self):
        """获取简短姓名"""
        return self.first_name or self.username

    def soft_delete(self):
        """软删除用户"""
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.is_active = False
        self.save(update_fields=["is_deleted", "deleted_at", "is_active"])

    def restore(self):
        """恢复已删除的用户"""
        self.is_deleted = False
        self.deleted_at = None
        self.is_active = True
        self.save(update_fields=["is_deleted", "deleted_at", "is_active"])

    def update_last_login_ip(self, ip_address):
        """更新最后登录IP"""
        self.last_login_ip = ip_address
        self.save(update_fields=["last_login_ip"])

    class Meta:
        """Meta options for User model."""

        verbose_name = "用户"
        verbose_name_plural = "用户"
        db_table = "users_user"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["is_active", "is_deleted"]),
        ]


class UserProfile(models.Model):
    """
    用户扩展信息表（如果需要更多字段可以使用）
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")

    # 社交媒体
    linkedin_url = models.URLField(blank=True, verbose_name="LinkedIn")
    twitter_url = models.URLField(blank=True, verbose_name="Twitter")
    website_url = models.URLField(blank=True, verbose_name="个人网站")

    # 通知设置
    email_notifications = models.BooleanField(default=True, verbose_name="邮件通知")
    sms_notifications = models.BooleanField(default=False, verbose_name="短信通知")
    push_notifications = models.BooleanField(default=True, verbose_name="推送通知")

    # 隐私设置
    profile_visibility_choices = [
        ("PUBLIC", "公开"),
        ("FRIENDS", "仅好友"),
        ("PRIVATE", "私密"),
    ]
    profile_visibility = models.CharField(
        max_length=10,
        choices=profile_visibility_choices,
        default="PUBLIC",
        verbose_name="资料可见性",
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "用户资料"
        verbose_name_plural = "用户资料"

    def __str__(self):
        return f"{self.user.email} 的资料"


class UserWatchlist(models.Model):
    """
    用户自选股（关注股票）表
    """

    # 字段定义已优化，无需添加新字段
    id = models.AutoField(primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="添加时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="watchlist")
    ts_code = models.CharField(max_length=20, verbose_name="股票代码")
    name = models.CharField(max_length=100, blank=True, verbose_name="股票名称")
    corporation = models.ForeignKey(
        Corporation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="关联公司",
    )
    hold_a_position = models.BooleanField(default=False, verbose_name="是否持仓")
    is_enabled = models.BooleanField(default=True, verbose_name="是否启用")

    def to_dict(self):
        return {
            "id": self.id,
            "ts_code": self.ts_code,
            "name": self.name,
            "corporation_id": str(self.corporation.id) if self.corporation else None,
            "hold_a_position": self.hold_a_position,
        }

    class Meta:
        verbose_name = "自选股"
        verbose_name_plural = "自选股"
        unique_together = ("user", "ts_code")
        ordering = ["-created_at"]

    @classmethod
    def get_user_watchlist(cls, user):
        """
        获取指定用户的自选股列表
        """
        return cls.objects.filter(user=user, is_enabled=True).order_by("-added_at")

    @classmethod
    def disable_for_user_and_code(cls, user, ts_code):
        """
        将指定用户的指定股票自选股设置为不可用（is_enabled=False）
        """
        return cls.objects.filter(user=user, ts_code=ts_code, is_enabled=True).update(
            is_enabled=False
        )

    @classmethod
    def get_user_hold_positions(cls, user):
        """
        获取指定用户持仓且启用的自选股列表
        """
        return cls.objects.filter(
            user=user, hold_a_position=True, is_enabled=True
        ).order_by("-added_at")

    @classmethod
    def set_stock_as_hold(cls, user, ts_code):
        """
        将指定用户的指定股票标记为持仓（hold_a_position=True）
        """
        return cls.objects.filter(user=user, ts_code=ts_code, is_enabled=True).update(
            hold_a_position=True
        )

    def __str__(self):
        user_email = self.user.email if self.user else "未知用户"
        return f"{user_email} - {self.ts_code}"


class UserStockTag(models.Model):
    """
    用户股票标签表，用于给股票添加特殊关注标签
    """

    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="stock_tags")
    ts_code = models.CharField(max_length=10, verbose_name="股票代码")
    corporation = models.ForeignKey(
        Corporation, on_delete=models.CASCADE, related_name="tags"
    )
    tag = models.CharField(max_length=50, verbose_name="标签")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")
    is_enabled = models.BooleanField(default=True, verbose_name="是否启用")
    is_system_tag = models.BooleanField(default=False, verbose_name="是否系统标签")

    class Meta:
        verbose_name = "股票标签"
        verbose_name_plural = "股票标签"
        unique_together = ("user", "corporation", "tag")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.email} - {self.corporation.name} - {self.tag}"
