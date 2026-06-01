"""Compatibility shim for migrated valuation logic.

Core valuation implementation now lives under `valuation.services.valuation_engine`.
Keep this module to avoid breaking older imports in prediction.* code paths.
"""

from valuation.services.valuation_engine import *  # noqa: F401,F403
