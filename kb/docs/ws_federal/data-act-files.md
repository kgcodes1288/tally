# How the federal spending files fit together

Federal agencies report spending to USAspending.gov under the DATA Act in several files that describe the same money at different levels of detail. This workspace holds three of them for fiscal year 2025, period 12 (the full year, October 2024 to September 2025).

## File A: account balances (`account_balances`)
One row per Treasury Account Symbol (TAS). It shows the budgetary resources available to an account (appropriations, carried-over balances, offsetting collections) and their status: obligations incurred, unobligated balance and gross outlays. File A comes from the agency's audited accounting system and is the authoritative total for each account.

## File B: program activity and object class (`program_activity`)
The same obligations and outlays as File A, broken down by **program activity** (what the money is for, such as "Science" or "Exploration") and **object class** (what kind of spending, such as personnel, contracts or grants). For each TAS, File B obligations should add up to File A obligations.

## File C: award financial (`award_financial`)
Account-level spending tied to individual awards: contracts, grants, loans and other assistance. It links accounting data to the award systems (FPDS for contracts, FABS for assistance) through award identifiers such as the PIID (contracts), FAIN (assistance) and URI.

- `award_category = 'contract'` or `'assistance'`: the row matched an award record.
- `award_category = 'unlinked'`: USAspending could not match the row to any award record. Unlinked rows are a known data-quality issue that agencies are asked to resolve.
- File C only covers award spending, so it is expected to be smaller than File B. Personnel costs, for example, never appear in File C.

## Useful identifiers
- `treasury_account_symbol` (TAS) joins Files A, B and C.
- `federal_account_symbol` groups several TAS into one federal account.
- `award_unique_key` identifies an award across rows; one award can have many File C rows.
- `transaction_obligated_amount` is the File C obligation amount. Negative values are deobligations.
- Amounts are in US dollars.

## Reference tables for trends
- `agency_budget_history`: agency-wide budgetary resources, obligations and outlays per fiscal year, about ten years per agency. The newest year can be partial.
- `agency_obligation_pace`: cumulative obligations by fiscal year and period (period 1 is October). Compare years at the same period to judge spending pace, for example "by period 6 NASA had obligated X percent of its year-end total".
