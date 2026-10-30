# Printer warranty cards

After payment confirmation, the sale detail page offers one warranty form per unit
for `FDM_Printer` and `Resin_Printer` items. Staff enter the physical serial number;
walk-in purchases also require a customer name. Cards use a monochrome printable
layout based on the supplied TD Printer reference, a text brand heading, contact details,
and its one-year terms. Browser Print can save the document as PDF. Cards are front/back, each 100 × 100 mm,
placed side by side on one portrait A4 page with 5 mm page margins.
Print at actual size (100%) without fit-to-page scaling.

The purchase date comes from the sale date. The one-year anniversary handles leap
days. Model, buyer, store and dates are stored as issuance snapshots. A unique serial
and composite item/unit primary key prevent duplicate issuance, including concurrent
requests. A repeated identical issuance opens the existing document. No stock,
registered device, sales total or Odoo record is changed by issuance.

Admin, manager and sales staff are restricted by the existing branch access check.
Customers can read cards only for sales linked to their customer account through
`/customer/warranties`. Walk-in buyers receive a printed/PDF copy from staff; the
system does not automatically email or send a message. Cancelled or unpaid orders
cannot issue or display valid cards. This first version has no correction/reissue UI.

Deployment: normal database initialization runs `schema.sql`, adding the
`Warranty_Cards` table without altering existing records. Run initialization before
serving the new code. No historical warranties are generated automatically because
sales do not contain physical serial numbers. Categorize printer SKUs correctly.

Tests use isolated SQLite fixtures: FDM/Resin eligibility, per-unit limits, serial
uniqueness, repeat issuance, immutable snapshots, leap-year dates, payment and
cancellation checks, CSRF, branch scope, customer ownership and HTML escaping.
