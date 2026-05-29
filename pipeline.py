"""Pipeline: apply normalization/transformation rules → modeling-ready unified dataset."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from data_unification.schemas import UNIFIED_REGION_PANEL_COLUMNS
from data_unification.unify import unify_all

from unified_dataset_pipeline.paths import FILES, UNIFICATION_INPUT, ensure_data_dirs
from unified_dataset_pipeline.validators import (
    PipelineValidationReport,
    validate_modeling_dataset,
)

logger = logging.getLogger(__name__)


@dataclass
class PipelineRunReport:
    """Audit trail for one pipeline execution."""

    passed: bool = True
    stages: list[str] = field(default_factory=list)
    metrics: dict[str, int | float | str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def add_stage(self, name: str) -> None:
        self.stages.append(name)

    def fail(self, msg: str) -> None:
        self.passed = False
        self.errors.append(msg)


class UnifiedDatasetPipeline:
    """
    Applies designed normalization and transformation rules (via data_unification)
    to cleaned demographic and facility data, producing a standardized unified
  dataset ready for modeling.
    """

    def __init__(
        self,
        *,
        min_counties: int = 100,
        min_history_years: int = 3,
    ) -> None:
        self.min_counties = min_counties
        self.min_history_years = min_history_years
        ensure_data_dirs()

    def resolve_inputs(self) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """Load cleaned inputs from task input/ or data_unification/data/input/."""
        sources = [
            (FILES["pep_clean"], FILES["senior_clean"], FILES["cms_clean"]),
            (
                UNIFICATION_INPUT / "pep_county_years_clean.csv",
                UNIFICATION_INPUT / "senior_population_clean.csv",
                UNIFICATION_INPUT / "cms_facilities_clean.csv",
            ),
        ]
        for pep_p, sen_p, cms_p in sources:
            if pep_p.exists() and sen_p.exists() and cms_p.exists():
                logger.info("Loading cleaned inputs from %s", pep_p.parent)
                pep = pd.read_csv(pep_p)
                senior = pd.read_csv(sen_p)
                facilities = pd.read_csv(cms_p)
                if pep_p.parent != FILES["pep_clean"].parent:
                    self._copy_inputs_to_task_folder(pep, senior, facilities)
                return pep, senior, facilities

        raise FileNotFoundError(
            "Cleaned input CSVs not found. Run:\n"
            "  python -m data_unification.run\n"
            "or copy pep/senior/cms clean files to unified_dataset_pipeline/data/input/"
        )

    def _copy_inputs_to_task_folder(
        self,
        pep: pd.DataFrame,
        senior: pd.DataFrame,
        facilities: pd.DataFrame,
    ) -> None:
        pep.to_csv(FILES["pep_clean"], index=False)
        senior.to_csv(FILES["senior_clean"], index=False)
        facilities.to_csv(FILES["cms_clean"], index=False)
        logger.info("Copied inputs into %s", FILES["pep_clean"].parent)

    def apply_normalization_and_unification(
        self,
        pep: pd.DataFrame,
        senior: pd.DataFrame,
        facilities: pd.DataFrame,
    ) -> dict[str, pd.DataFrame]:
        """Run normalization rules + join/aggregate transformations."""
        logger.info("Stage: normalize demographics and facilities")
        outputs = unify_all(pep, senior, facilities)
        logger.info("Stage: write staging artifacts")
        outputs["demographics_normalized"].to_csv(FILES["demographics_staged"], index=False)
        outputs["facilities_normalized"].to_csv(FILES["facilities_staged"], index=False)
        outputs["county_supply"].to_csv(FILES["county_supply_staged"], index=False)
        return outputs

    def build_modeling_dataset(self, panel: pd.DataFrame) -> pd.DataFrame:
        """Select canonical columns and sort for downstream model consumption."""
        out = panel[UNIFIED_REGION_PANEL_COLUMNS].copy()
        out = out.sort_values(["county_fips", "year"]).reset_index(drop=True)
        out["county_fips"] = out["county_fips"].astype(str).str.zfill(5)
        out["year"] = pd.to_numeric(out["year"], errors="coerce").astype(int)
        out["total_population"] = pd.to_numeric(out["total_population"], errors="coerce").astype(int)
        out["pop_65_plus"] = pd.to_numeric(out["pop_65_plus"], errors="coerce").astype(int)
        out["facility_count"] = pd.to_numeric(out["facility_count"], errors="coerce").fillna(0).astype(int)
        out["certified_beds"] = pd.to_numeric(out["certified_beds"], errors="coerce").fillna(0).astype(int)
        return out

    def run(self) -> tuple[dict[str, pd.DataFrame], PipelineRunReport, PipelineValidationReport]:
        """Execute full pipeline."""
        run_report = PipelineRunReport()

        run_report.add_stage("resolve_inputs")
        pep, senior, facilities = self.resolve_inputs()
        run_report.metrics["input_pep_rows"] = len(pep)
        run_report.metrics["input_senior_rows"] = len(senior)
        run_report.metrics["input_facility_rows"] = len(facilities)

        run_report.add_stage("normalize_and_unify")
        unified = self.apply_normalization_and_unification(pep, senior, facilities)

        run_report.add_stage("build_modeling_dataset")
        panel = self.build_modeling_dataset(unified["unified_region_panel"])
        supply = unified["county_supply"]

        run_report.add_stage("validate_modeling_ready")
        val_report = validate_modeling_dataset(
            panel,
            min_counties=self.min_counties,
            min_years=self.min_history_years,
        )
        if not val_report.passed:
            run_report.passed = False
            run_report.errors.extend(val_report.errors)

        run_report.add_stage("write_outputs")
        panel.to_csv(FILES["modeling_dataset"], index=False)
        supply.to_csv(FILES["county_supply"], index=False)
        run_report.metrics["output_rows"] = len(panel)
        run_report.metrics["output_counties"] = panel["county_fips"].nunique()

        logger.info(
            "Pipeline %s: %d rows, %d counties → %s",
            "PASSED" if run_report.passed and val_report.passed else "FAILED",
            len(panel),
            panel["county_fips"].nunique(),
            FILES["modeling_dataset"].name,
        )

        unified["modeling_dataset"] = panel
        return unified, run_report, val_report


def write_pipeline_report(
    run_report: PipelineRunReport,
    val_report: PipelineValidationReport,
    path: Path,
) -> None:
    lines = [
        f"PIPELINE PASSED: {run_report.passed and val_report.passed}",
        "",
        "Stages:",
        *[f"  - {s}" for s in run_report.stages],
        "",
        "Run metrics:",
        *[f"  {k}: {v}" for k, v in run_report.metrics.items()],
        "",
        "Validation metrics:",
        *[f"  {k}: {v}" for k, v in val_report.metrics.items()],
        "",
        "Errors:",
        *([f"  - {e}" for e in run_report.errors + val_report.errors] or ["  (none)"]),
        "",
        "Warnings:",
        *([f"  - {w}" for w in val_report.warnings] or ["  (none)"]),
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
