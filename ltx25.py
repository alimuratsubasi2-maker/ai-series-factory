"""LTX-2.5 (yerel, GGUF) ile görselden sesli video: tek aşamalı, düşük VRAM ayarı.

Kullanım:  python ltx25.py <baslangic.png> "<prompt>" <cikti.mp4> [saniye] [genislik] [yukseklik] [seed]
Prompt İngilizce sahne tarifi + tırnak içinde konuşma ("She says: \"...\"") olabilir; model sesi de üretir.
"""
import json
import re
import shutil
import sys
import time
import urllib.request
import uuid
from pathlib import Path

from PIL import Image

COMFY_KOK = Path(r"C:\ComfyUI_windows_portable")
COMFY = "http://127.0.0.1:8188"

UNET = "ltx-2.5-22b-distilled-UD-Q2_K_XL.gguf"
CLIP = "gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors"
VAE_V = "ltx-2.5-video-vae-bf16.safetensors"
VAE_A = "ltx-2.5-audio-vae-bf16.safetensors"
NEG = ("pc game, video game, cartoon, childish, ugly, blurry, distorted face, text, subtitles, captions, letters, words, "
       "writing, typography, on-screen text, lower third, watermark, logo")


def temizle(prompt: str) -> str:
    """Olumlu prompt'taki 'no text / no subtitles' gibi ifadeler LTX'e tam tersine altyazı çizdiriyor (ölçüldü):
    bunları çıkar, yasakları sadece negatif prompt'ta tut."""
    return re.sub(r"\s*\b[Nn]o (on-screen )?(text|subtitles?|captions?|letters|writing|watermarks?)\b[^.]*\.?", "", prompt).strip()
# distilled modelin şablondaki 1. aşama sigma dizisi (8 adım)
SIGMAS = "1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0"


def graf(resim_adi: str, prompt: str, saniye: float, w: int, h: int, seed: int, fps: int = 24) -> dict:
    kare = int(round(saniye * fps / 8)) * 8 + 1  # LTX 8n+1 kare ister
    return {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": UNET}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": CLIP, "type": "ltxv", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": VAE_V}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": VAE_A}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": NEG, "clip": ["2", 0]}},
        "7": {"class_type": "LTXVConditioning", "inputs": {"positive": ["5", 0], "negative": ["6", 0], "frame_rate": fps}},
        "8": {"class_type": "LoadImage", "inputs": {"image": resim_adi}},
        "9": {"class_type": "LTXVPreprocess", "inputs": {"image": ["8", 0], "img_compression": 18}},
        "10": {"class_type": "EmptyLTXVLatentVideo", "inputs": {"width": w, "height": h, "length": kare, "batch_size": 1}},
        "11": {"class_type": "LTXVImgToVideoInplace", "inputs": {"vae": ["3", 0], "image": ["9", 0], "latent": ["10", 0],
                                                                 "strength": 1.0, "bypass": False}},
        "12": {"class_type": "LTXVEmptyLatentAudio", "inputs": {"audio_vae": ["4", 0], "frames_number": kare,
                                                                "frame_rate": fps, "batch_size": 1}},
        "13": {"class_type": "LTXVConcatAVLatent", "inputs": {"video_latent": ["11", 0], "audio_latent": ["12", 0]}},
        "14": {"class_type": "LTXVDualCFGGuider", "inputs": {"model": ["1", 0], "positive": ["7", 0], "negative": ["7", 1],
                                                             "video_cfg": 1.0, "audio_cfg": 1.0}},
        "15": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler_ancestral"}},
        "16": {"class_type": "ManualSigmas", "inputs": {"sigmas": SIGMAS}},
        "17": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "18": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["17", 0], "guider": ["14", 0], "sampler": ["15", 0],
                                                                 "sigmas": ["16", 0], "latent_image": ["13", 0]}},
        "19": {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": ["18", 0]}},
        "20": {"class_type": "VAEDecodeTiled", "inputs": {"samples": ["19", 0], "vae": ["3", 0], "tile_size": 512,
                                                          "overlap": 64, "temporal_size": 64, "temporal_overlap": 16}},
        "21": {"class_type": "LTXVAudioVAEDecode", "inputs": {"samples": ["19", 1], "audio_vae": ["4", 0]}},
        "22": {"class_type": "CreateVideo", "inputs": {"images": ["20", 0], "audio": ["21", 0], "fps": fps}},
        "23": {"class_type": "SaveVideo", "inputs": {"video": ["22", 0], "filename_prefix": "dizi_ltx",
                                                     "format": "mp4", "codec": "h264"}},
    }


def uret(baslangic: Path, prompt: str, cikti: Path, saniye=4.0, w=448, h=768, seed=42, zaman_asimi=5400) -> Path:
    ad = f"dizi_{uuid.uuid4().hex[:8]}.png"
    Image.open(baslangic).convert("RGB").resize((w, h), Image.LANCZOS).save(COMFY_KOK / "ComfyUI" / "input" / ad)
    g = graf(ad, temizle(prompt), saniye, w, h, seed)
    req = urllib.request.Request(COMFY + "/prompt", data=json.dumps({"prompt": g, "client_id": str(uuid.uuid4())}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        pid = json.loads(urllib.request.urlopen(req, timeout=60).read())["prompt_id"]
    except urllib.error.HTTPError as e:
        raise RuntimeError("ComfyUI isteği reddetti: " + e.read().decode("utf-8", "replace")[:1500])
    return bekle(pid, cikti, zaman_asimi)


def bekle(pid: str, cikti: Path, zaman_asimi=5400) -> Path:
    bas = time.time()
    while time.time() - bas < zaman_asimi:
        try:
            # RAM sanal belleğe taşınca ComfyUI dakikalarca cevapsız kalabiliyor; bu bir hata değil, beklemeye devam
            h_ = json.loads(urllib.request.urlopen(f"{COMFY}/history/{pid}", timeout=120).read())
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(10)
            continue
        if pid in h_:
            st = h_[pid].get("status", {})
            if st.get("status_str") == "error":
                raise RuntimeError("ComfyUI hatası: " + json.dumps(st, ensure_ascii=False)[-1500:])
            outs = h_[pid].get("outputs") or {}
            for o in outs.values():
                for k in ("images", "videos", "gifs"):
                    for f in o.get(k, []):
                        shutil.copy(COMFY_KOK / "ComfyUI" / "output" / f.get("subfolder", "") / f["filename"], cikti)
                        print(f"TAMAM {cikti} ({time.time() - bas:.0f} sn)")
                        return cikti
        time.sleep(5)
    raise RuntimeError("zaman aşımı")


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "bekle":  # python ltx25.py bekle <prompt_id> <cikti.mp4>  (kopan istemciyi yeniden bağla)
        bekle(a[1], Path(a[2]))
        sys.exit()
    uret(Path(a[0]), a[1], Path(a[2]), *(float(a[3]),) if len(a) > 3 else (),
         **({"w": int(a[4]), "h": int(a[5])} if len(a) > 5 else {}), **({"seed": int(a[6])} if len(a) > 6 else {}))
