from __future__ import annotations

from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Build/refresh normalized financial feature snapshot table from endpoint raw tables"

    def handle(self, *args, **options):
        call_command("build_financial_feature_snapshot")
