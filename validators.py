"""Validation rules for modeling-ready unified datasets."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from data_unification.schemas import UNIFIED_REGION_PANEL_COLUMNS, validate_unified_panel_schema


@dataclass
class PipelineValidationReport:
    passed: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metrics: dict[str, float | int] = field(default_factory=dict)

    def fail(self, msg: str) -> None:
        self.passed = False
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)


def validate_modeling_dataset(
    panel: pd.DataFrame,
    *,
    min_counties: int = 100,
    min_years: int = 3,
    max_null_rate_pop_65: float = 0.05,
) -> PipelineValidationReport:
    """Check unified panel is ready for downstream forecasting features."""
    report = PipelineValidationReport()

    schema_errors = validate_unified_panel_schema(panel)
    for err in schema_errors:
        report.fail(err)

    missing_cols = set(UNIFIED_REGION_PANEL_COLUMNS) - set(panel.columns)
    if missing_cols:
        report.fail(f"Modeling dataset missing columns: {sorted(missing_cols)}")

    n_counties = panel["county_fips"].nunique()
    report.metrics["counties"] = int(n_counties)
    if n_counties < min_counties:
        report.fail(f"Too few counties: {n_counties} < {min_counties}")

    n_years = panel["year"].nunique()
    report.metrics["years"] = int(n_years)
    if n_years < min_years:
        report.fail(f"Too few years: {n_years} < {min_years}")

    null_rate = panel["pop_65_plus"].isna().mean()
    report.metrics["pop_65_null_rate"] = round(null_rate, 4)
    if null_rate > max_null_rate_pop_65:
        report.fail(f"pop_65_plus null rate {null_rate:.2%} exceeds {max_null_rate_pop_65:.2%}")

    if (panel["total_population"] < 0).any():
        report.fail("Negative total_population values")
    if (panel["pop_65_plus"] < 0).any():
        report.fail("Negative pop_65_plus values")
    if (panel["certified_beds"] < 0).any():
        report.fail("Negative certified_beds values")

    # Counties with enough history for time-series models
    hist = panel.groupby("county_fips")["year"].count()
    modelable = int((hist >= min_years).sum())
    report.metrics["counties_with_min_history"] = modelable
    if modelable < min_counties * 0.8:
        report.warn(
            f"Only {modelable} counties have >={min_years} years "
            f"(expected ~{min_counties})"
        )

    return report
