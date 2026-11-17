# AI Dizi FabrikasÄ±

Tek cÃ¼mlelik bir fikirden **yapay zekayla dizi Ã¼reten** hat: dizi kitabÄ± â†’ karakter/mekÃ¢n kartlarÄ± â†’ bÃ¶lÃ¼m (sesli sahneler) â†’ Ã¶nizleme â†’ YouTube + Instagram'a yayÄ±n.

## Komutlar
```bash
python dizi.py kitap <slug> "<tek cÃ¼mlelik fikir>"   # dizi kitabÄ±: karakterler, mekÃ¢nlar, 5 bÃ¶lÃ¼m akÄ±ÅŸÄ±
python dizi.py kadro <slug>                          # karakter + mekÃ¢n kartlarÄ±nÄ± Ã§izer
python dizi.py bolum <slug> <no>                     # bÃ¶lÃ¼mÃ¼ Ã¼retir, kontrol eder, montajlar
python dizi.py yayinla <slug> <no>                   # onaydan sonra yayÄ±nlar
python dizi.py fabrika                               # sÃ¼rekli Ã¼retim modu
```

## YapÄ±
- `dizi.py`: ana komut satÄ±rÄ± ve iÅŸ akÄ±ÅŸÄ±
- `ltx25.py`: LTX video modeli sarmalayÄ±cÄ±sÄ± (ComfyUI)
- `kanal_durum.py`, `profil_guncelle.py`: kanal takibi ve profil gÃ¼ncelleme
- `ayarlar.example.json`: ayar ÅŸablonu (anahtarlar boÅŸ)

Yerel olarak ComfyUI + video/ses modelleriyle Ã§alÄ±ÅŸacak ÅŸekilde tasarlandÄ±. Onay adÄ±mÄ± vardÄ±r: yayÄ±n otomatik deÄŸil, Ã¶nizlemeden sonradÄ±r.

**Teknolojiler:** Python Â· ComfyUI Â· LTX-Video Â· ffmpeg Â· YouTube/Instagram API