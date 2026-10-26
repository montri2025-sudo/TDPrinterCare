# Local Odoo integration test

The opt-in stack uses `docker-compose.local-test.json`, project
`tdprinter-local-test`, isolated named volumes, and loopback-only ports. It does
not join the production reverse-proxy network, reuse old MySQL data, or use real
customer records. `.env.local-test` holds newly generated credentials and is
ignored by Git. The Docker build context excludes environment files, uploads,
database directories and generated artifacts.

## Start

```sh
python3 tools/prepare_odoo_local_test.py
docker compose --env-file .env.local-test -p tdprinter-local-test -f docker-compose.local-test.json up -d --build
docker compose --env-file .env.local-test -p tdprinter-local-test -f docker-compose.local-test.json exec -T odoo python3 - < tools/bootstrap_odoo_local_test.py
docker compose --env-file .env.local-test -p tdprinter-local-test -f docker-compose.local-test.json exec -T app python - < tools/seed_odoo_local_test.py
docker compose --env-file .env.local-test -p tdprinter-local-test -f docker-compose.local-test.json exec -T app python - < tools/check_odoo_local_test.py
```

App: http://127.0.0.1:18865 · Odoo: http://127.0.0.1:18869

App login uses `INITIAL_ADMIN_USERNAME` / `INITIAL_ADMIN_PASSWORD` from the local
environment file. Odoo login uses `ODOO_USERNAME` and the randomly generated
`ODOO_API_KEY` value as its test-only admin password. These are distinct from the
Odoo database-manager master password. No credentials are printed or committed.
Use a dedicated, appropriately scoped API key for a real deployment.

The bootstrap installs Sales and Repair and sets the test company/pricelist to
THB. Helper scripts refuse to run without `TDSP_LOCAL_TEST=1`. They are intended
for this disposable stack only. Stop without deleting data using the same compose
arguments with `stop`; no automatic volume deletion is performed.

## Quotation export behavior

A button on sales-order and administrator restock-order detail pages explicitly
exports one record as an Odoo draft quotation. Sales exports require admin,
manager or sales role and source-branch access; restock exports require admin.
CSRF validation applies. The source row is locked for the export transaction so
parallel requests from this application serialize. Empty, cancelled, invalid,
anonymous-customer and over-100-line documents are rejected before export.

The customer (sale) or service center (restock) is synchronized as a partner.
Products resolve by exact SKU, creating only missing products without overwriting
catalog prices. A single product variant is required. Quantities and unit prices
come from source order lines, not current catalog pricing. The partner's Odoo
pricelist must use THB. Taxes are explicitly empty on imported draft lines and
must be reviewed in Odoo before confirmation; source totals are preserved.

Company plus `TDSP-SALE-{id}` / `TDSP-RESTOCK-{id}` identifies an export. Repeating
an export reuses the existing document, never replaces Odoo lines or moves its
state backwards. A source fingerprint warns if source data has since changed.
Edits/cancellations after export require manual review in Odoo. This is an
explicit one-way draft export, not continuous bidirectional synchronization.
No order confirmation, invoice, payment, delivery or email action is invoked.
The existing legacy bulk master-data sync is separate and unchanged.

## Repair feasibility

The local check creates a fictional serial-tracked machine and a draft
`repair.order` containing customer, product, serial number and internal notes.
It verifies no stock movement or linked sales order is generated. Odoo 19 states
are `draft`, `confirmed`, `under_repair`, `done`, `cancel`; these do not map one to
one to TDPrinterCare's diagnostic/parts/testing stages. There is no production
repair-sync button or automatic status synchronization in this change.

## Evidence

91 Python tests pass, including quotation idempotence, safe faults, currency and
variant validation, HTTPS transport, CSRF, roles and branch isolation. The local
PostgreSQL + Odoo 19 check passed for sale and restock quotes, repeated export,
exact THB totals, and a draft repair with serial number. Stock moves and invoices
remained unchanged. SQLite unit tests strip `FOR UPDATE`; real PostgreSQL supplies
the actual row lock in the local integration test. Production connectivity,
enterprise customizations and simultaneous multi-worker stress are not tested.

The restock list also has an always-visible bottom scroll control when its table
overflows, plus native horizontal scrolling. The control follows trackpad,
keyboard and resize changes, and hides when all columns fit.
