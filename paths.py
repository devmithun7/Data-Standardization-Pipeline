"""Directory layout for the unified dataset pipeline task."""

from __future__ import annotations

from pathlib import Path

TASK_ROOT = Path(__file__).resolve().parent
DATA_ROOT = TASK_ROOT / "data"

INPUT_DIR = DATA_ROOT / "input"
STAGING_DIR = DATA_ROOT / "staging"
OUTPUT_DIR = DATA_ROOT / "output"
REPORTS_DIR = DATA_ROOT / "reports"
LOGS_DIR = DATA_ROOT / "logs"

FILES = {
    "pep_clean": INPUT_DIR / "pep_county_years_clean.csv",
    "senior_clean": INPUT_DIR / "senior_population_clean.csv",
    "cms_clean": INPUT_DIR / "cms_facilities_clean.csv",
    "demographics_staged": STAGING_DIR / "demographics_normalized.csv",
    "facilities_staged": STAGING_DIR / "facilities_normalized.csv",
    "county_supply_staged": STAGING_DIR / "county_supply_unified.csv",
    "modeling_dataset": OUTPUT_DIR / "modeling_unified_dataset.csv",
    "county_supply": OUTPUT_DIR / "county_supply.csv",
    "pipeline_report": REPORTS_DIR / "pipeline_report.txt",
    "test_report": REPORTS_DIR / "test_results.txt",
    "pipeline_log": LOGS_DIR / "pipeline.log",
}

# Fallback: read cleaned inputs from data unification task if local input/ is empty
UNIFICATION_INPUT = TASK_ROOT.parent / "data_unification" / "data" / "input"


def ensure_data_dirs() -> None:
    for directory in (INPUT_DIR, STAGING_DIR, OUTPUT_DIR, REPORTS_DIR, LOGS_DIR):
        directory.mkdir(parents=True, exist_ok=True)
