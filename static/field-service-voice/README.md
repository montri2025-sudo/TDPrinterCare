# Thai narration for the field-service Demo

`manifest.json` maps the exact narration text of each `step(...)` in
`static/field-service-tour.js` to an MP3 in this folder. It starts empty: until the
clips are generated, the Demo shows timed Thai captions (no substitute voice).

Generate locally on the owner's Mac with the existing PrintScape VoxCPM2 environment
and the owner's authorized reference recording (kept in ignored `artifacts/`):

    <PrintScape voice venv>/bin/python tools/make-field-service-voice.py \
        --reference artifacts/customer-voice/reference.wav

Only fixed Demo instructions are narrated. The reference recording, model weights and
intermediate WAVs never go into this folder or Git, and nothing is sent to an external
speech service. Lines whose text changes are regenerated; stale entries are removed.
