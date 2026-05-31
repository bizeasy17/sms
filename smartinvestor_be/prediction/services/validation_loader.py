"""Compatibility shim for migrated valuation config loader.

Core valuation config loader now lives under `valuation.services.validation_loader`.
"""

from valuation.services.validation_loader import *  # noqa: F401,F403
