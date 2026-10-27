"""Every shipped tour instruction must have the owner's recorded narration, not captions-only fallback."""
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('voice_tool',ROOT/'tools/make-field-service-voice.py')
voice=importlib.util.module_from_spec(spec)
spec.loader.exec_module(voice)

class TestDemoVoiceAssets(unittest.TestCase):
    def test_staff_and_field_tours_have_complete_matching_narration(self):
        for source,regex,out in voice.TARGETS:
            with self.subTest(tour=source.name):
                lines=voice.lines_of(source,regex)
                manifest=json.loads((out/'manifest.json').read_text())
                self.assertEqual(set(lines),set(manifest),'Missing or stale spoken instructions')
                for text,name in manifest.items():
                    self.assertEqual(name,hashlib.sha256(text.encode()).hexdigest()[:16]+'.mp3')
                    file=out/name
                    self.assertTrue(file.is_file(),name)
                    self.assertGreater(file.stat().st_size,2000,name)
                    header=file.read_bytes()[:3]
                    self.assertTrue(header==b'ID3' or header[:1]==b'\xff',name)
    def test_original_recording_and_models_are_not_shipped_in_voice_folders(self):
        for _,_,out in voice.TARGETS:
            self.assertFalse(list(out.glob('*.wav')))
            self.assertFalse(list(out.glob('*.m4a')))
            self.assertFalse(list(out.glob('*.safetensors')))
