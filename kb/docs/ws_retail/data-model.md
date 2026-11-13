# Olist marketplace data model

Olist is a Brazilian marketplace that connects small sellers to large online stores. This workspace holds about 100,000 orders placed between September 2016 and October 2018. Amounts are in Brazilian reais (BRL). Personal data has been anonymized by the publisher.

## Tables and how they join
- `orders` (one row per order) joins `customers` on `customer_id`.
- `order_items` (one row per item) joins `orders` on `order_id`, `products` on `product_id` and `sellers` on `seller_id`.
- `order_payments` (one or more rows per order) joins on `order_id`. `payment_sequential` numbers the payments within an order.
- `order_reviews` joins on `order_id`. Scores run from 1 to 5. Comment text is in Portuguese.
- `products` and `geolocation` are shared reference tables. `geolocation` gives approximate coordinates per 5-digit zip prefix.

## Key definitions
- **Order value** = sum of `price + freight_value` over the order's items.
- **Amount paid** = sum of `payment_value` over the order's payments.
- `customer_id` is per order. Use `customer_unique_id` to count real customers or repeat buyers.
- **Delivery delay** = `order_delivered_customer_date` minus `order_estimated_delivery_date`. Positive means late.
- Order statuses include delivered, shipped, canceled, unavailable, invoiced, processing, created and approved.

## Known quirks
- Some orders are paid with several methods, including `voucher`, which can make amount paid differ from order value.
- Payments in installments (`payment_installments` above 1) can include interest, so amount paid may exceed order value.
- A few orders have payments but no items, or items but no payment.
- Product dimension and description-length columns have spelling errors in their names (`lenght`), kept as published.
