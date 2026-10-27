"""Generate Thai narration for the staff Demos (field-service tabs + every staff menu), locally and offline.

Same method as tools/make-customer-demo-voice.py (PrintScape VoxCPM2 install + the owner's
authorized reference recording), but reads the step(...) lines of static/field-service-tour.js
-> static/field-service-voice/ and of static/staff-demo.js -> static/staff-demo-voice/. The reference recording, model files and WAVs stay
in ignored artifacts/; nothing is uploaded anywhere.

Usage (on the owner's Mac):
  <PrintScape voice venv>/bin/python tools/make-field-service-voice.py \
      --reference artifacts/customer-voice/reference.wav
  add --dry-run to only list which lines would be generated / removed.
"""
import argparse, gc, hashlib, inspect, json, os, re, subprocess, time
from pathlib import Path

os.environ.setdefault('HF_HUB_OFFLINE', '1')
os.environ.setdefault('VOXCPM_MPS_DTYPE', 'float32')
os.environ.setdefault('PYTORCH_MPS_HIGH_WATERMARK_RATIO', '1.0')
os.environ.setdefault('PYTORCH_MPS_LOW_WATERMARK_RATIO', '0.8')
ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'artifacts/field-service-voice'
# Must match the transcript of the reference recording (same as the customer Demo tool).
REFERENCE_TEXT = 'สวัสดีครับ ยินดีต้อนรับสู่ร้านพิมพ์สามมิติของเรา วันนี้ผมจะพาไปดูการทำงาน ตั้งแต่รับออเดอร์ เตรียมไฟล์ พิมพ์ชิ้นงาน ตรวจคุณภาพ จนส่งถึงมือลูกค้าครับ'
TARGETS = [
    # (source script, regex capturing the narration text, output folder)
    (ROOT / 'static/field-service-tour.js', re.compile(r"step\('[^']*', '[^']*', '[^']*', '([^']*)'\)"), ROOT / 'static/field-service-voice'),
    (ROOT / 'static/staff-demo.js', re.compile(r"step\('[^']*', '[^']*', '([^']*)'\)"), ROOT / 'static/staff-demo-voice'),
]


def lines_of(source, regex):
    return list(dict.fromkeys(regex.findall(source.read_text(encoding='utf-8'))))


def write_manifest(out, manifest):
    path = out / 'manifest.json'
    draft = path.with_suffix('.tmp')
    draft.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    draft.replace(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--reference', required=True)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    reference = Path(args.reference).resolve(strict=True)
    if (ROOT / 'static') in reference.parents:
        raise SystemExit('reference must stay outside static/')
    jobs = []
    for source, regex, out in TARGETS:
        out.mkdir(exist_ok=True)
        lines = lines_of(source, regex)
        path = out / 'manifest.json'
        manifest = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        stale = [t for t in manifest if t not in lines]
        todo = [t for t in lines if t not in manifest or not (out / manifest[t]).exists()]
        print(f'{source.name}: {len(lines)} Thai lines; {len(todo)} to generate; {len(stale)} stale', flush=True)
        if args.dry_run:
            for t in todo: print('  + ' + t)
            for t in stale: print('  - ' + t)
            continue
        for t in stale:                      # never keep narration that describes something else
            (out / manifest.pop(t)).unlink(missing_ok=True)
        write_manifest(out, manifest)
        jobs += [(out, manifest, t) for t in todo]
    if args.dry_run or not jobs:
        return
    import numpy as np
    import torch
    import soundfile as sf
    from voxcpm import VoxCPM
    from huggingface_hub import snapshot_download
    cached = Path(snapshot_download('openbmb/VoxCPM2', local_files_only=True))
    compact = WORK / 'model'
    compact.mkdir(parents=True, exist_ok=True)
    for item in cached.iterdir():
        if item.name != 'config.json' and not (compact / item.name).exists():
            (compact / item.name).symlink_to(item, target_is_directory=item.is_dir())
    config = json.loads((cached / 'config.json').read_text())
    config['max_length'] = 2048
    (compact / 'config.json').write_text(json.dumps(config))
    model = VoxCPM.from_pretrained(str(compact), load_denoiser=False, optimize=False)
    allowed = inspect.signature(model._generate if hasattr(model, '_generate') else model.generate).parameters
    for index, (out, manifest, text) in enumerate(jobs, 1):
        started = time.time()
        np.random.seed(42); torch.manual_seed(42)
        options = dict(text=text, prompt_wav_path=str(reference), prompt_text=REFERENCE_TEXT,
                       reference_wav_path=str(reference), cfg_value=2.0, inference_timesteps=10,
                       normalize=False, denoise=False, retry_badcase=True, max_len=1024)
        wav = model.generate(**{k: v for k, v in options.items() if k in allowed})
        name = hashlib.sha256(text.encode()).hexdigest()[:16]
        temp = WORK / (name + '.wav')
        sf.write(temp, wav, model.tts_model.sample_rate, subtype='PCM_16')
        subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', str(temp), '-af',
                        'silenceremove=start_periods=1:start_threshold=-50dB,areverse,silenceremove=start_periods=1:start_threshold=-50dB,areverse,loudnorm=I=-16:TP=-1.5',
                        '-ac', '1', '-ar', '44100', '-b:a', '80k', str(out / (name + '.mp3'))], check=True)
        del wav
        gc.collect()
        if torch.backends.mps.is_available():
            torch.mps.synchronize(); torch.mps.empty_cache()
        manifest[text] = name + '.mp3'
        write_manifest(out, manifest)
        print(f'[{index}/{len(jobs)}] {time.time() - started:.0f}s {out.name}/{name}', flush=True)


if __name__ == '__main__':
    main()
