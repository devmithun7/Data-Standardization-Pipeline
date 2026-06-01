# Synthea Warehouse — Every Model Explained (in Plain English)

This document walks through **every model in the project**, one at a time. For each one you get:

- **What it is** — the plain-English description.
- **Why it was built** — the business or engineering reason it exists.
- **What it calculates and how** — the actual logic, explained step by step.

The models are grouped by layer, in the order data flows through the warehouse:

```
RAW (Synthea CSVs in Snowflake)
  → STAGING      (clean + standardize, 1 model per source)
    → INTERMEDIATE (business logic: insurance periods, enrichment, readmissions)
      → MARTS      (the star schema: dimensions + facts)
        → REPORTING (pre-aggregated tables for dashboards)
```

Before the models, there is a short section on the **helper macros**, because almost every model uses them. If you understand the macros first, the models read much more easily.

---

## Table of Contents

- [The Helper Macros](#the-helper-macros)
- [Staging Layer (9 models)](#staging-layer)
- [Intermediate Layer (3 models)](#intermediate-layer)
- [Marts — Dimensions (5 models)](#marts--dimensions)
- [Marts — Facts (3 models)](#marts--facts)
- [Reporting Layer (5 models)](#reporting-layer)
- [How It All Connects](#how-it-all-connects)

---

## The Helper Macros

Macros are reusable snippets of SQL. Instead of copy-pasting the same logic into 9 different files, the logic lives in one macro and every model calls it. This keeps the code consistent — if the rule for "what counts as a weekend" changes, you change it in one place.

### `synthea_surrogate_key(fields)`

**What it does:** Takes a list of columns and produces a single MD5 hash string from them.

**How:** It glues the columns together with a `|` separator (after turning `null` into empty string so it never breaks), then runs `md5()` on the result.

```sql
md5( coalesce(field1::varchar,'') || '|' || coalesce(field2::varchar,'') )
```

**Why it matters:** This is how every dimension and fact builds its **surrogate key**. A surrogate key is a warehouse-generated ID that replaces the raw source ID. We use it so:

- The warehouse isn't tied to the source system's ID format.
- We can build a key from *multiple* columns (e.g. `patient_id + effective_from`) when one column alone isn't unique — which is exactly what SCD2 needs.

### `synthea_date_key(date_column)`

**What it does:** Turns a date like `2024-03-15` into the integer `20240315`.

**Why:** Date dimensions traditionally use a clean integer key (`YYYYMMDD`) instead of an actual date. It joins fast and reads clearly. Every fact stores a `*_date_key` that joins to `dim_synthea__date`.

### `synthea_yes_no_from_boolean(expression)`

**What it does:** Takes a true/false condition and returns the **string** `'Yes'` or `'No'`.

**Why:** This project deliberately uses `'Yes'`/`'No'` text flags instead of `1`/`0` integers, because they're self-explanatory to business analysts reading a dashboard. Example: `lower(encounter_class) = 'emergency'` becomes `is_emergency_visit = 'Yes'`.

### The cleanup macros (`synthea_title_case`, `synthea_upper_trim`, `synthea_parse_date`, `synthea_parse_timestamp`, `synthea_zip_code`, `synthea_phone_number`, `synthea_digits_only`, etc.)

These are the small standardizers used all over the staging layer:

- **`synthea_title_case`** — `"john SMITH"` → `"John Smith"` (and blanks become `null`).
- **`synthea_upper_trim`** — trims spaces and uppercases (used for codes like gender/state).
- **`synthea_parse_date` / `synthea_parse_timestamp`** — safely convert text into real date/timestamp types using `try_to_*`, which returns `null` instead of erroring on bad values.
- **`synthea_zip_code`** — keeps only digits, takes the first 5, pads to 5 characters.
- **`synthea_phone_number` / `synthea_digits_only`** — strip out dashes, spaces, parentheses and keep only the numbers.
- **`synthea_reason_code` / `synthea_reason_description`** — fill missing reason fields with a default (`-9999999` / `'not available'`) so downstream joins don't hit nulls.
- **`synthea_loaded_at`** — stamps each row with a load timestamp for auditing.

**Why they exist:** Raw Synthea data is messy and inconsistent (mixed casing, text dates, formatted phone numbers). These macros guarantee every staging model cleans things the *same way*.

---

## Staging Layer

**Location:** `models/staging/synthea/`
**Materialized as:** Views (cheap, always reflect the latest RAW data).
**The rule for this layer:** one model per source table, light cleanup only — **no joins, no business logic, no aggregation.** Each staging model is a clean 1-to-1 mirror of a raw table.

**Why this layer exists:** RAW data should never be touched directly by reports. Staging gives every downstream model a single, clean, predictable version of each source. If the raw column is named `START` (a reserved word) or a date is stored as text, that mess is fixed *here, once*, and nobody downstream has to deal with it.

### `stg_synthea__patients`

- **What it is:** A cleaned copy of `RAW.PATIENTS` — one row per patient.
- **Why:** It's the foundation for the patient dimension and every patient-level report.
- **What it calculates / how:** Renames `id` → `patient_id`; parses `birthdate`/`deathdate` text into real dates; title-cases names, race, ethnicity, marital status; uppercases gender; standardizes the home address (city, county, state code, 5-digit zip, lat/long as floats); strips SSN and driver's license down to digits only. No math — pure standardization.

### `stg_synthea__encounters`

- **What it is:** A cleaned copy of `RAW.ENCOUNTERS` — one row per visit. This is the most important source table in the whole project.
- **Why:** Encounters (visits) are the central event everything revolves around — cost, utilization, and readmissions all start here.
- **What it calculates / how:** Renames `id` → `encounter_id`; parses the `START`/`STOP` text columns into `started_at`/`ended_at` timestamps (these are quoted because they're reserved words); keeps the cost columns (`base_encounter_cost`, `total_claim_cost`, `payer_coverage`); and **derives two flags** with the boolean macro:
  - `is_emergency_visit = 'Yes'` when `encounter_class` is `emergency`.
  - `is_inpatient_visit = 'Yes'` when `encounter_class` is `inpatient`.
  - Missing reason code/description are filled with defaults.

### `stg_synthea__conditions`

- **What it is:** Cleaned `RAW.CONDITIONS` — one row per diagnosis given to a patient during an encounter.
- **Why:** Powers the clinical-events fact and the chronic-condition logic in the high-risk patient report.
- **What it calculates / how:** Parses `START`/`STOP` into timestamps; renames `code`/`description` to `condition_code`/`condition_description`; keeps `patient_id` and `encounter_id` so conditions can be tied back to visits. A condition with **no stop date** later gets treated as **chronic** (still ongoing).

### `stg_synthea__medications`

- **What it is:** Cleaned `RAW.MEDICATIONS` — one row per prescription.
- **Why:** Feeds the clinical-events fact and medication cost analysis.
- **What it calculates / how:** Parses start/stop timestamps; renames cost and dispense columns (`base_cost`, `dispenses`, `total_cost`, `payer_coverage`) with `medication_` prefixes; fills default reason fields. (Note: Synthea has a known data quirk where 5 rows have `stopped_at < started_at` — this is a real source defect the tests catch.)

### `stg_synthea__procedures`

- **What it is:** Cleaned `RAW.PROCEDURES` — one row per procedure performed.
- **Why:** The third stream that feeds the clinical-events fact.
- **What it calculates / how:** Parses the `DATE` column (reserved word, so quoted) into `procedure_at`; renames `patient`/`encounter`/`code`/`description` and `base_cost` with `procedure_` prefixes; fills default reason fields.

### `stg_synthea__providers`

- **What it is:** Cleaned `RAW.PROVIDERS` — one row per clinician.
- **Why:** Becomes the provider dimension; lets us attribute encounters to doctors.
- **What it calculates / how:** Renames `id` → `provider_id`, keeps the `organization` link (`organization_id`), title-cases the name and specialty, uppercases gender, standardizes the address, and keeps `utilization`.

### `stg_synthea__organizations`

- **What it is:** Cleaned `RAW.ORGANIZATIONS` — one row per facility/hospital.
- **Why:** Becomes the organization dimension; used for facility-level and same-hospital-readmission analysis.
- **What it calculates / how:** Renames `id` → `organization_id`, title-cases name, standardizes address, cleans the phone number to digits, keeps `revenue` and `utilization`.

### `stg_synthea__payers`

- **What it is:** Cleaned `RAW.PAYERS` — one row per insurance company.
- **Why:** Becomes the payer dimension; used for coverage and insurance analysis.
- **What it calculates / how:** Renames `id` → `payer_id`, title-cases name, standardizes the HQ address and phone, and keeps a long list of financial/utilization fields (amount covered/uncovered, revenue, covered vs uncovered encounters/medications/procedures, member months, etc.).

### `stg_synthea__payer_transitions`

- **What it is:** Cleaned `RAW.PAYER_TRANSITIONS` — one row per patient per year of insurance coverage.
- **Why:** This is the **raw material for the SCD2 insurance history.** It records which payer covered which patient in which years.
- **What it calculates / how:** Renames `patient` → `patient_id`, `payer` → `payer_id`, `start_year`/`end_year` → `coverage_start_year`/`coverage_end_year`, and title-cases the ownership type. No math — but these year columns get turned into real date *periods* in the intermediate layer.

---

## Intermediate Layer

**Location:** `models/intermediate/synthea/`
**Materialized as:** Views.
**The rule for this layer:** this is where **real business logic** happens — logic that's too complex for staging but isn't yet a final reporting table. These models can join, use window functions, and compute derived values.

**Why this layer exists:** It keeps the marts clean. Instead of cramming complicated readmission or insurance-period logic into a fact table, we compute it once here, give it a clear name, and let the marts simply consume the result.

### `int_synthea__patient_insurance_periods`

- **What it is:** The patient's insurance history turned into dated **periods** — one row per patient per coverage period. This is the **SCD2 (Slowly Changing Dimension Type 2)** preparation model.
- **Why it was built:** A patient changes insurance over time. To answer "which insurer covered this patient *on the day of this specific visit*," we need each coverage span expressed as a real date range, not just a year number. SCD2 is the standard pattern for tracking history like this.
- **What it calculates / how:**
  1. Pulls patient demographics from `stg_synthea__patients`.
  2. Joins to `stg_synthea__payer_transitions` to get each coverage year, and to `stg_synthea__payers` for the payer name.
  3. **Builds the period boundaries:** `effective_from` = January 1 of the coverage start year (`date_from_parts(start_year, 1, 1)`), and `effective_to` = December 31 of the coverage end year (or this year if it's still open).
  4. **Flags the current period:** `is_current = 'Yes'` if the coverage end year is this year or later.
  5. **Versions the rows:** a `row_number()` over each patient, ordered by start year, produces `scd2_version` (1, 2, 3...) — the classic SCD2 version counter.

### `int_synthea__encounter_enriched`

- **What it is:** Each encounter, "enriched" with context from providers, organizations, and payers, plus several derived calculations. One row per encounter.
- **Why it was built:** The raw encounter row only has IDs and codes. To make it useful, we attach human-readable names and pre-compute the numbers everyone asks for (duration, out-of-pocket cost, coverage %). Doing it here means the fact table and the high-risk report both reuse the same definitions.
- **What it calculates / how:**
  - **Duration:** `datediff('hour', started_at, ended_at)` → how many hours the visit lasted.
  - **Care setting:** a `case` statement that maps messy `encounter_class` values into clean buckets — `wellness`, `ambulatory`, `emergency`, `urgent_care`, `inpatient`, or `other`.
  - **Patient out-of-pocket:** `total_claim_cost − encounter_payer_coverage` (with `coalesce` so nulls count as 0).
  - **Payer coverage %:** `100 × payer_coverage ÷ total_claim_cost`, using `nullif(total_claim_cost, 0)` to avoid divide-by-zero.
  - **Context:** left joins to providers, organizations, and payers to pull in names, specialty, and city/state.

### `int_synthea__readmission_flags`

- **What it is:** For every inpatient discharge, did the patient come back — and how fast? One row per inpatient discharge.
- **Why it was built:** **30-day readmission rate is the single most important hospital quality metric.** This model contains the core logic that detects readmissions; the fact table and two reports all depend on it.
- **What it calculates / how:**
  1. **Find the discharges:** filter encounters down to `encounter_class = 'inpatient'` that have an end date. These are the "index" discharges being evaluated.
  2. **Find the next visit:** self-join encounters back to themselves on the same `patient_id`, keeping only later visits (`e.started_at > d.discharge_date`). A `row_number()` ranks them so we can grab the **first** one.
  3. **Measure the gap:** `datediff('day', discharge_date, readmit_date)` gives `days_to_readmission`.
  4. **Set the flags** with the boolean macro: `is_7_day`, `is_30_day`, `is_90_day` readmission (based on the day gap), `has_readmission`, and `is_same_organization_readmission` (did they return to the same hospital?).
  5. Keeps only the first readmission per discharge (`readmit_rank = 1`) via a left join, so discharges with no return still appear (with `No` flags).

---

## Marts — Dimensions

**Location:** `models/marts/synthea/dimensions/`
**Materialized as:** Tables (queried constantly by reports, so we build them once).

**What a dimension is, in plain terms:** the **"who / what / where / when"** context. Dimensions describe things — a patient, a doctor, a hospital, an insurer, a calendar day. They hold descriptive attributes (names, addresses, categories) but **no measures to sum up.** Reports join facts to dimensions to slice numbers by these attributes.

**Why dimensions are separate:** the same `dim_patient` and `dim_date` are reused by every fact and every report. Defining each entity once keeps everything consistent ("conformed dimensions").

### `dim_synthea__patient`

- **What it is:** The patient dimension — but at **one row per insurance period**, not one row per patient (because it's SCD2).
- **Why:** So a fact can join to the *specific version* of the patient that was valid at the time of the event.
- **What it calculates / how:** Reads straight from `int_synthea__patient_insurance_periods` and builds the surrogate key `patient_key = md5(patient_id | effective_from)`. Carries demographics, payer, the `effective_from`/`effective_to` dates, `is_current`, and `scd2_version`.
- **Important nuance:** in Synthea, **all periods end up `is_current = 'No'`** (the data is historical), so reports pick the *latest* period per patient rather than filtering on `is_current = 'Yes'`. Also, to count actual people, you must `count(distinct patient_id)`, not count rows.

### `dim_synthea__date`

- **What it is:** A full calendar dimension — one row for **every single day** from 1900-01-01 to 2030-12-31.
- **Why:** Time-based reporting (monthly trends, fiscal-year cost) needs a reliable calendar to join to. It also serves as the **time spine** for the dbt Semantic Layer.
- **What it calculates / how:**
  1. **Generates the days:** `table(generator(rowcount => 47884))` creates ~47,884 rows, and `dateadd(day, seq4(), '1900-01-01')` turns each into a consecutive date.
  2. **Derives attributes for each day:** the integer `date_key`, day/month/quarter/year parts, day name, week-of-year, month name.
  3. **Fiscal calendar:** fiscal year starts in October — so months 10–12 roll into next year's fiscal year, and fiscal quarters are remapped accordingly.
  4. **Convenience flags:** `is_weekend`, `is_month_start`, `is_month_end` as Yes/No.

### `dim_synthea__provider`

- **What it is:** The provider (clinician) dimension — one row per provider.
- **Why:** Lets reports attribute encounters and costs to individual doctors (e.g. the provider scorecard).
- **What it calculates / how:** Reads `stg_synthea__providers`, builds `provider_key = md5(provider_id)`, and carries name, gender, specialty, address, the `organization_id` link, and utilization. Filters out null provider IDs.

### `dim_synthea__organization`

- **What it is:** The facility/hospital dimension — one row per organization.
- **Why:** Enables facility-level analysis and the "same hospital" check in readmissions.
- **What it calculates / how:** Reads `stg_synthea__organizations`, builds `organization_key = md5(organization_id)`, carries name, address, phone, revenue, and utilization. Filters out null org IDs.

### `dim_synthea__payer`

- **What it is:** The insurance-company dimension — one row per payer.
- **Why:** Powers all insurance/coverage breakdowns in the reports.
- **What it calculates / how:** Reads `stg_synthea__payers`, builds `payer_key = md5(payer_id)`, and carries name, HQ address, phone, and revenue. Filters out null payer IDs.

---

## Marts — Facts

**Location:** `models/marts/synthea/facts/`
**Materialized as:** Tables.

**What a fact is, in plain terms:** the **"how much / how often"** — the measurable events of the business. A fact table is mostly **numbers you can add up** (cost, duration, counts) plus **foreign keys** that point to dimensions. Facts are kept thin and at a single, well-defined grain.

**A pattern shared by all three facts — the point-in-time insurance join:**
Each fact left-joins to `int_synthea__patient_insurance_periods` on `patient_id` **and** a `BETWEEN` on the event date and the period's `effective_from`/`effective_to`. This attaches the insurance period that was active *on the day of the event*. A `row_number()` (`period_match_rank`) plus a final `where period_match_rank = 1` guarantees no row is duplicated if it happens to match more than one period. This is why facts can carry a correct `patient_key` that respects history.

### `fct_synthea__encounters`

- **What it is:** The **core fact** — one row per encounter (visit), with all costs, duration, and foreign keys to every dimension.
- **Why it was built:** This is the central table for utilization and cost analytics. Almost every report joins to it.
- **What it calculates / how:**
  - **Builds 5 foreign keys** (all surrogate hashes): `patient_key` (from `patient_id + effective_from`), `provider_key`, `organization_key`, `payer_key`, and `encounter_date_key`.
  - **Does the point-in-time patient join** described above.
  - **Enforces data-cleaning rules at the mart boundary** (this is deliberate — the fact is the "gatekeeper"):
    - Costs are clamped to be non-negative: `greatest(cost, 0)`.
    - Duration: negatives become `0`; anything over 1000 hours becomes `null` (an obviously-bad value).
  - **Stores the additive measures:** `total_claim_cost`, `encounter_payer_coverage`, `patient_out_of_pocket`, `base_encounter_cost`, `duration_hours`, plus the `is_emergency_visit` / `is_inpatient` flags and reason code/description.

### `fct_synthea__readmissions`

- **What it is:** A fact that links each inpatient discharge to its readmission, with timing flags. One row per index discharge.
- **Why it was built:** To make the readmission logic (computed in the intermediate layer) easily reportable at the mart level, joined to dimensions.
- **What it calculates / how:**
  - **Builds the key** `readmission_key = md5(index_encounter_id | readmit_encounter_id)`.
  - **Carries two date keys** — `discharge_date_key` and `readmit_date_key` — which makes it behave like a small *accumulating snapshot* (two milestones on one row).
  - **Does the point-in-time patient join** on the discharge date.
  - **Stores:** `days_to_readmission` and the `is_7_day` / `is_30_day` / `is_90_day` / `has_readmission` / `is_same_organization_readmission` flags.
- **Important caveat:** this fact has **no `payer_key`**. To analyze readmissions by insurer, you join back to `fct_synthea__encounters` on `index_encounter_id = encounter_id` (which is exactly what the monthly readmission report does).

### `fct_synthea__clinical_events`

- **What it is:** A **single unified fact** combining three different clinical streams — conditions, procedures, and medications — into one long table. One row per clinical event.
- **Why it was built:** So analysts query **one** table for all clinical activity instead of three separate ones. It's a classic "consolidated fact" pattern.
- **What it calculates / how:**
  1. **Three CTEs, one per source** (conditions, procedures, medications). Each one:
     - Builds an event key from `patient + encounter + event type + code + date`.
     - Tags itself with a literal `event_type` (`'condition'` / `'procedure'` / `'medication'`).
     - Maps its own columns onto a **shared schema** (`clinical_code`, `clinical_description`, `event_cost`, `dispense_count`, `duration_days`).
     - Fills the fields it doesn't have with typed `null` casts (e.g. conditions have no cost; procedures have no dispense count) so the union lines up.
     - Derives `is_chronic_condition` (a condition with no stop date) and `duration_days` via `datediff` with a `coalesce(stop, current_date())` fallback for still-ongoing items.
  2. **`union all`** stacks the three streams into one.
  3. **Enrich + dedup:** does the point-in-time patient join, adds the `encounter_key` and `event_date_key`, and keeps `period_match_rank = 1`.

### How the KPIs are grouped out of each fact

Each fact stores **raw, row-level measures**. A KPI is produced by combining an **aggregate function** (`sum` / `count` / `avg`, or a ratio of two sums) with a **`GROUP BY` a dimension**. The dimensions you're allowed to group by are exactly the **foreign keys that fact carries** — so the fact decides which slices are possible.

**`fct_synthea__encounters` — cost & utilization KPIs**

Measures stored: `total_claim_cost`, `encounter_payer_coverage`, `patient_out_of_pocket`, `base_encounter_cost`, `duration_hours`, plus `is_emergency_visit` / `is_inpatient` flags. Group-by slices: patient, provider, organization, payer, date, care_setting.

| KPI | How it's computed | Typical group-by |
|-----|-------------------|------------------|
| Encounter volume | `count(distinct encounter_id)` | month × care_setting × payer |
| Total / avg cost | `sum(total_claim_cost)`, `avg(total_claim_cost)` | month / patient-year / provider |
| Emergency / inpatient counts | `sum(case when flag='Yes' then 1 else 0 end)` | any slice |
| Payer coverage % | `sum(coverage) / nullif(sum(total_claim_cost),0)` | month × payer |
| Avg / max duration | `avg(duration_hours)`, `max(duration_hours)` | month × care_setting |

**`fct_synthea__readmissions` — quality KPIs**

Measures stored: `days_to_readmission`, and the `is_7_day` / `is_30_day` / `is_90_day` / `has_readmission` / `is_same_organization_readmission` flags. Group-by slices: patient, organization, discharge_date, readmit_date. (No payer — borrowed from `fct_encounters`.)

| KPI | How it's computed | Typical group-by |
|-----|-------------------|------------------|
| Discharge count (denominator) | `count(distinct index_encounter_id)` | month × diagnosis × payer / provider |
| 30-day readmissions (numerator) | `sum(case when is_30_day_readmission='Yes' then 1 else 0 end)` | same |
| **30-day readmission rate** | `100 * numerator / nullif(denominator,0)` | same |
| Avg days to readmission | `avg(days_to_readmission)` | month / organization |

The signature pattern here is the **ratio KPI**: a `sum` of a flag (numerator) over a `count` of discharges (denominator).

**`fct_synthea__clinical_events` — clinical-activity KPIs**

Measures stored: `event_cost`, `dispense_count`, `duration_days`, plus the `event_type` label and `is_chronic_condition` flag. Group-by slices: patient, encounter, event_date, event_type.

| KPI | How it's computed | Typical group-by |
|-----|-------------------|------------------|
| Event counts | `count(*)` | event_type × patient |
| Chronic condition count | `count(distinct clinical_code)` where chronic | patient |
| Primary diagnosis (a label, not a sum) | pick one via `row_number()` / `qualify` | per encounter |

This fact is used less for "sum it up" KPIs and more as a **lookup** — e.g. `rpt_synthea__readmission_rate_monthly` filters it to `event_type='condition'` to attach the **primary diagnosis** as a grouping *attribute*.

**The mental model:** each fact holds the raw measures for its grain; its foreign keys define the legal group-by dimensions; KPIs are `sum`/`count`/`avg` of those measures sliced by a dimension; and ratio KPIs are a `sum` of a flag over a `count` of the denominator. Cost KPIs come from the encounter fact, quality KPIs from the readmissions fact, and clinical-activity KPIs from the clinical-events fact — each at its own grain so the aggregates stay correct.

---

## Reporting Layer

**Location:** `models/reporting/synthea/`
**Materialized as:** Tables.

**What this layer is, in plain terms:** these are the **pre-aggregated, dashboard-ready** tables. They join facts to dimensions and `GROUP BY` down to a specific grain, so a BI tool just reads the answer instead of computing it. The expensive aggregation is paid **once** at build time.

**Why this layer exists:** dashboards should be fast and metric definitions should be consistent. By baking the aggregation into a table, every dashboard that reads `rpt_synthea__monthly_encounters` gets the exact same numbers, instantly.

### `rpt_synthea__monthly_encounters`

- **What it is:** Monthly utilization and cost KPIs. **Grain:** one row per month × care setting × payer.
- **Why:** The primary "volume and cost trend" table for dashboards.
- **What it calculates / how:** Joins `fct_synthea__encounters` to `dim_payer` and `dim_date`, groups by month/care-setting/payer, and computes: `encounter_count`, emergency and inpatient counts (`sum(case when flag='Yes' then 1 else 0 end)`), total and average cost, total payer coverage and out-of-pocket, average/max duration, and a **payer coverage %** = `sum(coverage) / sum(total_cost)` (guarded with `nullif`).

### `rpt_synthea__readmission_rate_monthly`

- **What it is:** Monthly 30-day readmission rate. **Grain:** one row per month × primary diagnosis × payer.
- **Why:** The headline clinical-quality KPI table, broken down by what the patient was treated for and who insured them.
- **What it calculates / how (this is the most multi-step report):**
  1. **`primary_diagnosis` CTE:** joins `fct_synthea__clinical_events` (filtered to `event_type = 'condition'`) to encounters, and uses `row_number()` + `qualify` to pick the **one** leading diagnosis per encounter.
  2. **`readmissions_enriched` CTE:** takes `fct_synthea__readmissions`, attaches that diagnosis, and joins back through `fct_synthea__encounters` to recover the **payer** (remember, readmissions has no payer of its own).
  3. **`aggregated` CTE:** groups by month/diagnosis/payer and computes `discharge_count`, `readmission_30day_count`, and `readmission_30day_rate_pct`.
  4. **Quality flag:** marks `'Alert'` when the rate exceeds the **15% industry benchmark**, else `'OK'`.

### `rpt_synthea__cost_of_care_annual`

- **What it is:** Annual cost summary per patient. **Grain:** one row per patient × fiscal year.
- **Why:** Financial analytics — how much each patient costs the system each year, and which patients are expensive.
- **What it calculates / how:** Joins encounters to `dim_patient` (to get the person) and `dim_date` (to get `fiscal_year`), then groups by patient + fiscal year to sum: encounter count, emergency/inpatient counts, total and average cost, payer coverage, out-of-pocket. It builds its own surrogate key (`patient_id + fiscal_year`), computes the current fiscal year, and **buckets** each patient-year into `High Cost` (> $100k), `Medium Cost` (> $50k), or `Low Cost`.

### `rpt_synthea__provider_performance`

- **What it is:** A provider scorecard. **Grain:** one row per provider.
- **Why:** Lets the organization compare doctors on volume, cost, and quality (readmissions).
- **What it calculates / how:**
  1. **`provider_encounters` CTE:** joins encounters to `dim_provider` and `dim_organization`.
  2. **`provider_readmissions` CTE:** joins those encounters to `fct_synthea__readmissions` on the index encounter.
  3. **`aggregated` CTE:** per provider, computes `total_encounters`, `unique_patients`, emergency/inpatient counts, total/avg cost, `cost_per_visit`, payer coverage, inpatient discharges, and `readmission_30day_rate_pct`.
  4. **Quality flag (prioritized):** `'High Risk (Readmission)'` if rate > 20%, else `'High Cost'` if avg > $10k, else `'Low Volume'` if < 10 encounters, else `'OK'`.

### `rpt_synthea__high_risk_patients`

- **What it is:** A care-management outreach list — the patients who most need attention. **Grain:** one row per patient.
- **Why:** Care teams need a prioritized list of high-risk patients to proactively reach out to. This is the most "product-like" report.
- **What it calculates / how (it combines four sources):**
  1. **`latest_patients` CTE:** picks the **most recent SCD2 row per patient** using `qualify row_number()` (latest period — *not* `is_current`, because of the Synthea nuance).
  2. **`patient_encounters` CTE:** per patient — total visits, total cost, ED visit count, and the date of the last ED visit.
  3. **`patient_readmissions` CTE:** per patient — readmission count and last readmission date.
  4. **`patient_chronic_conditions` CTE:** per patient — count of distinct still-open conditions, plus a `listagg` of their names into one string.
  5. **`scored` CTE:** computes `age` via `datediff`, then assigns a **`risk_level`** with layered rules:
     - **Very High:** 2+ readmissions, OR 1 readmission *plus* 2+ chronic conditions.
     - **High:** cost > $100k, OR 4+ ED visits, OR 3+ chronic conditions.
     - **Moderate:** 2+ chronic conditions.
     - **Low:** everyone else.
  6. **Final select:** keeps only `Very High / High / Moderate` patients (the ones worth outreach) and adds a `primary_risk_factor` label explaining *why* each one is flagged (recent readmission, frequent ED user, high cost, multiple chronic conditions).

---

## How It All Connects

Reading bottom-up, here is the full story of one number — say, the **30-day readmission rate for diabetes patients on a given insurer in March**:

1. **RAW.ENCOUNTERS / RAW.CONDITIONS / RAW.PAYER_TRANSITIONS** hold the messy source data.
2. **Staging** cleans each one into `stg_synthea__encounters`, `stg_synthea__conditions`, `stg_synthea__payer_transitions`.
3. **`int_synthea__readmission_flags`** finds the discharges and their first readmissions, computing the 30-day flag. **`int_synthea__patient_insurance_periods`** turns coverage years into dated periods.
4. **`fct_synthea__readmissions`** turns those flags into a fact; **`fct_synthea__encounters`** holds the payer link; **`fct_synthea__clinical_events`** holds the diagnosis.
5. **`rpt_synthea__readmission_rate_monthly`** joins all of those, groups by month + diagnosis + payer, and produces the final rate and quality flag.
6. A **BI dashboard** simply reads that one reporting table.

That's the whole point of the layered design: each layer does one job, every model has a clear grain and purpose, and the messy work happens once — early — so the numbers at the end are fast, consistent, and trustworthy.
