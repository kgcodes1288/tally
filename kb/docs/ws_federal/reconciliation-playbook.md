# Federal spending reconciliation playbook

Use this playbook when asked to reconcile, validate or explain differences between the federal spending files.

## Check 1: File A against File B, per account
1. Sum `obligations_incurred` from `account_balances` by `treasury_account_symbol`.
2. Sum `obligations_incurred` from `program_activity` by the same key.
3. Report every account where the absolute difference is above the materiality threshold (default: 1,000 dollars or 0.1 percent of the account, whichever is larger).
4. If nothing differs, say so plainly. A clean result is a valid finding.

## Check 2: award coverage, File B against File C
1. For each account, compare File B obligations for award-type object classes (contracts, grants and similar, object classes 25.x, 31.x, 32.x, 33.x, 41.x) with File C obligations.
2. Express File C as a percentage of File B. Large gaps can mean awards reported without account data, or timing differences.
3. Do not expect a perfect match. Explain differences, do not "fix" them.

## Check 3: unlinked awards
1. Count rows and sum `transaction_obligated_amount` where `award_category = 'unlinked'`, by agency, account and award type.
2. List the largest unlinked items with their PIID, FAIN or URI and recipient, so an analyst can trace them.
3. Separate small or negative amounts (often deobligations on old awards) from large positive ones, which matter more.

## How to report
- Lead with the answer: is it reconciled, and if not, how big is the gap and where is it concentrated?
- Show totals for each file side by side, then the exceptions.
- Always state the period (FY2025, period 12), the agencies in scope, and the threshold used.
- Never present a difference without saying which file is likely authoritative (File A is the accounting source of truth).
