"""Validate complete fixed narration manifests and decode all MP3s. Read-only, local tools only."""
import importlib.util
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('voice_generation',ROOT/'tools/make-field-service-voice.py')
voice=importlib.util.module_from_spec(spec);spec.loader.exec_module(voice)
for source,regex,out in voice.TARGETS:
    expected=set(voice.lines_of(source,regex))
    manifest=json.loads((out/'manifest.json').read_text())
    if set(manifest)!=expected:
        raise SystemExit(f'{source.name}: {len(expected-set(manifest))} missing, {len(set(manifest)-expected)} stale')
    total=0
    for file in manifest.values():
        path=out/file
        subprocess.run(['ffmpeg','-v','error','-i',str(path),'-f','null','-'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        seconds=float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',str(path)]))
        if not 1<seconds<120:
            raise SystemExit(f'{file}: unexpected duration {seconds}')
        total+=seconds
    print(f'{source.name}: {len(manifest)} clips decode successfully; {total:.1f} seconds')
