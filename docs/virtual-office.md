# Virtual Office

The existing `/admin/board` route now opens a service shop map. The menu is named
Virtual Office for administrators, managers and technician leads. Other pages use
updated application chrome and retain their existing functions.

## Working with the map

- Each room represents one existing repair status. Select a room or a stage to
  filter jobs. Select a machine or job card to inspect a job, its real history,
  its technician and its next step. Changes save only after pressing Save.
- Search and branch/technician filters run locally on the already authorized
  ticket data. Date filtering uses ticket creation dates, defaulting to this month.
- Reception counts distinct customers with `New` jobs. It represents the recorded
  service queue, not visitors physically detected at the shop.
- Waiting and repair/testing counts use distinct machine serial numbers within
  the selected jobs. Dispatch counts closed jobs explicitly marked pending handover.
- Closed jobs with no handover record appear separately as unrecorded. Users can
  mark pending shipment/pickup, shipped, or collected at the shop. Delivery changes
  are recorded in ticket history. Reopening a ticket in the office resets handover.
- The process diagram indicates the current stage. It does not assert that a job
  visited every preceding stage; the history lists actual recorded changes.

## Installation and data

Normal application startup through `db.init_db()` adds `Tickets.handover_status`
and `Tickets.handover_at` idempotently, then enforces allowed handover values.
Existing tickets default to `unrecorded`. No existing delivery is inferred.
The source changes do not themselves run this migration or deploy the application.

Status updates validate roles, branch, technician and allowed statuses. The office
sends expected status/assignee/handover values. Stale edits return 409 instead of
overwriting another update. The final update also checks the values atomically.

## Performance and verification

The scene is SVG with perspective projection, not WebGL. It displays at most four
machine icons per room; remaining tickets remain accessible in the lists. Rendering
occurs on initial load or filter/zoom interaction. There are no animation loops,
polling timers, new frontend dependencies, or external 3D downloads. The scene's
styles and script load only on this page. History is fetched once in a batch for
the displayed authorized tickets, not once per ticket.

This does not guarantee performance for a production-sized dataset. The full job
list and historical range still determine payload size. Large date ranges should
be measured before deployment. A richer animated scene could be extracted to
PrintScape later; this change does not modify PrintScape or its integration API.

`tests/test_virtual_office.py` exercises the real WSGI routes with fictional SQLite
fixtures. It covers branch/role authorization, CSRF, valid and invalid updates,
stale edits, history, return URLs, safe JSON, empty results and delivery transitions.
The browser preview uses a separate disposable database. PostgreSQL migration and
production load have not been tested against an online database.

## Customer view

`/customer/office` is a customer-only, read-only view of devices owned by the
signed-in customer's `customer_id`. A menu entry and a dashboard shortcut lead to
it. The server scopes both the ticket query and device query to that owner; URL
parameters cannot substitute another customer's ID or serial number. Only the
latest job (creation time, then ticket ID) is shown for each owned device. Open
jobs from previous months remain visible. Devices with no job are listed without
inventing a room location.

Customer JSON omits technician identities, staff lists and internal history notes.
It contains only status/time history. The detail panel links to the existing
owner-checked customer ticket page. No editor form is rendered; the administrative
write route still rejects customers even if they manually submit a forged request.
Customer device selection emphasizes the relevant stage and displays a location
message. Room positions are workflow stages, not tracked physical coordinates.

## Executive monitor room

The administrator/manager dashboard now leads with a six-screen control-room
illustration. The room uses a local static SVG background with executive figures;
these are decorative figures, not online users. The screens display job flow,
status mix, technician workload, product-group sales, repair performance and
follow-up items. Each screen opens a larger SVG and a text data table. Existing
reports, forms, queues and maps remain in an expandable section below the room.

The room reuses existing authorized dashboard aggregates without additional SQL
queries. Date-range status/performance metrics, current workload and monthly
trends each have explicit period labels. Repair completion percentage describes
closed jobs in the selected received-job cohort; it is not an SLA measurement.
No-data values are shown as zero or unavailable, never as invented example graphs.

No new frontend dependency, animation loop or refresh timer is introduced. The
existing detailed reports retain their previous Chart.js/Leaflet dependencies.
`tests/test_monitor_room.py` checks the data mapping, manager branch scope,
empty-cohort handling and customer role rejection with fictional fixtures.

## Office-simulator studio

`static/service-office-scene.js` places accessible operational overlays on an original
warm isometric office illustration in `static/office-assets/service-studio.webp` (about 369 KiB).
This replaces the previous wireframe-style floor. Desks, printers and furniture in the
illustration are decorative; only numbered job pins, counts and technician name badges
represent authorized operational records. The renderer never infers work from the artwork.

Six station labels filter the existing statuses. Each station shows up to four clickable
job pins and two assigned pixel technicians; extra jobs are summarized as `+N`. The bottom
monitor counts all filtered jobs, technicians, waiting-parts work and pending handovers.
Empty stations do not invent jobs or staff. Customer scope and the server-authorized save
form remain unchanged. Closing details opened from a pin returns keyboard focus to that pin.

CSS animates technician work/walking gestures and waiting-parts indicators. The motion
button pauses animation. Reduced-motion preferences disable it and hidden tabs pause it.
There is no render loop, polling, external AI service at runtime, new database table or
OpenClaw/Officestra dependency. Refresh reads the latest authorized data.

Verification: Python 111 + Node 27 tests pass. Renderer tests cover empty stations,
keyboard actions, literal text, pending dispatch and bounded rendering of 1,000 jobs
(maximum 24 job pins / 12 technician figures). Browser checks cover station filtering,
motion controls and light/dark themes. Visual layout fixtures are exported separately under
ignored artifacts and are never seeded into operational data.

## Interactive 3D office

The default board now lazy-loads a same-origin Three.js 0.186.1 scene. Users can orbit,
zoom, reset the camera, open native job buttons and switch to the existing illustrated
view. WebGL initialization/context failures fall back to the illustration. No CDN,
new API, database change, status inference or automatic stock/Odoo write is involved.

Six stations use the same authorized filtered ticket snapshot and existing detail/save
flow. Up to 24 printer/job markers and 12 assigned technician figures are rendered;
summary totals still count all matching records. Technician movement is symbolic,
not location tracking: figures walk along the aisle between assigned workstations.
Empty datasets create no fictional workers or tickets.

Rendering is capped near 30 fps and pixel ratio 1.5. Hidden/offscreen scenes stop;
reduced-motion preferences and the pause control stop walking. Static scenes stop
requesting frames once camera damping settles. Keyboard camera controls and native
job buttons remain available. Three.js sources are vendored with MIT attribution;
the two build modules are minified to about 748 KiB combined.

Verification: 32 Node tests cover both renderers/core routing and existing tours;
Python regression tests cover the unchanged authorization and ticket update flows.
A separate ignored browser fixture exercises walking and opening job details without
seeding operational records. The earlier no-render-loop statement applies to the
illustrated view only.
