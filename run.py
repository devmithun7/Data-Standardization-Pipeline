#!/usr/bin/env python3
"""
Run the unified dataset pipeline and optional tests.

  python -m unified_dataset_pipeline.run
  python -m unified_dataset_pipeline.run --test
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import yaml

TASK_ROOT = Path(__file__).resolve().parent
ROOT = TASK_ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from unified_dataset_pipeline.paths import FILES, ensure_data_dirs
from unified_dataset_pipeline.pipeline import UnifiedDatasetPipeline, write_pipeline_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("unified_dataset_pipeline")


def _setup_file_logging() -> None:
    ensure_data_dirs()
    fh = logging.FileHandler(FILES["pipeline_log"], encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logging.getLogger().addHandler(fh)


def load_config() -> dict:
    cfg_path = TASK_ROOT / "config.yaml"
    if cfg_path.exists():
        with open(cfg_path, encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {}


def run_pipeline() -> int:
    cfg = load_config()
    val_cfg = cfg.get("validation", {})
    _setup_file_logging()

    pipeline = UnifiedDatasetPipeline(
        min_counties=val_cfg.get("min_counties", 100),
        min_history_years=val_cfg.get("min_history_years", 3),
    )
    _outputs, run_report, val_report = pipeline.run()
    write_pipeline_report(run_report, val_report, FILES["pipeline_report"])

    ok = run_report.passed and val_report.passed
    logger.info(
        "Done. Outputs in %s | Report: %s",
        FILES["modeling_dataset"].parent,
        FILES["pipeline_report"],
    )
    return 0 if ok else 1


def run_tests() -> int:
    from unified_dataset_pipeline.test_pipeline import run_test_suite

    ensure_data_dirs()
    return run_test_suite()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build modeling-ready unified dataset from cleaned inputs"
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Run pipeline tests (runs pipeline first if output missing)",
    )
    parser.add_argument(
        "--test-only",
        action="store_true",
        help="Run tests only without executing pipeline",
    )
    args = parser.parse_args()

    if args.test_only:
        sys.exit(run_tests())

    code = run_pipeline()
    if args.test:
        test_code = run_tests()
        sys.exit(max(code, test_code))
    sys.exit(code)


if __name__ == "__main__":
    main()
