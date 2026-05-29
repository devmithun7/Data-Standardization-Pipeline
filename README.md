# Unified Dataset Pipeline Task

Develop and test a pipeline that applies the **normalization and transformation rules** designed in `data_unification/` to cleaned facility and demographic datasets, producing a **standardized unified dataset ready for modeling**.

This is a **standalone task folder**. All pipeline code, tests, reports, and output data live under `unified_dataset_pipeline/`.

---

## Table of contents

- [Task objective](#task-objective)
- [Entity-relationship diagram](#entity-relationship-diagram)
- [Prerequisites](#prerequisites)
- [Folder structure](#folder-structure)
- [Data folder layout](#data-folder-layout)
- [Quick start](#quick-start)
- [Pipeline stages](#pipeline-stages)
- [Module reference](#module-reference)
- [Validation rules](#validation-rules)
- [Testing](#testing)
- [Outputs](#outputs)
- [Output schema](#output-schema)
- [Configuration](#configuration)
- [Integration with the project](#integration-with-the-project)
- [Troubleshooting](#troubleshooting)
- [Submission checklist](#submission-checklist)

---

## Task objective

| Requirement | How it is met |
|-------------|----------------|
| Apply normalization/transformation rules | Calls `data_unification.unify_all()` |
| Input: cleaned facility + demographic data | Loads from `data/input/` or `data_unification/data/input/` |
| Output: standardized unified dataset | `data/output/modeling_unified_dataset.csv` |
| Pipeline implementation | `pipeline.py`, `UnifiedDatasetPipeline` class |
| Test the pipeline | `test_pipeline.py` — 9 unit tests |
| Auditable run | `data/reports/pipeline_report.txt`, `data/logs/pipeline.log` |

**Primary deliverable:** `modeling_unified_dataset.csv` — county-year panel with canonical columns, validated for downstream forecasting in `src/models/`.

---

## Entity-relationship diagram

End-to-end model: **cleaned inputs** → **staging** → **modeling output** → (optional) **training features** in the main project.

```
  data/input/                    data/staging/                 data/output/
  -------------                  --------------                ---------------

  +-------------+                +----------------------+
  | PEP_INPUT   |--------------->| DEMOGRAPHICS_STAGED  |
  +-------------+                +----------+-----------+
  +-------------+                           |
  |SENIOR_INPUT |-------------------------->+
  +-------------+                           |
                                            v
  +-------------+                +----------------------+     +------------------------+
  | CMS_INPUT   |--------------->| FACILITIES_STAGED    |     | MODELING_UNIFIED       |
  +-------------+                +----------+-----------+     | DATASET                |
                                 | COUNTY_SUPPLY_STAGED |---->| (county_fips + year)   |
                                 +----------------------+     +-----------+------------+
                                                                            |
                                                                            | src/models/
                                                                            v
                                                                +------------------------+
                                                                | TRAINING_FEATURES      |
                                                                +------------------------+
```

### Pipeline vs. data folders

| ER entity | File location |
|-----------|----------------|
| `PEP_INPUT`, `SENIOR_INPUT`, `CMS_INPUT` | `data/input/*.csv` |
| `DEMOGRAPHICS_STAGED`, `FACILITIES_STAGED`, `COUNTY_SUPPLY_STAGED` | `data/staging/*.csv` |
| `MODELING_UNIFIED_DATASET` | `data/output/modeling_unified_dataset.csv` |
| `TRAINING_FEATURES` | `data/processed/training_features.csv` (main project pipeline) |

---

## Prerequisites

### Upstream tasks (in order)

1. **Ingest + clean** — `src/ingest/`, `src/clean/`
2. **Data unification (design)** — `data_unification/` (schemas, rules, `unify_all()`)

### Minimum input files

Either in `unified_dataset_pipeline/data/input/` **or** `data_unification/data/input/`:

| File | Description |
|------|-------------|
| `pep_county_years_clean.csv` | Cleaned Census PEP county-year population |
| `senior_population_clean.csv` | Cleaned 65+ population by county |
| `cms_facilities_clean.csv` | Cleaned CMS nursing home providers |

Generate inputs easily:

```bash
python -m data_unification.run
```

### Python environment

```bash
pip install -r requirements.txt
```

No extra test dependencies — uses built-in `unittest`.

---

## Folder structure

```
unified_dataset_pipeline/
├── README.md                 # This documentation
├── config.yaml               # Validation thresholds
├── paths.py                  # Task data paths
├── pipeline.py               # UnifiedDatasetPipeline
├── validators.py             # Modeling-readiness checks
├── test_pipeline.py          # Unit test suite
├── run.py                    # CLI (run / test)
├── __init__.py
└── data/
    ├── README.md
    ├── input/                # Cleaned source tables
    ├── staging/              # Intermediate normalized tables
    ├── output/               # ★ Final modeling dataset
    ├── reports/              # Pipeline + test reports
    └── logs/                 # pipeline.log
```

---

## Data folder layout

```
data/
├── input/
│   ├── pep_county_years_clean.csv
│   ├── senior_population_clean.csv
│   └── cms_facilities_clean.csv
├── staging/
│   ├── demographics_normalized.csv
│   ├── facilities_normalized.csv
│   └── county_supply_unified.csv
├── output/
│   ├── modeling_unified_dataset.csv    ← PRIMARY DELIVERABLE
│   └── county_supply.csv
├── reports/
│   ├── pipeline_report.txt
│   └── test_results.txt
└── logs/
    └── pipeline.log
```

---

## Quick start

From **project root**:

```bash
# 1. Ensure cleaned inputs exist (if not already)
python -m data_unification.run

# 2. Run pipeline (copies inputs, unifies, validates, writes outputs)
python -m unified_dataset_pipeline.run

# 3. Run pipeline + full test suite
python -m unified_dataset_pipeline.run --test
```

### CLI options

| Command | Description |
|---------|-------------|
| `python -m unified_dataset_pipeline.run` | Run pipeline only |
| `python -m unified_dataset_pipeline.run --test` | Run pipeline, then tests |
| `python -m unified_dataset_pipeline.run --test-only` | Tests only (requires existing output) |
| `python -m unified_dataset_pipeline.test_pipeline` | Same as `--test-only` |

Exit code `0` = success; `1` = validation or test failure.

---

## Pipeline stages

```
┌─────────────────────────────────────────────────────────────────┐
│              UnifiedDatasetPipeline.run()                        │
└─────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────┐
│ 1. resolve_inputs   │  Load cleaned CSVs; copy to data/input/
└─────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│ 2. normalize_and_unify                  │  data_unification.unify_all()
│    • normalize PEP, senior, CMS           │
│    • merge demographics                   │
│    • join facilities → county supply      │
│    • build unified region panel           │
└─────────────────────────────────────────┘
         │
         ▼
┌─────────────────────┐
│ 3. build_modeling_  │  Canonical columns, int dtypes, sort
│    dataset          │
└─────────────────────┘
         │
         ▼
┌─────────────────────┐
│ 4. validate_modeling│  Schema, nulls, county coverage
│    _ready           │
└─────────────────────┘
         │
         ▼
┌─────────────────────┐
│ 5. write_outputs    │  output/, staging/, reports/
└─────────────────────┘
```

### Stage details

| Stage | Class method | Output |
|-------|--------------|--------|
| Resolve inputs | `resolve_inputs()` | In-memory DataFrames; saves to `data/input/` |
| Normalize & unify | `apply_normalization_and_unification()` | Calls `unify_all()`; writes `data/staging/` |
| Build modeling dataset | `build_modeling_dataset()` | Panel with `UNIFIED_REGION_PANEL_COLUMNS` |
| Validate | `validate_modeling_dataset()` | Pass/fail + metrics |
| Write | `run()` | `modeling_unified_dataset.csv`, `county_supply.csv` |

---

## Module reference

### `pipeline.py`

```python
from unified_dataset_pipeline.pipeline import UnifiedDatasetPipeline

pipeline = UnifiedDatasetPipeline(min_counties=100, min_history_years=3)
outputs, run_report, val_report = pipeline.run()
panel = outputs["modeling_dataset"]
```

`PipelineRunReport` — stages executed, row counts, errors.

### `validators.py`

`validate_modeling_dataset(panel)` checks:

- Canonical schema (`data_unification.schemas`)
- Minimum county count (default 100)
- Minimum year span (default 3)
- `pop_65_plus` null rate ≤ 5%
- Non-negative populations and beds
- Counties with enough history for time-series models (warning if low)

### `paths.py`

Central path constants — always use `FILES["modeling_dataset"]` etc. instead of hard-coded paths.

### `run.py`

CLI wrapper; configures file logging to `data/logs/pipeline.log`.

---

## Validation rules

Configured in `config.yaml`:

```yaml
validation:
  min_counties: 100
  min_history_years: 3
  max_null_rate_pop_65: 0.05
```

| Check | Failure if |
|-------|------------|
| Schema | Missing columns or invalid FIPS length |
| County coverage | &lt; 100 counties |
| Year span | &lt; 3 distinct years |
| Null 65+ rate | &gt; 5% null `pop_65_plus` |
| Value sanity | Negative population or beds |

Results written to `data/reports/pipeline_report.txt`.

---

## Testing

### Test suite (`test_pipeline.py`)

| Test | Verifies |
|------|----------|
| `test_output_file_exists` | `modeling_unified_dataset.csv` created |
| `test_schema_columns` | All canonical columns present |
| `test_schema_validation` | `validate_unified_panel_schema()` passes |
| `test_county_fips_format` | 5-digit FIPS strings |
| `test_population_non_negative` | Populations ≥ 0 |
| `test_modeling_validation_passes` | Full modeling validation |
| `test_minimum_county_coverage` | ≥ 100 counties |
| `test_staging_artifacts_exist` | Staging CSVs written |
| `test_pipeline_report_exists` | Report contains `PIPELINE PASSED: True` |

### Run tests

```bash
python -m unified_dataset_pipeline.run --test
```

Results summary: `data/reports/test_results.txt`

Expected: **9 tests, 0 failures**.

---

## Outputs

| File | Typical size | Purpose |
|------|--------------|---------|
| `data/output/modeling_unified_dataset.csv` | 15,720 rows | **Feed to forecasting / features** |
| `data/output/county_supply.csv` | 2,786 rows | County-level bed supply |
| `data/staging/demographics_normalized.csv` | 15,720 rows | Audit: normalized demographics |
| `data/staging/facilities_normalized.csv` | 14,690 rows | Audit: normalized facilities |
| `data/staging/county_supply_unified.csv` | 2,786 rows | Audit: aggregated supply |
| `data/reports/pipeline_report.txt` | — | Run metrics + pass/fail |
| `data/reports/test_results.txt` | — | Test counts (after `--test`) |
| `data/logs/pipeline.log` | — | Detailed log |

---

## Output schema

`modeling_unified_dataset.csv` columns (from `data_unification.schemas.UNIFIED_REGION_PANEL_COLUMNS`):

| Column | Type | Description |
|--------|------|-------------|
| `county_fips` | str | 5-digit county FIPS |
| `state_abbr` | str | State code |
| `county_name` | str | County name |
| `year` | int | Year |
| `total_population` | int | Total county population |
| `pop_65_plus` | int | Population aged 65+ |
| `pct_pop_65_plus` | float | Share of population 65+ |
| `facility_count` | int | Nursing homes in county |
| `certified_beds` | int | Sum of certified beds |
| `avg_residents` | float | Sum of average residents |
| `beds_per_1000_seniors` | float | Supply intensity |
| `penetration_rate` | float | Residents / 65+ pop |
| `occupancy_rate` | float | Residents / beds |
| `pop_65_growth_yoy` | float | YoY 65+ growth |
| `total_pop_growth_yoy` | float | YoY total pop growth |

### Downstream usage

```python
import pandas as pd
from src.models.features import add_model_features, get_training_frame

panel = pd.read_csv(
    "unified_dataset_pipeline/data/output/modeling_unified_dataset.csv",
    dtype={"county_fips": str},
)
panel["county_fips"] = panel["county_fips"].str.zfill(5)
panel = add_model_features(panel)
train = get_training_frame(panel, min_history_years=3)
```

Or use project pipeline:

```bash
python -m src.pipeline.run
```

---

## Configuration

`unified_dataset_pipeline/config.yaml`:

```yaml
validation:
  min_counties: 100
  min_history_years: 3
  max_null_rate_pop_65: 0.05
```

Project cleaning/unification settings remain in `config/settings.yaml` (used when inputs are loaded from `data/raw/`).

---

## Integration with the project

```
src/ingest + src/clean
        │
        ▼
data_unification/          ← normalization design & rules
        │
        ▼
unified_dataset_pipeline/  ← THIS TASK: tested pipeline → modeling CSV
        │
        ▼
src/models/features.py     ← lags, training frame
src/models/forecast.py     ← county forecasts
```

| Path | Role |
|------|------|
| `data/processed/region_panel.csv` | Main pipeline copy of unified panel |
| `data/processed/training_features.csv` | Features for forecasting |
| `unified_dataset_pipeline/data/output/` | **Task-local copy for submission** |

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `FileNotFoundError` for inputs | Run `python -m data_unification.run` first |
| Pipeline `PASSED: False` | Read `data/reports/pipeline_report.txt` errors section |
| Tests fail on FIPS length | Ensure `county_fips` read as string with `.str.zfill(5)` |
| Empty `pop_65_plus` | Re-run after updating `data_unification/normalizers.py` |
| Tests fail but CSV looks fine | Delete `data/output/` and re-run with `--test` |

---

## Submission checklist

- [ ] `unified_dataset_pipeline/` — all Python modules
- [ ] `data/input/` — three cleaned CSVs
- [ ] `data/staging/` — three intermediate CSVs
- [ ] `data/output/modeling_unified_dataset.csv` — **primary file**
- [ ] `data/output/county_supply.csv`
- [ ] `data/reports/pipeline_report.txt` — shows `PIPELINE PASSED: True`
- [ ] `data/reports/test_results.txt` — shows 0 failures (run with `--test`)
- [ ] This README

---

## Related tasks

| Task | Folder | Role |
|------|--------|------|
| Ingest & clean | `src/ingest/`, `src/clean/` | Upstream raw → cleaned data |
| Normalization design | `data_unification/` | Schemas, rules, `unify_all()` |
| **Unified pipeline** | `unified_dataset_pipeline/` | **This task** |
| Forecasting | `src/models/` | Downstream modeling |
