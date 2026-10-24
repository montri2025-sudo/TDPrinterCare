# Virtual Warehouse and staff stock control room

`/admin/inventory` now includes a virtual shelf view and a large stock-room monitor.
Original product forms, image gallery, edit/delete controls and restock operations
remain in the management section. The room is made from local HTML/SVG/CSS assets.
Worker/cart movement is illustrative CSS animation. It does not change inventory,
claim employee presence or create orders. It can be paused, respects reduced-motion
preferences, and pauses outside the viewport or while the page is hidden.

`/staff/warehouse` is a separate read-only room for administrators, managers,
technician leads, technicians and sales staff. Non-admin staff see only products
in their assigned branch plus shared central-stock products. Their sales, repair
usage and outstanding-order aggregates are restricted to their own branch. Staff
without a branch get an empty view. Customer roles are denied. The staff JSON does
not contain cost prices, financial margins, stock-edit forms or management data.

## Display and definitions

- Red indicates `stock_quantity <= reorder_level` (including zero stock).
- Green "best seller" indicates the top 20% of positive-selling accessible SKUs
  this calendar month, ranked by unit sales, including ties. This rank is computed
  before client search filtering. An item may have both low-stock and best-seller
  badges. Sales are from noncancelled sale orders, including orders awaiting
  payment confirmation because the existing stock flow deducts stock on creation.
- The large wall screens show SKU count, total remaining units, monthly sold units,
  suggested purchase units and a six-item watch list. Search, shelf and status
  filters update both the screens and shelves. Mixed-product unit totals are
  explicitly labeled; they are not financial values or a common physical unit.
- Rack labels use actual `storage_location` strings. Missing locations appear in
  an explicit unassigned rack. Rendering initially shows at most nine racks and
  six products per rack; users can request more instead of creating all DOM nodes
  at once. The existing management table still lists all accessible products.

## Month-end purchase suggestion

The planning window includes today through the last day of the current month.
Demand is noncancelled sale quantities plus repair quantities actually approved
for stock deduction (`auto` or `approved`) during the last 30 calendar days,
including today. Pending/rejected repair logs and future transactions are excluded.

```
projected_usage = ceil(last_30_day_usage / 30 * remaining_days_in_month)
recommendation = max(0, reorder_level + max(1, projected_usage) - current_stock)
```

The one-unit minimum brings a product above, rather than exactly to, the reorder
trigger when there is no demand history. No other example demand is invented.
Outstanding quantities are shown separately for processing/shipped restock orders,
net of received quantities. They are NOT subtracted because the data model has no
promised arrival date. Requested, received and cancelled orders are excluded from
that outstanding count. Review existing orders and arrival dates before purchasing.
Suggestions are not purchase orders, guarantees, lead-time-aware forecasts, or a
replacement for supplier constraints, pack sizes and stock reviews.

The calculation uses three grouped read queries and adds no schema changes,
polling, frontend dependency or automatic stock write. Production-size ranges and
execution plans have not been load-tested. The screenshot preview uses a disposable
fictional database; no live database or deployment is changed.

`tests/test_virtual_warehouse.py` covers demand/threshold math, cancellation and
approval rules, incoming quantities, branch scope, role restrictions, staff price
privacy, safe JSON and continued availability of the original management forms.
