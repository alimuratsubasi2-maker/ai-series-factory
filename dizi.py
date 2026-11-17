"""AI Dizi Fabrikası: tek cümle -> dizi kitabı -> kadro kartları -> bölüm (LTX-2.5 sesli sahneler) -> önizleme -> YouTube + Instagram.

Komutlar (sistem python'u ile):
  python dizi.py kitap <slug> "<tek cümlelik fikir>"   dizi kitabı (karakterler, mekânlar, 5 bölüm akışı)
  python dizi.py kadro <slug>                          karakter + mekân kartlarını çiz
  python dizi.py bolum <slug> <no>                     bölümü üret, 4'lü kontrol, montaj, önizlemeyi aç
  python dizi.py yayinla <slug> <no>                   (onaydan sonra) önce YouTube, sonra Instagram
  python dizi.py yayinla_hepsi <slug>                  (onaydan sonra) dizinin tüm bölümleri sırayla
  python dizi.py fabrika                               sürekli: 5 bölüm üret -> bildir -> yeni senaryo (DURDUR dosyası durdurur)

Her adım çıktısını diske yazar, varsa atlar: yarıda kalan iş kaldığı yerden devam eder.
Her bölümün durumu diziler/<slug>/bolum_<no>/durum.json'a yazılır (JARVIS kanal_durum.py ile okur).
"""
import datetime as dt
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

try:  # Avast HTTPS'e kendi sertifikasını sokuyor
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

from PIL import Image

import ltx25

KOK = Path(__file__).resolve().parent
AYAR = json.loads((KOK / "ayarlar.json").read_text(encoding="utf-8"))
DIZILER = KOK / "diziler"
COMFY_KOK = Path(r"C:\ComfyUI_windows_portable")
COMFY = "http://127.0.0.1:8188"
OM = Path(r"C:\Users\MSI\Desktop\YAPAY ZEKA PROJELER\OpenMontage")
YT_PY = OM / ".venv" / "Scripts" / "python.exe"
YT_UPLOAD = OM / "youtube" / "youtube_upload.py"
IG_DIR = Path(r"C:\Users\MSI\Desktop\ETSY MAGAZASI İÇİN ÜRÜNLER\instagram-otomasyon")
NO_WINDOW = 0x08000000
W, H, FPS = 1080, 1920, 30

SDXL = "juggernautXL_v9.safetensors"
SDXL_NEG = ("text, watermark, logo, signature, letters, caption, blurry, lowres, deformed, disfigured, extra fingers, "
            "extra limbs, bad anatomy, cartoon, anime, drawing, painting, cgi, plastic skin, ugly, duplicate")


def log(m):
    print(f"[{dt.datetime.now():%H:%M:%S}] {m}", flush=True)


def calistir(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, creationflags=NO_WINDOW, **kw)
    if r.returncode:
        err = r.stderr.decode("utf-8", "replace") if isinstance(r.stderr, bytes) else r.stderr
        raise RuntimeError(f"{Path(str(cmd[0])).name} hata verdi: {err[-800:]}")
    return r


def sure(dosya) -> float:
    return float(calistir(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(dosya)],
                          text=True).stdout.strip())


def durum_yaz(bdir: Path, **alanlar):
    f = bdir / "durum.json"
    d = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"youtube": None, "instagram": None}
    d.update(alanlar, guncelleme=dt.datetime.now().strftime("%d.%m.%Y %H:%M"))
    f.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- claude -p (senaryo yazarı)

def claude_json(prompt: str, kontrol) -> dict:
    claude = shutil.which("claude") or str(Path.home() / "AppData/Roaming/npm/claude.cmd")
    hata = ""
    for _ in range(3):
        p = prompt + (f"\n\nÖNCEKİ DENEMEN GEÇERSİZDİ ({hata}). Sadece geçerli JSON yaz." if hata else "")
        r = subprocess.run([claude, "-p", "--output-format", "text"], input=p, capture_output=True, text=True,
                           encoding="utf-8", timeout=600, cwd=str(KOK), creationflags=NO_WINDOW)
        m = re.search(r"\{.*\}", r.stdout or "", re.S)
        try:
            d = json.loads(m.group(0)) if m else None
            if not d:
                raise ValueError("JSON yok: " + (r.stdout or r.stderr or "")[-200:])
            kontrol(d)
            return d
        except (ValueError, KeyError, TypeError, AssertionError, json.JSONDecodeError) as e:
            hata = str(e)[:200] or type(e).__name__
            log(f"senaryo denemesi geçersiz: {hata}")
    raise RuntimeError("Claude geçerli JSON üretemedi: " + hata)


KITAP_PROMPT = """Sen YouTube Shorts / Instagram Reels için kısa Türkçe dizi yazan bir senaristsin. Aşağıdaki tek cümlelik
fikirden 5 bölümlük, her bölümü ~55 saniye olan, merak uyandıran, duygusal ve sürükleyici bir dizinin "dizi kitabını" çıkar.

FİKİR: {fikir}

KURALLAR
- 3 ya da 4 karakter. Her karakterin TEK bir "kart" görseli olacak: karakter, dizide en çok bulunduğu mekânda,
  göğüs hizasından (medium close-up), kameraya yakın bakarken. Sahneler bu kartı ilk kare olarak kullanacak; o yüzden
  karakteri hep o mekânda düşün.
- "kart_prompt": İNGİLİZCE, Stable Diffusion XL için fotogerçekçi tek kare: yaş, cinsiyet, Türk görünümü, saç, kıyafet,
  belirgin özellik + mekân + ışık; sonuna "vertical 9:16 cinematic film still, 35mm, highly detailed, realistic skin" ekle.
  Yazı/tabela/logo olmasın.
- "gorunum": İNGİLİZCE kısa görünüm tarifi (video modelinin prompt'unda tekrar kullanılacak).
- "ses": İNGİLİZCE ses tarifi (örn. "soft trembling elderly female voice").
- 2-4 mekân kartı (insansız): "kart_prompt" İNGİLİZCE, aynı fotogerçekçi stil, "no people" ekle.
- "id"ler küçük harf, Türkçe karaktersiz, alt çizgili (örn. "nadide", "vapur_ic").
- 5 bölüm: her biri tek cümle özet; her bölüm bir sır/soru ile bitsin (cliffhanger).

ÇIKTI: SADECE şu şemada geçerli JSON:
{{"ad": "...", "logline": "...", "ton": "...",
  "karakterler": [{{"id": "...", "ad": "...", "rol": "...", "kart_prompt": "...", "gorunum": "...", "ses": "..."}}],
  "mekanlar": [{{"id": "...", "ad": "...", "kart_prompt": "..."}}],
  "bolumler": [{{"no": 1, "baslik": "...", "ozet": "..."}}]}}
"""

BOLUM_PROMPT = """Sen kısa Türkçe dizi senaristisin. Aşağıdaki dizi kitabına göre {no}. bölümün çekim senaryosunu yaz.

DİZİ KİTABI:
{kitap}

{onceki}
{taslak}
KURALLAR
- {s_min} ile {s_max} arası sahne, toplam {t_min}-{t_max} saniye (YouTube Shorts / Reels üst sınırı 180 sn, AŞMA).
  Her sahne {sn_min}-{sn_max} saniye. Bölümün özetindeki olayları acele etmeden, karakterler arası diyalogla anlat;
  sahnelerin en az üçte ikisi replikli olsun, sessiz mekân sahneleri geçiş/atmosfer için kullanılsın.
- Her sahne bir KART ile başlar ("kart": karakter id'si ya da mekân id'si). Video modeli o kartı ilk kare yapıp canlandırır;
  bu yüzden sahnedeki eylem kartın mekânında ve kartta görünen kişiyle geçmeli. Konuşan karakterin sahnesinde "kart" o karakter.
- "replik": o sahnede kartın karakterinin söylediği TÜRKÇE cümle (en fazla 12 kelime, doğal, günlük dil, rakamları yazıyla)
  ya da sessiz/atmosfer sahnesi için "". Mekân kartı sahnelerinde replik "" olsun.
- "ltx": İNGİLİZCE video prompt'u, ŞU KALIPTA: "Use the provided image as the first frame. <karakterin gorunum tarifi>
  <tek ve basit eylem>. <Replik varsa:> She/He says in Turkish with a <ses tarifi>: \\"<replik aynen>\\". <kamera hareketi>.
  <ortam sesleri>." Prompt'ta "text", "subtitles", "caption" kelimelerini HİÇ kullanma. Karmaşık aksiyon, sahne değişimi, yeni kişi ekleme YOK.
- İlk sahne merak uyandırsın (kanca), son sahne bir sırla/soruyla bitsin.
- "baslik": en fazla 70 karakter, "{ad} | Bölüm {no}: ..." biçiminde, sonunda " #Shorts".
- "aciklama": 2 cümle Türkçe bölüm açıklaması (spoiler yok).
- "etiketler": 8-12 kısa Türkçe etiket. "hashtagler": 5-8 hashtag (tek satır, # ile).

ÇIKTI: SADECE şu şemada geçerli JSON:
{{"baslik": "...", "aciklama": "...", "etiketler": ["..."], "hashtagler": "#...",
  "sahneler": [{{"kart": "...", "replik": "...", "ltx": "...", "saniye": 6, "eski_no": null}}]}}
"""

TASLAK_EK = """MEVCUT KISA TASLAK (bu bölümün daha önce yazılmış kısa hali; bazı sahneleri zaten çekildi):
{taslak}
Bu taslağı istenen uzunluğa GENİŞLET. Taslaktaki sahneler {cekilen} numaralı olanlar ÇEKİLDİ: bunları yeni senaryoda
kart, replik, ltx ve saniye alanları BİREBİR AYNI olacak şekilde, mantıklı sırada kullan ve "eski_no" alanına taslaktaki
numarasını yaz. Diğer tüm sahnelerde "eski_no": null.
"""


def kitap(slug: str, fikir: str):
    ddir = DIZILER / slug
    f = ddir / "kitap.json"
    if f.exists():
        log(f"kitap zaten var: {f}")
        return json.loads(f.read_text(encoding="utf-8"))
    ddir.mkdir(parents=True, exist_ok=True)

    def kontrol(d):
        assert 2 <= len(d["karakterler"]) <= 5 and d["mekanlar"] and len(d["bolumler"]) >= 3
        for k in d["karakterler"] + d["mekanlar"]:
            assert k["id"] and k["kart_prompt"]

    d = claude_json(KITAP_PROMPT.format(fikir=fikir), kontrol)
    d["fikir"] = fikir
    f.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"kitap yazıldı: {d['ad']} — {d['logline']}")
    return d


# ---------------------------------------------------------------- ComfyUI

def comfy_hazir() -> bool:
    try:
        urllib.request.urlopen(COMFY + "/system_stats", timeout=5)
        return True
    except Exception:
        return False


def comfy_baslat():
    if comfy_hazir():
        return
    log("ComfyUI başlatılıyor")
    out = open(COMFY_KOK / "comfy_log.txt", "ab")
    subprocess.Popen([str(COMFY_KOK / "python_embeded" / "python.exe"), "-s", "start_hidden.py"], cwd=str(COMFY_KOK),
                     stdout=out, stderr=subprocess.STDOUT, creationflags=NO_WINDOW | 0x01000000)  # BREAKAWAY_FROM_JOB
    for _ in range(150):
        if comfy_hazir():
            return
        time.sleep(2)
    raise RuntimeError("ComfyUI başlatılamadı")


def kart_ciz(prompt: str, seed: int, cikti: Path):
    if cikti.exists():
        return
    g = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": SDXL}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": SDXL_NEG, "clip": ["1", 1]}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 768, "height": 1344, "batch_size": 1}},
        "6": {"class_type": "KSampler", "inputs": {"seed": seed, "steps": 28, "cfg": 5.0, "sampler_name": "dpmpp_2m_sde",
                                                    "scheduler": "karras", "denoise": 1.0, "model": ["1", 0],
                                                    "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["5", 0]}},
        "7": {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0], "vae": ["1", 2]}},
        "8": {"class_type": "SaveImage", "inputs": {"filename_prefix": "dizi_kart", "images": ["7", 0]}},
    }
    req = urllib.request.Request(COMFY + "/prompt", data=json.dumps({"prompt": g, "client_id": str(uuid.uuid4())}).encode(),
                                 headers={"Content-Type": "application/json"})
    pid = json.loads(urllib.request.urlopen(req, timeout=60).read())["prompt_id"]
    bas = time.time()
    while time.time() - bas < 1200:
        try:
            h = json.loads(urllib.request.urlopen(f"{COMFY}/history/{pid}", timeout=120).read())
        except Exception:
            time.sleep(5)
            continue
        if pid in h and h[pid].get("outputs"):
            im = next(i for o in h[pid]["outputs"].values() for i in o.get("images", []))
            shutil.copy(COMFY_KOK / "ComfyUI" / "output" / im.get("subfolder", "") / im["filename"], cikti)
            return
        if pid in h and h[pid].get("status", {}).get("status_str") == "error":
            raise RuntimeError("kart çizilemedi: " + json.dumps(h[pid]["status"])[-400:])
        time.sleep(2)
    raise RuntimeError("kart zaman aşımı")


def kadro(slug: str):
    ddir = DIZILER / slug
    k = json.loads((ddir / "kitap.json").read_text(encoding="utf-8"))
    (ddir / "kadro").mkdir(exist_ok=True)
    comfy_baslat()
    for i, x in enumerate(k["karakterler"] + k["mekanlar"]):
        f = ddir / "kadro" / f"{x['id']}.png"
        if not f.exists():
            log(f"kart çiziliyor: {x['ad']}")
            kart_ciz(x["kart_prompt"], 1000 + i * 7, f)
    log(f"kadro hazır: {ddir / 'kadro'}")


# ---------------------------------------------------------------- 4'lü kontrol

_whisper = None


def yazıya_dok(video: Path) -> dict:
    global _whisper
    import whisper
    if _whisper is None:
        _whisper = whisper.load_model("small")
    wav = video.with_suffix(".wav")
    calistir(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", str(wav)])
    r = _whisper.transcribe(str(wav), language="tr", word_timestamps=True, fp16=False)
    wav.unlink(missing_ok=True)
    kelimeler = [(w["start"], w["end"], w["word"].strip()) for s in r["segments"] for w in s.get("words", [])]
    return {"metin": r["text"].strip(), "kelimeler": kelimeler}


def _sade(s: str) -> str:
    return re.sub(r"[^a-zçğıöşü ]", "", s.lower().replace("İ", "i").replace("I", "ı")).split().__str__()


YUZ_ESIK = 0.65  # SFace kosinüs: aynı kişi ~0.85, birbirine benzeyen iki farklı yaşlı kadın ~0.54 ölçüldü
_yuz = None


def _yuz_vektoru(img):
    import cv2
    global _yuz
    if _yuz is None:
        _yuz = (cv2.FaceDetectorYN_create(str(KOK / "modeller" / "yunet.onnx"), "", (320, 320), 0.7),
                cv2.FaceRecognizerSF_create(str(KOK / "modeller" / "sface.onnx"), ""))
    det, rec = _yuz
    h, w = img.shape[:2]
    det.setInputSize((w, h))
    _, yuzler = det.detect(img)
    if yuzler is None:
        return None
    f = max(yuzler, key=lambda r: r[2] * r[3])
    return rec.feature(rec.alignCrop(img, f))


def yuz_benzerligi(kart: Path, video: Path) -> float:
    """Kart yüzü ile klibin %40/%70/%95 karelerindeki yüzün en düşük benzerliği (yüz yoksa 0)."""
    import cv2
    a = _yuz_vektoru(cv2.imread(str(kart)))
    if a is None:
        return 1.0  # kartta yüz bulunamadıysa ölçemeyiz
    cap = cv2.VideoCapture(str(video))
    n = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    skorlar = []
    for oran in (0.4, 0.7, 0.95):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(n * oran))
        ok, kare = cap.read()
        b = _yuz_vektoru(kare) if ok else None
        skorlar.append(0.0 if b is None else float(_yuz[1].match(a, b, cv2.FaceRecognizerSF_FR_COSINE)))
    cap.release()
    return round(min(skorlar), 3)


def kontrol_et(video: Path, sahne: dict, karakter_karti: Path | None) -> dict:
    """Süre, dikey ölçü, ses, yüz. İlk üçü tutmazsa sahne reddedilir; yüz şüpheliyse rapora düşer."""
    pr = json.loads(calistir(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height", "-of", "json",
                              str(video)], text=True).stdout)["streams"]
    v = next((s for s in pr if s["codec_type"] == "video"), {})
    ses_var = any(s["codec_type"] == "audio" for s in pr)
    k = {"sure": sure(video) >= sahne["saniye"] - 0.4, "dikey": v.get("height", 0) > v.get("width", 1)}
    yz = yazıya_dok(video) if ses_var else {"metin": "", "kelimeler": []}
    k["duyulan"] = yz["metin"]
    k["kelimeler"] = yz["kelimeler"]
    if sahne.get("replik"):
        oran = difflib.SequenceMatcher(None, _sade(sahne["replik"]), _sade(yz["metin"])).ratio()
        k["ses_benzerlik"] = round(oran, 2)
        k["ses"] = ses_var and oran >= 0.55
    else:
        vol = calistir(["ffmpeg", "-i", str(video), "-af", "volumedetect", "-f", "null", "-"], text=True).stderr
        m = re.search(r"max_volume: (-?[\d.]+)", vol)
        k["ses"] = ses_var and m is not None and float(m.group(1)) > -45
    k["yuz"] = True
    if karakter_karti:
        try:
            k["yuz_benzerlik"] = yuz_benzerligi(karakter_karti, video)
            k["yuz"] = k["yuz_benzerlik"] >= YUZ_ESIK
        except Exception as e:  # yüz kontrolü sadece rapor içindir; hata üretimi durdurmasın
            k["yuz_hata"] = str(e)[:200]
    k["gecti"] = k["sure"] and k["dikey"] and k["ses"]
    return k


# ---------------------------------------------------------------- bölüm

def senaryo(slug: str, no: int) -> dict:
    ddir = DIZILER / slug
    bdir = ddir / f"bolum_{no}"
    f = bdir / "senaryo.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    k = json.loads((ddir / "kitap.json").read_text(encoding="utf-8"))
    onceki = []
    for n in range(1, no):
        pf = ddir / f"bolum_{n}" / "senaryo.json"
        if pf.exists():
            p = json.loads(pf.read_text(encoding="utf-8"))
            onceki.append(f"{n}. bölüm replikleri: " + " / ".join(s["replik"] for s in p["sahneler"] if s["replik"]))
    kartlar = {x["id"] for x in k["karakterler"] + k["mekanlar"]}
    sn = AYAR["sahne_saniye"]
    s_min, s_max = AYAR["sahne_sayisi"]
    t_min, t_max = AYAR["bolum_saniye"]

    # Kısa taslak (senaryo_kisa.json) varsa genişletilir; çekilmiş sahneleri eski/ klasörüne alıp yeni sıraya taşırız
    taslak, cekilen = "", []
    kisa = bdir / "senaryo_kisa.json"
    if kisa.exists():
        ks = json.loads(kisa.read_text(encoding="utf-8"))
        cekilen = [i + 1 for i in range(len(ks["sahneler"])) if (bdir / "eski" / f"sahne_{i + 1}_kontrol.json").exists()]
        taslak = TASLAK_EK.format(taslak=json.dumps(ks["sahneler"], ensure_ascii=False, indent=1),
                                  cekilen=", ".join(map(str, cekilen)) or "(hiçbiri)")

    def kontrol(d):
        assert s_min - 3 <= len(d["sahneler"]) <= s_max + 3 and d["baslik"], f"sahne sayısı {len(d['sahneler'])}"
        for s in d["sahneler"]:
            assert s["kart"] in kartlar, f"bilinmeyen kart {s['kart']}"
            assert s["ltx"]
            if not s.get("eski_no"):
                s["saniye"] = max(4, min(int(s.get("saniye", sn)), sn + 2))
            s.setdefault("replik", "")
        assert sum(s["saniye"] for s in d["sahneler"]) <= 178, "toplam süre 180 sn'yi aşıyor"

    d = claude_json(BOLUM_PROMPT.format(no=no, ad=k["ad"], kitap=json.dumps(k, ensure_ascii=False, indent=1),
                                        onceki="ÖNCEKİ BÖLÜMLER:\n" + "\n".join(onceki) if onceki else "",
                                        taslak=taslak, s_min=s_min, s_max=s_max, t_min=t_min, t_max=t_max,
                                        sn_min=sn - 2, sn_max=sn + 2), kontrol)
    if "#shorts" not in d["baslik"].lower():
        d["baslik"] = d["baslik"][:90] + " #Shorts"
    for i, s in enumerate(d["sahneler"]):
        e = s.get("eski_no")
        if e in cekilen:
            for son in (".mp4", "_kontrol.json"):
                shutil.copy(bdir / "eski" / f"sahne_{e}{son}", bdir / f"sahne_{i + 1}{son}")
            log(f"çekilmiş sahne korundu: taslak {e} -> yeni {i + 1}")
    f.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    return d


def sahne_uret(slug: str, no: int, i: int, s: dict, kitap_: dict) -> dict:
    ddir = DIZILER / slug
    bdir = ddir / f"bolum_{no}"
    cikti = bdir / f"sahne_{i + 1}.mp4"
    kf = bdir / f"sahne_{i + 1}_kontrol.json"
    if cikti.exists() and kf.exists():
        return json.loads(kf.read_text(encoding="utf-8"))
    karakter_mi = (ddir / "kadro" / f"{s['kart']}.png") if s["kart"] in {x["id"] for x in kitap_["karakterler"]} else None
    en_iyi = None
    for deneme in range(3):
        aday = bdir / f"sahne_{i + 1}_d{deneme + 1}.mp4"
        if not aday.exists():
            ltx25.uret(ddir / "kadro" / f"{s['kart']}.png", s["ltx"], aday, s["saniye"], AYAR["sahne_genislik"],
                       AYAR["sahne_yukseklik"], seed=no * 1000 + i * 10 + deneme)
        k = kontrol_et(aday, s, karakter_mi)
        k["deneme"] = deneme + 1
        log(f"  sahne {i + 1} deneme {deneme + 1}: süre {'✓' if k['sure'] else '✗'} dikey {'✓' if k['dikey'] else '✗'} "
            f"ses {'✓' if k['ses'] else '✗'} yüz {'✓' if k['yuz'] else 'şüpheli'} | duyulan: {k['duyulan'][:60]}")
        puan = (k["gecti"], k.get("ses_benzerlik", 1), k["yuz"])
        if en_iyi is None or puan > en_iyi[0]:
            en_iyi = (puan, aday, k)
        if k["gecti"] and k["yuz"]:
            break
    _, aday, k = en_iyi
    shutil.copy(aday, cikti)
    k["kabul"] = "geçti" if k["gecti"] else "en iyi deneme (kontrolü tam geçmedi)"
    kf.write_text(json.dumps(k, ensure_ascii=False, indent=2), encoding="utf-8")
    return k


def _buyuk(s: str) -> str:
    return s.replace("i", "İ").replace("ı", "I").upper()


def _ass_t(t: float) -> str:
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def altyazi(parcalar: list, toplam: float, baslik: str, cikti: Path):
    """parcalar: [(sahne_baslangici, kelimeler)] -> 3'er kelime, konuşulan kelime sarı + açılışta dizi adı, sonda 'devam edecek'."""
    sat = [f"Dialogue: 1,{_ass_t(0)},{_ass_t(2.6)},Baslik,,0,0,0,,{{\\fad(300,400)}}{baslik}",
           f"Dialogue: 1,{_ass_t(max(toplam - 2.2, 0))},{_ass_t(toplam)},Son,,0,0,0,,{{\\fad(300,0)}}DEVAM EDECEK..."]
    for bas, kel in parcalar:
        gruplar, g = [], []
        for w in kel:
            g.append(w)
            if len(g) == 3 or re.search(r"[.,!?;:]$", w[2]):
                gruplar.append(g)
                g = []
        if g:
            gruplar.append(g)
        for gi, g in enumerate(gruplar):
            gs = gruplar[gi + 1][0][0] if gi + 1 < len(gruplar) else g[-1][1] + 0.3
            for wi, (b, _e, _t) in enumerate(g):
                son = g[wi + 1][0] if wi + 1 < len(g) else gs
                metin = " ".join(("{\\c&H00E6FF&}" + _buyuk(t) + "{\\c&HFFFFFF&}") if j == wi else _buyuk(t)
                                 for j, (_b, _s, t) in enumerate(g))
                sat.append(f"Dialogue: 0,{_ass_t(bas + b)},{_ass_t(bas + son)},Alt,,0,0,0,,{metin}")
    cikti.write_text(
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 0\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
        "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding\n"
        "Style: Alt,Arial Black,78,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,6,3,2,70,70,520,1\n"
        "Style: Baslik,Georgia,88,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,1,0,0,0,100,100,2,0,1,4,4,8,60,60,260,1\n"
        "Style: Son,Georgia,70,&H00E6FF&,&H00FFFFFF,&H00000000,&H96000000,1,1,0,0,100,100,2,0,1,4,3,5,60,60,0,1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n" + "\n".join(sat) + "\n",
        encoding="utf-8")


def montaj(bdir: Path, sahneler: list, kontroller: list, baslik_ust: str) -> Path:
    final = bdir / "video.mp4"
    if final.exists():
        return final
    n = len(sahneler)
    parcalar, girdiler, t = [], [], 0.0
    for i in range(n):
        f = bdir / f"sahne_{i + 1}.mp4"
        # Whisper sessiz/ortam sesli sahnelerde "Altyazı M.K." gibi metin uyduruyor: sadece replikli sahnelere altyazı
        parcalar.append((t, kontroller[i]["kelimeler"] if sahneler[i].get("replik") else []))
        t += sure(f)
        girdiler += ["-i", f.name]
    altyazi(parcalar, t, baslik_ust, bdir / "altyazi.ass")
    v = "".join(f"[{i}:v]scale={W}:{H}:flags=lanczos,unsharp=5:5:0.6,fps={FPS},setsar=1,format=yuv420p[v{i}];"
                f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo[a{i}];" for i in range(n))
    v += "".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[vc][ac];[vc]subtitles=altyazi.ass[vo]"
    muzik = [p for p in (KOK / "muzik").glob("*") if p.suffix.lower() in (".mp3", ".m4a", ".wav")] if (KOK / "muzik").exists() else []
    if muzik:
        girdiler += ["-stream_loop", "-1", "-i", str(muzik[0])]
        v += (f";[{n}:a]volume=0.10,atrim=duration={t:.3f},afade=t=out:st={max(t - 2, 0):.3f}:d=2[m];"
              f"[ac][m]amix=inputs=2:duration=first:normalize=0[ao]")
    else:
        v += ";[ac]anull[ao]"
    calistir(["ffmpeg", "-y", "-v", "error", *girdiler, "-filter_complex", v, "-map", "[vo]", "-map", "[ao]",
              "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
              "-movflags", "+faststart", final.name], cwd=str(bdir))
    return final


def bolum(slug: str, no: int, onizle=True):
    ddir = DIZILER / slug
    bdir = ddir / f"bolum_{no}"
    bdir.mkdir(parents=True, exist_ok=True)
    k = json.loads((ddir / "kitap.json").read_text(encoding="utf-8"))
    durum_yaz(bdir, asama="senaryo yazılıyor", baslik="")
    s = senaryo(slug, no)
    durum_yaz(bdir, asama="kadro hazırlanıyor", baslik=s["baslik"])
    kadro(slug)
    comfy_baslat()
    n = len(s["sahneler"])
    kontroller = []
    for i, sh in enumerate(s["sahneler"]):
        durum_yaz(bdir, asama=f"sahneler {i}/{n}")
        log(f"sahne {i + 1}/{n} ({sh['kart']}, {sh['saniye']} sn): {sh['replik'] or '(sessiz)'}")
        kontroller.append(sahne_uret(slug, no, i, sh, k))
    durum_yaz(bdir, asama="montaj")
    video = montaj(bdir, s["sahneler"], kontroller,f"{_buyuk(k['ad'])}\\N{{\\fs56}}BÖLÜM {no}")
    rapor = [f"{i + 1}. {kk['kabul']} (deneme {kk['deneme']}, yüz {'✓' if kk['yuz'] else 'şüpheli'}) — {kk['duyulan'][:70]}"
             for i, kk in enumerate(kontroller)]
    (bdir / "kontrol_raporu.txt").write_text("\n".join(rapor), encoding="utf-8")
    durum_yaz(bdir, asama="önizleme bekliyor", sure=round(sure(video), 1),
              sorunlu_sahne=sum(1 for kk in kontroller if not kk["gecti"] or not kk["yuz"]))
    log(f"BÖLÜM HAZIR: {video} ({sure(video):.1f} sn)\n" + "\n".join(rapor))
    if onizle:
        os.startfile(str(video))
    return video


# ---------------------------------------------------------------- yayın (sadece kullanıcı onayından sonra)

def aciklama(s: dict, platform: str) -> str:
    linkler = (f"▶ Tüm bölümler YouTube'da: {AYAR['youtube_link']}\n📸 Instagram: {AYAR['instagram_link']}"
               if platform == "youtube" else
               f"▶ Tüm bölümler YouTube'da: {AYAR['youtube_link']}\n📸 Instagram: {AYAR['instagram_link']}")
    return f"{s['aciklama']}\n\n{linkler}\n\n{s.get('hashtagler', '')}\n\nBu dizi yapay zekâ ile üretilmiştir."


def yayinla(slug: str, no: int):
    bdir = DIZILER / slug / f"bolum_{no}"
    s = json.loads((bdir / "senaryo.json").read_text(encoding="utf-8"))
    video = bdir / "video.mp4"
    assert video.exists(), "önce bölümü üret"

    # 1) YouTube
    ytf = bdir / "youtube.json"
    if not ytf.exists():
        log("YouTube'a yükleniyor")
        meta = {"video": str(video), "title": s["baslik"][:100], "description": aciklama(s, "youtube"),
                "tags": [str(t)[:30] for t in s.get("etiketler", [])][:15], "privacy": AYAR.get("youtube_gizlilik", "public"),
                "category": "24", "language": "tr", "channel": AYAR["youtube_kanal"]}
        (bdir / "yt_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        env = dict(os.environ, YT_NONINTERACTIVE="1", PYTHONIOENCODING="utf-8", PYTHONWARNINGS="ignore")
        r = subprocess.run([str(YT_PY), str(YT_UPLOAD), str(bdir / "yt_meta.json")], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=env, cwd=str(YT_UPLOAD.parent), timeout=1800,
                           creationflags=NO_WINDOW)
        cikis = (r.stdout or "") + (r.stderr or "")
        m = re.search(r"yüklendi: (https://youtu\.be/\S+)", cikis)
        if not m:
            durum_yaz(bdir, asama="YouTube yüklemesi başarısız")
            raise RuntimeError("YouTube yüklemesi başarısız" + (" — YouTube Bagla ile yeniden onay gerekli"
                                                                  if "YETKI_GEREKLI" in cikis or "invalid_grant" in cikis else "")
                               + ":\n" + cikis[-600:])
        ytf.write_text(json.dumps({"link": m.group(1)}), encoding="utf-8")
    yt_link = json.loads(ytf.read_text(encoding="utf-8"))["link"]
    durum_yaz(bdir, asama="YouTube'da yayında, Instagram bekliyor", youtube=yt_link)
    log(f"YouTube: {yt_link}")

    # 2) Instagram Reels
    igf = bdir / "instagram.json"
    if not igf.exists():
        log("Instagram'a yükleniyor")
        sys.path.insert(0, str(IG_DIR))
        import yayinla as ig
        mid = ig.post_video(str(video), aciklama(s, "instagram"), dry_run=False)
        link = None
        try:
            link = json.load(urllib.request.urlopen(
                f"https://graph.facebook.com/v21.0/{mid}?fields=permalink&access_token={ig.ACCESS_TOKEN}", timeout=30))["permalink"]
        except Exception:
            pass
        igf.write_text(json.dumps({"media_id": mid, "link": link}), encoding="utf-8")
    ig_link = json.loads(igf.read_text(encoding="utf-8")).get("link") or "yüklendi"
    durum_yaz(bdir, asama="yayında", instagram=ig_link)
    log(f"Instagram: {ig_link}")


# ---------------------------------------------------------------- fabrika: senaryo -> 5 bölüm -> onay/yayın -> yeni senaryo

FABRIKA = DIZILER / "fabrika.json"
TG_AYAR = Path(r"C:\Users\MSI\Desktop\YAPAY ZEKA PROJELER\Telegram-Video-Otomasyon\ayarlar.json")

FIKIR_PROMPT = """Kısa dikey Türkçe AI dizileri yapan bir kanal için YENİ bir dizi fikri bul. Her dizi 5 bölüm, her bölüm ~3 dakika.
Daha önce yapılan diziler (bunlardan TÜR, MEKÂN ve DUYGU olarak belirgin şekilde farklı olsun):
{onceki}

KURALLAR
- Türkiye'de geçen, gerçekçi, merak uyandıran, 3-4 karakterli, 2-4 mekânlı bir hikâye (yapay zekâ videosu için:
  kalabalık sahne, aksiyon, dövüş, araç kovalamaca YOK; konuşma ve atmosfer ağırlıklı).
- Türler arasında dönüşümlü düşün: gizem, gerilim, aile dramı, romantik, kara mizah, doğaüstü, dönem hikâyesi.
- "fikir": tek Türkçe cümle. "slug": küçük harf, Türkçe karaktersiz, tireli (örn. "ucuncu-kat-yedi-numara").

ÇIKTI: SADECE {{"slug": "...", "fikir": "..."}}
"""


def bolum_sayisi(slug: str) -> int:
    k = json.loads((DIZILER / slug / "kitap.json").read_text(encoding="utf-8"))
    return len(k["bolumler"])


def biten_bolumler(slug: str) -> list:
    return [n for n in range(1, bolum_sayisi(slug) + 1) if (DIZILER / slug / f"bolum_{n}" / "video.mp4").exists()]


def telegram(metin: str):
    try:
        a = json.loads(TG_AYAR.read_text(encoding="utf-8"))
        data = urllib.parse.urlencode({"chat_id": a["izinli_chat_id"], "text": metin[:4000]}).encode()
        urllib.request.urlopen(f"https://api.telegram.org/bot{a['telegram_token']}/sendMessage", data=data, timeout=30)
    except Exception as e:
        log(f"telegram gönderilemedi: {e}")


def fabrika_oku() -> dict:
    return json.loads(FABRIKA.read_text(encoding="utf-8")) if FABRIKA.exists() else {"sira": [], "bildirilen": []}


def fabrika_yaz(f: dict):
    FABRIKA.write_text(json.dumps(f, ensure_ascii=False, indent=2), encoding="utf-8")


def yeni_dizi(f: dict) -> str:
    onceki = []
    for s in f["sira"]:
        try:
            k = json.loads((DIZILER / s / "kitap.json").read_text(encoding="utf-8"))
            onceki.append(f"- {k['ad']}: {k['logline']} (ton: {k['ton']})")
        except Exception:
            pass

    def kontrol(d):
        assert d["fikir"] and re.fullmatch(r"[a-z0-9-]{3,60}", d["slug"]) and not (DIZILER / d["slug"]).exists()

    d = claude_json(FIKIR_PROMPT.format(onceki="\n".join(onceki) or "(henüz yok)"), kontrol)
    log(f"YENİ DİZİ: {d['slug']} — {d['fikir']}")
    kitap(d["slug"], d["fikir"])
    f["sira"].append(d["slug"])
    fabrika_yaz(f)
    k = json.loads((DIZILER / d["slug"] / "kitap.json").read_text(encoding="utf-8"))
    telegram(f"🎬 Yeni dizi başladı: {k['ad']}\n{k['logline']}\n\nBölümler: " +
             " · ".join(f"{b['no']}. {b['baslik']}" for b in k["bolumler"]))
    return d["slug"]


def fabrika():
    """Sonsuz döngü: aktif dizinin eksik bölümünü üret; 5'i bitince bildir (yayın onay bekler), yeni diziye geç.
    Durdurmak için diziler/DURDUR dosyası oluştur."""
    try:  # fabrika çalıştığı sürece Windows uykuya/modern beklemeye geçmesin (süreç kapanınca kendiliğinden kalkar)
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001 | 0x00000040)  # CONTINUOUS|SYSTEM|AWAYMODE
    except Exception:
        pass
    hatalar = {}
    while not (DIZILER / "DURDUR").exists():
        f = fabrika_oku()
        aktif = f["sira"][-1] if f["sira"] else None
        if aktif is None or len(biten_bolumler(aktif)) == bolum_sayisi(aktif):
            if aktif and aktif not in f["bildirilen"]:
                k = json.loads((DIZILER / aktif / "kitap.json").read_text(encoding="utf-8"))
                for n in biten_bolumler(aktif):
                    durum_yaz(DIZILER / aktif / f"bolum_{n}", asama="yayın onayı bekliyor (5 bölüm tamam)")
                telegram(f"✅ {k['ad']} — {bolum_sayisi(aktif)} bölümün hepsi hazır!\nYayın onayını bekliyor: "
                         f"önizleyip onay verince önce YouTube, sonra Instagram'a sırayla yüklenecek.\n"
                         f"Klasör: {DIZILER / aktif}")
                f["bildirilen"].append(aktif)
                fabrika_yaz(f)
            yeni_dizi(f)
            continue
        no = next(n for n in range(1, bolum_sayisi(aktif) + 1) if n not in biten_bolumler(aktif))
        try:
            bolum(aktif, no, onizle=False)
            hatalar.pop((aktif, no), None)
        except Exception as e:
            hatalar[(aktif, no)] = hatalar.get((aktif, no), 0) + 1
            log(f"HATA {aktif} bölüm {no} ({hatalar[(aktif, no)]}. kez): {e}")
            durum_yaz(DIZILER / aktif / f"bolum_{no}", asama=f"hata, yeniden denenecek: {str(e)[:120]}")
            if hatalar[(aktif, no)] >= 3:
                telegram(f"⚠️ Dizi fabrikası durdu: {aktif} bölüm {no} 3 kez hata verdi.\n{str(e)[:500]}")
                return
            time.sleep(300)
    log("DURDUR dosyası bulundu, fabrika durdu")


def yayinla_hepsi(slug: str):
    """Kullanıcı onayından sonra: bölümleri sırayla, her biri önce YouTube sonra Instagram."""
    for n in biten_bolumler(slug):
        yayinla(slug, n)
    f = fabrika_oku()
    f.setdefault("yayinlanan", []).append(slug)
    fabrika_yaz(f)
    telegram(f"📺 {slug}: {len(biten_bolumler(slug))} bölüm YouTube + Instagram'da yayında.")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    a = sys.argv[1:]
    if not a:
        print(__doc__)
    elif a[0] == "kitap":
        kitap(a[1], a[2])
    elif a[0] == "kadro":
        kadro(a[1])
    elif a[0] == "bolum":
        bolum(a[1], int(a[2]), onizle="--onizleme-yok" not in a)
    elif a[0] == "yayinla":
        yayinla(a[1], int(a[2]))
    elif a[0] == "yayinla_hepsi":
        yayinla_hepsi(a[1])
    elif a[0] == "fabrika":
        fabrika()
