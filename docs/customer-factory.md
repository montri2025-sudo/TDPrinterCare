# Customer Virtual Factory

`/customer/dashboard` displays the signed-in customer's registered devices in
FDM, Resin, Wash & Cure and Other rooms. Counts include inactive devices, whose
grey status remains visible. The original dashboard and map are expandable below.

Room placement is a visual grouping, not live location or machine telemetry.
Green means ready according to records, blue means an open repair, amber means
maintenance is due, and grey means sold or decommissioned. Maintenance alerts
remain visible when a device also has an open repair. Inactive devices do not
generate due alerts. Clicking a device opens its details and existing care/history
links. All device data comes from the existing owner-scoped dashboard results.

The Demo starts on an explicit button press, then advances after each Thai audio
clip ends. With “continue across menus” enabled (the default), it visits Dashboard,
Virtual Office, maintenance, tickets, new repair, registration and tracking in
order, then stops. It never submits forms or changes recorded customer data.
Pause, previous, next, close and mute controls remain available. Hidden tabs pause
playback; returning requires Resume. If browser autoplay is blocked, Resume is
shown instead of silently advancing. Muted playback uses timed Thai captions.

Narration is generated locally with the existing PrintScape VoxCPM2 installation
from the user's explicitly supplied recording. The normalized reference matched
PrintScape's existing reference byte for byte, so its paired Thai transcript is
reused. The raw/normalized voice reference remains in ignored artifacts; only
fixed demo narration MP3s and their text manifest are served. No personal machine
records are narrated or sent to an external speech provider. A local Thai browser
voice is a fallback when an audio file is unavailable. No voice selector is shown.

The shared Demo also covers ticket details, notifications and device care pages.
The guide is excluded. Mute preferences persist for the browser session. Voice
generation runs offline as a build task, never within the web server. Regenerate
with `tools/make-customer-demo-voice.py` and an authorized reference recording.

The amber LED pulses slowly, can be paused and respects reduced-motion settings.
Rendering uses HTML/CSS and local filtering, with no polling or 3D dependencies.
There is no new schema or additional device query for this view.

Verification: 81 unit tests pass, including customer isolation, missing customer
binding, inactive devices, unknown types, safe JSON and combined repair/due
status. Browser verification used a disposable fictional database and covered
all five Demo steps and the device detail dialog. Production deployment and load
testing are not part of this change. Four Node playback tests cover audio completion,
pause/cancellation, muted menu continuation, autoplay rejection and guide exclusion.

All 28 narration clips were generated and decoded successfully: 195.7 seconds
total, 1.89 MiB of MP3 audio. The browser preview confirmed recorded playback
and automatic progression from Dashboard through subsequent customer menus.

## Appearance

The shared top bar has a Light/Dark theme button on all pages using the base
layout. The choice is applied before the page renders, saved in local storage,
retained across navigation and synchronized across tabs. Without storage access,
the button still works for the current page. The default is dark.

Room styles use color tokens with the original dark colors as fallbacks; the
light palette changes surfaces, text and borders while retaining colored status
indicators. Common navigation, forms, cards and Demo controls follow the selected
theme. No server-side preference, database change or new frontend dependency is
required. Theme behavior has three Node tests; browser checks cover both themes
and retention from the customer dashboard to maintenance.
