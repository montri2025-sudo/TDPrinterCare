"""Generate Thai demo narration locally. Reference recording stays outside static/Git.
Usage: <PrintScape voice venv>/bin/python tools/make-customer-demo-voice.py --reference /path/reference.wav
Only use a reference owned or explicitly authorized by the speaker.
"""
import argparse, gc, hashlib, inspect, json, os, re, subprocess, time
from pathlib import Path
os.environ.setdefault('HF_HUB_OFFLINE', '1')
os.environ.setdefault('VOXCPM_MPS_DTYPE', 'float32')
os.environ.setdefault('PYTORCH_MPS_HIGH_WATERMARK_RATIO', '1.0')
os.environ.setdefault('PYTORCH_MPS_LOW_WATERMARK_RATIO', '0.8')
ROOT = Path(__file__).resolve().parents[1]
REFERENCE_TEXT = 'สวัสดีครับ ยินดีต้อนรับสู่ร้านพิมพ์สามมิติของเรา วันนี้ผมจะพาไปดูการทำงาน ตั้งแต่รับออเดอร์ เตรียมไฟล์ พิมพ์ชิ้นงาน ตรวจคุณภาพ จนส่งถึงมือลูกค้าครับ'

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--reference', required=True)
    args = parser.parse_args()
    import numpy as np
    import torch
    import soundfile as sf
    from voxcpm import VoxCPM
    reference = str(Path(args.reference).resolve(strict=True))
    out = ROOT / 'static/customer-demo-voice'
    out.mkdir(exist_ok=True)
    lines = list(dict.fromkeys(re.findall(r"step\('[^']*','[^']*','([^']*)'\)", (ROOT / 'static/customer-demo.js').read_text())))
    manifest_path = out / 'manifest.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    todo = [text for text in lines if text not in manifest or not (out / manifest[text]).exists()]
    print(f'{len(lines)} Thai lines; {len(todo)} to generate', flush=True)
    if not todo:
        return
    from huggingface_hub import snapshot_download
    cached = Path(snapshot_download('openbmb/VoxCPM2', local_files_only=True))
    compact = ROOT / 'artifacts/customer-voice/model'
    compact.mkdir(parents=True, exist_ok=True)
    for item in cached.iterdir():
        if item.name != 'config.json' and not (compact / item.name).exists():
            (compact / item.name).symlink_to(item, target_is_directory=item.is_dir())
    config = json.loads((cached / 'config.json').read_text())
    # Short guides + 17-second reference fit comfortably; avoid an 8192-token KV cache.
    config['max_length'] = 2048
    (compact / 'config.json').write_text(json.dumps(config))
    model = VoxCPM.from_pretrained(str(compact), load_denoiser=False, optimize=False)
    allowed = inspect.signature(model._generate if hasattr(model, '_generate') else model.generate).parameters
    for index, text in enumerate(todo, 1):
        started = time.time()
        np.random.seed(42); torch.manual_seed(42)
        options = dict(text=text, prompt_wav_path=reference, prompt_text=REFERENCE_TEXT,
                       reference_wav_path=reference, cfg_value=2.0, inference_timesteps=10,
                       normalize=False, denoise=False, retry_badcase=True, max_len=1024)
        wav = model.generate(**{k: v for k, v in options.items() if k in allowed})
        name = hashlib.sha256(text.encode()).hexdigest()[:16]
        temp = ROOT / 'artifacts/customer-voice' / (name + '.wav')
        temp.parent.mkdir(parents=True, exist_ok=True)
        sf.write(temp, wav, model.tts_model.sample_rate, subtype='PCM_16')
        subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', str(temp), '-af',
                        'silenceremove=start_periods=1:start_threshold=-50dB,areverse,silenceremove=start_periods=1:start_threshold=-50dB,areverse,loudnorm=I=-16:TP=-1.5',
                        '-ac', '1', '-ar', '44100', '-b:a', '80k', str(out / (name + '.mp3'))], check=True)
        del wav
        gc.collect()
        if torch.backends.mps.is_available():
            torch.mps.synchronize()
            torch.mps.empty_cache()
        manifest[text] = name + '.mp3'
        draft = manifest_path.with_suffix('.tmp')
        draft.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
        draft.replace(manifest_path)
        print(f'[{index}/{len(todo)}] {time.time()-started:.0f}s {name}', flush=True)

if __name__ == '__main__':
    main()
