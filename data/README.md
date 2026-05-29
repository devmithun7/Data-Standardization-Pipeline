# Unified Dataset Pipeline — Data Files

All CSV, reports, and logs for the **unified dataset pipeline** task.  
Full documentation: [../README.md](../README.md)

## Layout

| Folder | Files | Description |
|--------|-------|-------------|
| `input/` | `pep_*_clean.csv`, `senior_*_clean.csv`, `cms_*_clean.csv` | Cleaned source tables |
| `staging/` | `demographics_normalized.csv`, `facilities_normalized.csv`, `county_supply_unified.csv` | Intermediate pipeline artifacts |
| `output/` | `modeling_unified_dataset.csv`, `county_supply.csv` | **Final modeling-ready outputs** |
| `reports/` | `pipeline_report.txt`, `test_results.txt` | Pass/fail audit trail |
| `logs/` | `pipeline.log` | Detailed run log |

## Regenerate

```bash
python -m unified_dataset_pipeline.run --test
```
