from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass
class DataCoverage:
    sample_count: int = 0
    start_date: date | None = None
    end_date: date | None = None
    missing_indices: list[str] = field(default_factory=list)
    source_ts_codes: dict[str, str] = field(default_factory=dict)

    def as_dict(self):
        return {
            'sample_count': self.sample_count,
            'start_date': self.start_date,
            'end_date': self.end_date,
            'missing_indices': list(self.missing_indices),
            'source_ts_codes': dict(self.source_ts_codes),
        }


@dataclass
class DomainResult:
    status: str
    data: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    coverage: DataCoverage = field(default_factory=DataCoverage)

    def as_dict(self):
        return {
            'status': self.status,
            'data': self.data,
            'warnings': list(self.warnings),
            'coverage': self.coverage.as_dict(),
        }