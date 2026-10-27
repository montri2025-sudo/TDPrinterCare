# Thai narration for the read-only staff guide

Generated offline with `tools/make-field-service-voice.py` from the owner’s authorized reference,
the same voice used by the customer Demo. Reference audio stays in ignored artifacts/.
`manifest.json` maps every exact fixed `step(...)` instruction in static/staff-demo.js to an MP3.
This includes the operational field-service page. The retired fictional field-service example is not shipped.
No real customer/job information is narrated or sent to an external speech service.

Run `python3 tools/check_demo_voice.py` to verify completeness and decode every clip.
Muted/blocked playback keeps Thai captions available; it never substitutes another voice.
