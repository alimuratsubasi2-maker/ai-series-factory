"""Kanal durumu (sadece okuma): NovadijitalTR YouTube + Instagram (@hisar_tasarim_) son videoları ve istatistikleri.

Çıktı: durum.txt (sesle okunacak Türkçe özet) + durum.json. JARVIS bunu okuyarak "kanallarım ne durumda" sorusunu cevaplar.
Hiçbir şey yüklemez, silmez, değiştirmez. OpenMontage .venv python'u ile çalıştırılır (google kütüphaneleri orada).
"""
import datetime as dt
import json
import sys
import urllib.request
from pathlib import Path

try:  # Avast HTTPS'e kendi sertifikasını sokuyor; Windows sertifika deposunu kullan
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

KOK = Path(__file__).resolve().parent
YT_DIR = Path(r"C:\Users\MSI\Desktop\YAPAY ZEKA PROJELER\OpenMontage\youtube")
IG_ENV = Path(r"C:\Users\MSI\Desktop\ETSY MAGAZASI İÇİN ÜRÜNLER\instagram-otomasyon\.env")
SON_N = 10


def _tarih(s: str) -> str:
    try:
        t = dt.datetime.fromisoformat(s.replace("Z", "+00:00").replace("+0000", "+00:00")).astimezone()
        return t.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return s


def youtube() -> dict:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    tok = YT_DIR / "token_novadijital.json"
    creds = Credentials.from_authorized_user_file(str(tok))
    if not creds.valid:
        try:
            creds.refresh(Request())
            tok.write_text(creds.to_json(), encoding="utf-8")
        except Exception as e:
            if "invalid_grant" in str(e):
                return {"hata": "YouTube bağlantısının süresi dolmuş; 'YouTube Bagla' ile yeniden onay gerekiyor.",
                        "detay": str(e)[:200]}
            return {"hata": "YouTube'a şu an bağlanılamadı (internet/sertifika sorunu).", "detay": str(e)[:200]}
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    ch = yt.channels().list(part="snippet,statistics,contentDetails", mine=True).execute()["items"][0]
    yuklemeler = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    ids = [i["contentDetails"]["videoId"] for i in
           yt.playlistItems().list(part="contentDetails", playlistId=yuklemeler, maxResults=SON_N).execute().get("items", [])]
    videolar = []
    if ids:
        for v in yt.videos().list(part="snippet,statistics,status", id=",".join(ids)).execute().get("items", []):
            st = v.get("statistics", {})
            videolar.append({"baslik": v["snippet"]["title"], "tarih": _tarih(v["snippet"]["publishedAt"]),
                             "durum": v["status"].get("privacyStatus"), "islem": v["status"].get("uploadStatus"),
                             "izlenme": int(st.get("viewCount", 0)), "begeni": int(st.get("likeCount", 0)),
                             "yorum": int(st.get("commentCount", 0)), "link": f"https://youtu.be/{v['id']}"})
    s = ch["statistics"]
    return {"kanal": ch["snippet"]["title"], "abone": int(s.get("subscriberCount", 0)),
            "toplam_izlenme": int(s.get("viewCount", 0)), "video_sayisi": int(s.get("videoCount", 0)), "videolar": videolar}


def _graph(yol: str, tok: str) -> dict:
    ayrac = "&" if "?" in yol else "?"
    return json.load(urllib.request.urlopen(f"https://graph.facebook.com/v21.0/{yol}{ayrac}access_token={tok}", timeout=30))


def instagram() -> dict:
    env = dict(l.strip().split("=", 1) for l in IG_ENV.read_text(encoding="utf-8").splitlines()
               if "=" in l and not l.startswith("#"))
    tok, ig = env["IG_PAGE_ACCESS_TOKEN"], env["IG_BUSINESS_ACCOUNT_ID"]
    try:
        hesap = _graph(f"{ig}?fields=username,followers_count,media_count", tok)
        medya = _graph(f"{ig}/media?fields=caption,media_type,media_product_type,timestamp,like_count,comments_count,permalink"
                       f"&limit={SON_N}", tok).get("data", [])
    except urllib.error.HTTPError as e:
        return {"hata": "Instagram bağlantısı çalışmıyor (erişim anahtarı yenilenmeli olabilir).",
                "detay": e.read().decode("utf-8", "replace")[:200]}
    gonderiler = []
    for m in medya:
        g = {"tur": "Reels" if m.get("media_product_type") == "REELS" else m.get("media_type", "").lower(),
             "aciklama": (m.get("caption") or "").split("\n")[0][:70], "tarih": _tarih(m.get("timestamp", "")),
             "begeni": m.get("like_count", 0), "yorum": m.get("comments_count", 0), "link": m.get("permalink")}
        if g["tur"] == "Reels":
            try:
                g["izlenme"] = _graph(f"{m['id']}/insights?metric=views", tok)["data"][0]["values"][0]["value"]
            except Exception:
                pass
        gonderiler.append(g)
    return {"hesap": hesap.get("username"), "takipci": hesap.get("followers_count", 0),
            "gonderi_sayisi": hesap.get("media_count", 0), "gonderiler": gonderiler}


def uretim() -> dict:
    """Dizi üretim hattının bıraktığı bölüm kayıtları (diziler/<dizi>/bolum_*/durum.json).

    Kayıt şeması: {"baslik", "asama": "senaryo|kadro|sahneler 3/7|montaj|önizleme bekliyor|onaylandı|yayında",
                   "youtube": null|"https://youtu.be/..", "instagram": null|"https://instagram.com/..", "guncelleme"}
    """
    bolumler = []
    for f in sorted(KOK.glob("diziler/*/bolum_*/durum.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            bolumler.append({"dizi": f.parent.parent.name, "bolum": f.parent.name, **d})
        except Exception:
            pass
    return {"bolumler": bolumler}


def ozet(d: dict) -> str:
    sat = [f"Kanal durumu, {d['zaman']} itibarıyla."]
    y = d["youtube"]
    if "hata" in y:
        sat.append("YouTube: " + y["hata"])
    else:
        sat.append(f"YouTube {y['kanal']}: {y['abone']} abone, toplam {y['toplam_izlenme']} izlenme, {y['video_sayisi']} video.")
        for v in y["videolar"][:5]:
            durum = {"public": "yayında", "private": "gizli", "unlisted": "liste dışı"}.get(v["durum"], v["durum"])
            if v["islem"] not in ("processed", "uploaded"):
                durum += f", işleme durumu {v['islem']}"
            sat.append(f"  - {v['baslik']} ({v['tarih']}, {durum}): {v['izlenme']} izlenme, {v['begeni']} beğeni, {v['yorum']} yorum.")
    i = d["instagram"]
    if "hata" in i:
        sat.append("Instagram: " + i["hata"])
    else:
        sat.append(f"Instagram @{i['hesap']}: {i['takipci']} takipçi, {i['gonderi_sayisi']} gönderi.")
        for g in i["gonderiler"][:5]:
            izl = f"{g['izlenme']} izlenme, " if "izlenme" in g else ""
            sat.append(f"  - {g['tur']} {g['tarih']} \"{g['aciklama']}\": {izl}{g['begeni']} beğeni, {g['yorum']} yorum.")
    b = d["uretim"]["bolumler"]
    if b:
        sat.append(f"Dizi üretimi: {len(b)} bölüm kaydı var.")
        for x in b[-5:]:
            yuk = ", ".join(f"{p} {x.get(p) or 'yüklenmedi'}" for p in ("youtube", "instagram"))
            sat.append(f"  - {x['dizi']} {x['bolum']} ({x.get('baslik', '')}): {x.get('asama', 'bilinmiyor')}; {yuk}"
                       f" (son güncelleme {x.get('guncelleme', '?')}).")
    else:
        sat.append("Dizi üretimi: henüz üretilmiş bölüm yok.")
    return "\n".join(sat)


def main():
    d = {"zaman": dt.datetime.now().strftime("%d.%m.%Y %H:%M")}
    for ad, f in (("youtube", youtube), ("instagram", instagram), ("uretim", uretim)):
        try:
            d[ad] = f()
        except Exception as e:
            d[ad] = {"hata": f"{ad} okunamadı: {e}"[:300]} if ad != "uretim" else {"bolumler": []}
    (KOK / "durum.json").write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    metin = ozet(d)
    (KOK / "durum.txt").write_text(metin, encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(metin)


if __name__ == "__main__":
    main()
