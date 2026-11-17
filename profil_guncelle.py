"""YouTube kanal açıklamasına Instagram linkini yazar (ayarlar.json'daki "kanal_aciklamasi").

Instagram kullanıcı adı değişince: ayarlar.json'da instagram_link'i düzelt, bunu yeniden çalıştır.
Instagram biyografisine link API ile yazılamıyor; onu kullanıcı uygulamadan ekler.
OpenMontage .venv python'u ile çalıştırılır.
"""
import json
from pathlib import Path

import truststore

truststore.inject_into_ssl()
from google.oauth2.credentials import Credentials  # noqa: E402
from googleapiclient.discovery import build  # noqa: E402

KOK = Path(__file__).resolve().parent
AYAR = json.loads((KOK / "ayarlar.json").read_text(encoding="utf-8"))
TOKEN = Path(r"C:\Users\MSI\Desktop\YAPAY ZEKA PROJELER\OpenMontage\youtube") / f"token_{AYAR['youtube_kanal']}.json"

yt = build("youtube", "v3", credentials=Credentials.from_authorized_user_file(str(TOKEN)), cache_discovery=False)
ch = yt.channels().list(part="brandingSettings", mine=True).execute()["items"][0]
b = ch["brandingSettings"]
b.setdefault("channel", {})["description"] = AYAR["kanal_aciklamasi"].format(**AYAR)
yt.channels().update(part="brandingSettings", body={"id": ch["id"], "brandingSettings": b}).execute()
print("Kanal açıklaması güncellendi:\n" + b["channel"]["description"])
