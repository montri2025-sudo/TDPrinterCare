# Thai customer Demo narration

These MP3s are generated locally with VoxCPM2 from the application owner's
explicitly supplied and authorized voice sample. They contain fixed Thai Demo
instructions only. `manifest.json` maps exact guide text to an MP3 filename.

The source recording, normalized reference, model weights and intermediate WAVs
are intentionally kept outside this public directory and excluded from Git.
Generation is an offline build task; the application only plays these files.

Regenerate with `tools/make-customer-demo-voice.py` using the installed PrintScape
voice environment and a reference recorded with the script's `REFERENCE_TEXT`.
The tool resumes missing lines and publishes its manifest atomically. It uses a
smaller inference cache and clears GPU cache between lines for short guides.
