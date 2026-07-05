# Mimari Degerlendirme Gorevi -- Software Architect Agent Spec

**Tarih:** 2026-07-05
**Talep eden:** Urun Yoneticisi (PM)
**Hedef agent:** Software Architect
**Cikti dosyasi:** `/Users/erdemerdolu/Desktop/kube-sec/mimari-degerlendirme.md`
**Cikti dili:** Turkce

---

## 1. Problem Tanimi

Kube-Sec, Kubernetes guvenlik/operasyon dashboard'u olarak gelistirilen bir uygulamadir. Kullaniciya sunulan deger onerisinin merkezinde "masaustu uygulamasi olarak dagitilabilme" yer almaktadir. Mevcut mimari (Flask + Jinja2 SSR + PyInstaller ile paketleme + webbrowser.open ile tarayici sekmesi acma) bu hedefe ne olcude hizmet ediyor, ne olcude engelliyor -- bunu somut kanitlarla ortaya koyan ve gerekceleri tek bir tavsiye ile sonuclanan bir mimari degerlendirme raporu uretilmelidir.

Kullanici ayrica "Next.js'e replace edebiliriz" diyerek modern frontend teknolojilerine gecis olasiligin acikca masaya koymustur. Repo kokunde halihazirda baglantisiz bir Next.js/shadcn iskeleti (v0.app taslagi) de mevcuttur; bu iskelinin yeniden kullanilabirligi de degerlendirilmelidir.

---

## 2. Analiz Kapsamindaki Dosyalar ve Dizinler

Asagidaki dosya/dizinlerin HER BIRI okunmali ve ilgili bolumlerinde somut referanslar (dosya adi, satir numarasi veya satir araligi) verilmelidir:

| # | Dosya / Dizin | Analiz Amaci |
|---|---|---|
| 1 | `src/web/app.py` (~5.474 satir, 119 route) | Monolitik yapi; route sayisi, is mantigi yogunlugu, frontend/backend ayristirma potansiyeli |
| 2 | `src/web/templates/*.html` (22 sablon) | Jinja2 SSR karmasikligi, istemci tarafi JS miktari, React'a donusum eforu |
| 3 | `src/web/static/` (pod_describe.js, logo.svg) | Statik varlik durumu |
| 4 | `launcher.py` | Masaustu baslatma mekanizmasi (webbrowser.open, port bulma, frozen kontrolu) |
| 5 | `Kube-Sec.spec` | PyInstaller paketleme yapilandirmasi (datas, hiddenimports, bundle_identifier) |
| 6 | `Makefile` | Build/release sureci (sign, notarize, dmg hedefleri) |
| 7 | `requirements.txt` | Python bagimliliklari ve versiyonlari |
| 8 | `src/main.py` | Normal calistirma entrypoint'i |
| 9 | `src/scanner/k8s_scanner.py`, `src/reports/report_generator.py` | Yardimci siniflar -- backend yeniden kullanimda rolleri |
| 10 | `src/version.py`, `VERSION` | Versiyon yonetimi |
| 11 | `package.json`, `app/layout.tsx`, `app/page.tsx`, `components/ui/*.tsx` | Mevcut Next.js/shadcn iskeleti -- kullanilabirligi |
| 12 | `Dockerfile` (varsa) | Konteyner build sureci |

**Kapsam DISI -- bu dosya/dizinler analiz edilmeyecek:**

- `Dias/` dizini (ilgisiz, farkli proje)
- `k8s-security-checker/`, `kube-sec/kube-sec/` (eski/stale parcalar)
- `.venv/`, `node_modules/`, `.git/`
- `kubeconfigs/` icerigi (hassas veri, icerigi okunmamali; sadece mekanizmanin varligi not edilmeli)

---

## 3. Degerlendirme Kriterleri

Raporda her bir kriter icin mevcut durumun somut olarak betimlenmesi ve 1-5 arasi bir olgunluk/yeterlilik puani verilmesi ZORUNLUDUR. Puan aciklamalari:

- **1:** Tamamen yetersiz, ciddi sorunlar var
- **2:** Buyuk eksiklikler var, onemli iyilestirme gerekli
- **3:** Temel islevsellik var ama onemli kisitlamalar mevcut
- **4:** Iyi, kucuk iyilestirmelerle yeterli
- **5:** Mukemmel, masaustu deneyimi hedefine tam uyumlu

### 3.1 Baslatma ve Pencere Deneyimi (UX)

- Uygulama baslatildiginda kullanicinin gordugu sey nedir? (native pencere mi, tarayici sekmesi mi?)
- `launcher.py` satir 38-46'daki `webbrowser.open` mekanizmasinin kullanici deneyimi uzerindeki etkisi
- Tarayici sekmesinin kapatilmasi durumunda Flask sunucusunun akibeti
- macOS Dock'ta ve Windows gorev cubugunda uygulamanin temsili (ikon, pencere basligi, Dock'tan geri acma)
- Birden fazla Kube-Sec orneginin ayni anda acilma durumu ve port cakismasi riski (`launcher.py` satir 24-34)

### 3.2 Paketleme, Dagitim ve Kurulum

- PyInstaller bundle boyutu (tahmini -- `Kube-Sec.spec` `datas` listesindeki icerikler uzerinden)
- PyInstaller'in bilinen kisitlamalari: antivirusten false positive, macOS Gatekeeper sorunlari, Windows SmartScreen
- `Kube-Sec.spec` satir 46-51'deki `BUNDLE` yapilandirmasi: `bundle_identifier='com.example.kubesec'` -- uretim icin uygunlugu
- Code signing ve notarization sureci (`Makefile` satir 92-113): mevcut otomasyon yeterliligi
- Otomatik guncelleme mekanizmasi var mi? Yoksa bu eksikligin masaustu uygulama deneyimine etkisi
- Windows build sureci (`build-windows.sh`/`build-windows.ps1` -- varsa icerik analizi)

### 3.3 Native OS Entegrasyonu

- Sistem tepsisi (tray icon) destegi var mi?
- OS bildirimleri (notifications) destegi var mi?
- Dosya sistemi entegrasyonu (drag & drop, dosya secici) -- mevcut template'lerde kullaniyor mu?
- Derin baglanti (deep linking / URL scheme) destegi
- Sistem karanlik/aydinlik tema uyumu

### 3.4 Cevrimdisi (Offline) Calisma ve Performans

- Uygulamanin internet baglantisi olmadan baslatilip baslatilabilecegi (CDN'den yuklenen JS/CSS var mi? Template'lerdeki disaridan cekilenler)
- Flask dev sunucusunun (uretim WSGI sunucusu degil) performans etkileri (`src/main.py` ve `launcher.py`'de `app.run()` kullanimi)
- Arka plan thread'lerinin (workload stats cache, pods summary cache, metrics sampler) kaynak tuketimi
- Bellek kullanimi profili: Python + Flask + kubernetes client'in masaustu ortamda makul olup olmadigi

### 3.5 Kod Mimarisi ve Surdurulebilirlik

- `src/web/app.py`'nin ~5.474 satirlik monolitik yapisinin bakim maliyeti
- 119 route'un tek dosyada olmasi: yeni ozellik ekleme hizi, hata izolasyonu, test edilebilirlik
- Frontend (Jinja2 SSR + inline JS) ile backend (Flask route handler'lari) arasindaki sikistirmanin ayristirma potansiyeli
- Blueprint/modular yapi kullanilmamis olmasi
- Test altyapisinin yoklugu (pytest bagimliligi var ama sifir test)
- i18n mekanizmasinin (`I18N` dict) olceklenebilirligi

### 3.6 Gelistirme Deneyimi (DX)

- Hot reload / HMR destegi (Flask debug modu var ama frontend icin?)
- Linting, formatting, type checking araclarinin yoklugu
- CI/CD pipeline yoklugu
- Repo kokunde iki farkli proje iskeletinin (Python Flask + Next.js) bir arada bulunmasinin yarattigi karisiklik

---

## 4. Karsilastirma Gereksinimleri

Asagidaki EN AZ 4 alternatif mimari secenegin HER BIRI icin belirtilen alt basliklar doldurularak bir karsilastirma tablosu olusturulmalidir.

### Secenek A: Mevcut Mimaride Kalma + Iyilestirmeler
Flask + Jinja2 + PyInstaller'da kalip sorunlari hafifletme (ornegin pywebview ile native pencere, blueprint refactor, otomatik guncelleme ekleme).

### Secenek B: Flask API Backend + Next.js/React Frontend + Electron Shell
Mevcut Flask backend'i saf JSON API'ye donusturme, Jinja2 template'lerini Next.js/React ile yeniden yazma, Electron ile native pencere saglama.

### Secenek C: Flask API Backend + Next.js/React Frontend + Tauri Shell
Secenek B ile ayni ama Electron yerine Tauri (Rust-tabanli, daha kucuk bundle) kullanma.

### Secenek D: Tam Electron + Node.js Yeniden Yazim
Flask backend'i tamamen birakip kubernetes client'i Node.js'e (ornegin @kubernetes/client-node) tasima, tum uygulamayi Electron + React olarak sifirdan yazma.

**Her secenek icin su alt basliklar ZORUNLU doldurulacak:**

| Alt baslik | Aciklama |
|---|---|
| **Gelistirme eforu** | Adam-hafta cinsinden kabaca tahmin (mevcut 119 route ve 22 sablon baz alinarak) |
| **Mevcut kodun yeniden kullanim orani** | `src/web/app.py`'deki 119 route handler'in yuzde kaci korunabilir/adapte edilebilir? |
| **Masaustu UX kazanimi** | Secenek A'ya gore somut olarak ne kazanilir? (native pencere, tray, bildirim, deep link vb.) |
| **Paket boyutu tahmini** | MB cinsinden kabaca (Python runtime + Flask vs. Chromium + Node.js vs. Tauri WebView) |
| **Otomatik guncelleme** | Mekanizma kolayligi (electron-updater vs. ozel cozum vs. Tauri updater) |
| **Cross-platform** | macOS + Windows + (opsiyonel Linux) destegi kolayligi |
| **Bilinen riskler** | En az 2 somut risk (teknik, takvim, yetenek vb.) |
| **Arti yonler** | En az 3 somut arti |
| **Eksi yonler** | En az 3 somut eksi |
| **Repo kokundeki Next.js iskeletinin kullanilabilme durumu** | `package.json`, `app/`, `components/ui/` icerigi dogrudan kullanilabilir mi, yoksa sifirdan mi baslamak gerekir? |

---

## 5. Tavsiye Zorunlulugu

Rapor, muglak "duruma gore degisir", "takimin tercihine bagli" gibi ifadelerle bitmemeli. Tek ve NET bir tavsiye icermeli:

- "Mevcut mimaride (Flask + PyInstaller) KALINMALI, su iyilestirmeler YAPILMALI: [madde listesi]"

VEYA

- "Su alternatif mimariye GECILMELI: [secenek adi], cunku [gerekce listesi]"

Tavsiye, su kriterlere gore gerekcelendirilmeli:
1. Kullanicinin birebir "masaustu uygulamasi" beklentisine en iyi hangi secenek cevap veriyor?
2. Mevcut gelistirici kaynaklariyla (tek/kucuk takim varsayimi) hangi secenek makul surede tamamlanabilir?
3. Uzun vadeli bakim maliyeti hangi secenekte en dusuk?

---

## 6. Asama Plani Gereksinimleri

Eger tavsiye mevcut mimaride kalmak DEGILSE, asagidaki formatta asama asama bir gecis plani sunulmalidir. Her asama icin:

| Alan | Aciklama |
|---|---|
| Asama adi | Kisa, tanimlayici |
| Kapsam | Bu asamada ne yapiliyor (hangi route'lar, hangi ekranlar, hangi altyapi) |
| Tamamlanma kriteri | Olculebilir ve test edilebilir bir kosula baglanmis (ornegin "mevcut 22 sablonun 22'si de React'a tasinmis ve ayni islevsellikle calisir hale gelmis olmali") |
| Tahmini sure | Adam-hafta |
| Bagimliliklari | Onceki hangi asamanin tamamlanmasi gerekiyor |
| Geri donus noktasi | Bu asama basarisiz olursa onceki duruma nasil donulur |

Asama sayisi 3 ile 7 arasinda olmali. Ilk asama "paralel calisma" yapisindan baslamamali -- yani mevcut Flask uygulamasi calismaya devam ederken yeni altyapinin yapilandirilmasini kapsamali (big-bang degil, incremental migration).

---

## 7. Cikti Formati ve Konum

Rapor `/Users/erdemerdolu/Desktop/kube-sec/mimari-degerlendirme.md` dosyasina TURKCE olarak yazilmali.

Raporun ZORUNLU bolumleri:

1. **Yonetici Ozeti** -- Tek paragraf, net tavsiye, teknik detaysiz, karar vericinin okuyup anlamasi icin yeterli
2. **Mevcut Mimari Analizi** -- Bolum 3'teki her kriter icin somut dosya/satir referanslariyla degerlendirme ve puan tablosu
3. **Degerlendirme Kriterleri Ozet Tablosu** -- 6 kriter, her biri 1-5 puan, tek tablo
4. **Alternatif Karsilastirmasi** -- Bolum 4'teki 4 secenek, tablo formatinda
5. **Tavsiye ve Gerekce** -- Bolum 5 gereksinimlerine uygun
6. **Gecis Plani** (eger migrasyon tavsiye ediliyorsa) -- Bolum 6 formatinda

---

## 8. Kalite Gereksinimleri (Kabul Kriterleri)

Rapor, asagidaki TUMU karsilanmadigi surece kabul EDILMEZ:

### Kritik Gereksinimler

- [ ] **KR-01:** Bolum 2'deki 12 dosya/dizin kaynaginin hepsi okunmus ve raporda en az bir kez somut referansla (dosya adi + satir numarasi) atifta bulunulmus olmali.
- [ ] **KR-02:** Bolum 3'teki 6 degerlendirme kriterinin her biri icin 1-5 arasi puan verilmis ve her puan en az bir somut kod/dosya referansiyla desteklenmis olmali.
- [ ] **KR-03:** Bolum 4'teki 4 alternatif secenegin her biri icin tablodaki 10 alt basligin hepsi doldurulmus olmali.
- [ ] **KR-04:** Rapor, muglak olmayan TEK bir tavsiye ile bitmeli; "duruma gore degisir" / "takim tercihine bagli" gibi ifadeler YASAK.
- [ ] **KR-05:** Her "X sorununa yol acar" veya "Y avantaji saglar" iddiasi, ya somut bir dosya/satir referansiyla ya da dogrulanabilir bir dis kaynakla desteklenmis olmali.
- [ ] **KR-06:** Rapor `/Users/erdemerdolu/Desktop/kube-sec/mimari-degerlendirme.md` konumuna Turkce olarak yazilmis olmali.

### Orta Gereksinimler

- [ ] **OR-01:** Repo kokundeki Next.js iskeletinin (`package.json`, `app/`, `components/`) mevcut durumu ve secilen alternatifle iliskisi acikca degerlendirilmis olmali (yeniden kullanilabilir mi, silinmeli mi, temel alinabilir mi).
- [ ] **OR-02:** Eger migrasyon tavsiye ediliyorsa, gecis plani 3-7 asama icermeli ve her asama icin tamamlanma kriteri olculebilir olmali.
- [ ] **OR-03:** `launcher.py`'deki `webbrowser.open` mekanizmasi ve `Kube-Sec.spec`'deki `bundle_identifier='com.example.kubesec'` gibi uretim-oncesi/placeholder degerlerin tespit edilmis ve raporlanmis olmali.
- [ ] **OR-04:** Kubeconfig yonetim mekanizmasinin (session-based + global fallback, `src/web/app.py` satir 229-384 civari) secilen mimaride nasil ele alinacagi degerlendirilmis olmali.

### Nice-to-have

- [ ] **NH-01:** Her alternatif secenek icin bir "minimum viable product" (MVP) tanimi yapilmis olabilir (tam migrasyon oncesi hangi alt kume yeterli).
- [ ] **NH-02:** Mevcut i18n mekanizmasinin (`I18N` dict, `translate()`, `inject_i18n`) secilen mimarideki karsiligi oneriliyor olabilir.
- [ ] **NH-03:** Mevcut background thread mekanizmalarinin (cache refresher, metrics sampler) secilen mimarideki karsiligi icin bir pattern onerilmis olabilir.

---

## 9. Kisitlar

- Architect agent KOD DEGISIKLIGI YAPMAMALI, sadece analiz ve rapor uretmeli.
- `kubeconfigs/` dizininin icerigi okunmamali (hassas veri).
- `Dias/` dizini projeye ait degildir, yok sayilmali.
- Raporda hicbir durumda `kubeconfigs/` altindaki dosya icerikleri yazdirmamali.
