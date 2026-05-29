"""Tests for the unified dataset pipeline."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

TASK_ROOT = Path(__file__).resolve().parent
ROOT = TASK_ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_unification.schemas import UNIFIED_REGION_PANEL_COLUMNS, validate_unified_panel_schema

from unified_dataset_pipeline.paths import FILES, ensure_data_dirs
from unified_dataset_pipeline.pipeline import UnifiedDatasetPipeline
from unified_dataset_pipeline.validators import validate_modeling_dataset


class TestUnifiedDatasetPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_data_dirs()
        if not FILES["modeling_dataset"].exists():
            pipeline = UnifiedDatasetPipeline()
            try:
                pipeline.run()
            except FileNotFoundError as exc:
                raise unittest.SkipTest(str(exc)) from exc

    def test_output_file_exists(self) -> None:
        self.assertTrue(FILES["modeling_dataset"].exists())

    def test_schema_columns(self) -> None:
        df = pd.read_csv(FILES["modeling_dataset"], dtype={"county_fips": str})
        for col in UNIFIED_REGION_PANEL_COLUMNS:
            self.assertIn(col, df.columns, f"Missing column {col}")

    def test_schema_validation(self) -> None:
        df = pd.read_csv(FILES["modeling_dataset"], dtype={"county_fips": str})
        df["county_fips"] = df["county_fips"].str.zfill(5)
        errors = validate_unified_panel_schema(df)
        self.assertEqual(errors, [], f"Schema errors: {errors}")

    def test_county_fips_format(self) -> None:
        df = pd.read_csv(FILES["modeling_dataset"], dtype={"county_fips": str})
        df["county_fips"] = df["county_fips"].str.zfill(5)
        self.assertTrue((df["county_fips"].str.len() == 5).all())

    def test_population_non_negative(self) -> None:
        df = pd.read_csv(FILES["modeling_dataset"])
        self.assertGreaterEqual(df["total_population"].min(), 0)
        self.assertGreaterEqual(df["pop_65_plus"].min(), 0)

    def test_modeling_validation_passes(self) -> None:
        df = pd.read_csv(FILES["modeling_dataset"], dtype={"county_fips": str})
        df["county_fips"] = df["county_fips"].str.zfill(5)
        report = validate_modeling_dataset(df)
        self.assertTrue(report.passed, report.errors)

    def test_minimum_county_coverage(self) -> None:
        df = pd.read_csv(FILES["modeling_dataset"])
        self.assertGreaterEqual(df["county_fips"].nunique(), 100)

    def test_staging_artifacts_exist(self) -> None:
        self.assertTrue(FILES["demographics_staged"].exists())
        self.assertTrue(FILES["facilities_staged"].exists())
        self.assertTrue(FILES["county_supply_staged"].exists())

    def test_pipeline_report_exists(self) -> None:
        self.assertTrue(FILES["pipeline_report"].exists())
        text = FILES["pipeline_report"].read_text(encoding="utf-8")
        self.assertIn("PIPELINE PASSED", text)


def run_test_suite() -> int:
    """Run tests and write report to data/reports/test_results.txt."""
    ensure_data_dirs()
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    lines = [
        f"Tests run: {result.testsRun}",
        f"Failures: {len(result.failures)}",
        f"Errors: {len(result.errors)}",
        f"Skipped: {len(result.skipped)}",
        "",
    ]
    for test, trace in result.failures + result.errors:
        lines.append(f"FAILED: {test}")
        lines.append(trace)
    FILES["test_report"].write_text("\n".join(lines), encoding="utf-8")

    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_test_suite())
