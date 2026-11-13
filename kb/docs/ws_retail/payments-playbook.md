# Order payment reconciliation playbook

1. Compute order value (items plus freight) and amount paid (sum of payments) per order.
2. Classify each order: matched (difference within 0.01 BRL), overpaid, underpaid, no payment, or no items.
3. For mismatches, break down by `payment_type` and `payment_installments`. Installment interest usually explains overpayment; vouchers often explain splits.
4. Report count and net BRL difference per class and per state, with the ten largest examples (order id, value, paid, payment types).
5. State clearly which differences look explainable (interest, vouchers) and which need investigation.
