# Kube-Sec Backlog (v2)

> **Onceki backlog (v1) durumu:** 17 madde, 57 kabul kriteri — TAMAMI tamamlandi ve dogrulandi (2026-07-05 – 2026-07-20).
> **Bu backlog olusturulma tarihi:** 2026-07-21
> **Analiz kapsami:** 19 sablon dosyasi (`src/web/templates/*.html`), 15 blueprint modulu (`src/web/blueprints/**/*.py`), 7 altyapi modulu (`src/web/`), `src/scanner/k8s_scanner.py`, CI/CD dosyalari (`.github/workflows/`), `Dockerfile`, `Makefile`, `requirements.txt`

---

## [Oncelik: Yuksek] 1. Test Altyapisinin Kurulmasi

**Kategori:** Teknik Borc / Kalite Guvencesi
**Mevcut durum:**
- `requirements.txt:6` pytest==6.2.5 bagimlilik olarak listelenmis ancak proje genelinde tek bir test dosyasi bile yok: `find src/ -name "test_*.py" -o -name "*_test.py"` komutu sifir sonuc donuyor.
- `conftest.py` dosyasi mevcut degil.
- `Makefile` icerisinde `test` hedefi tanimlanmamis.
- CI pipeline'da (`security-scan.yml`, `release.yml`) test calistiran hicbir adim yok.

**Sorun:** Kod tabaninda ~4.000 satir Python (blueprint'ler + altyapi modulleri) ve ~60 route handler mevcut. Herhangi bir degisikligin mevcut islevselligi bozup bozmadigini dogrulamanin otomatik bir yolu yok. Refactoring (ornegin verify_ssl deseni merkezilestirmesi, backlog #3) veya yeni ozellik eklemek yuksek regresyon riski tasiyor.

**Kabul kriterleri:**
- [ ] `tests/` dizini olusturulur ve en az 1 adet `conftest.py` dosyasi eklenir (Flask test client fixture'u iceren).
- [ ] Asagidaki 4 kategori icin en az birer test dosyasi yazilir:
  - `tests/test_health.py`: `/k8s-explorer/app-health` ve `/k8s-explorer/health` endpoint'leri icin en az 2 test (happy path + cluster baglanti hatasi simulasyonu).
  - `tests/test_audit_log.py`: `audit_log.py` icindeki `record_audit_event()` ve `get_recent_events()` fonksiyonlari icin en az 3 birim testi (kayit ekleme, limit kontrolu, disk yazma mock'u).
  - `tests/test_i18n.py`: `translate()` fonksiyonu icin en az 2 test (gecerli anahtar, gecersiz anahtar fallback'i).
  - `tests/test_kubeconfig_manager.py`: `list_kubeconfigs()` ve `get_active_kubeconfig_path()` icin en az 2 test.
- [ ] `Makefile`'a `test` hedefi eklenir: `$(PYTHON) -m pytest tests/ -v`.
- [ ] Tum testler `make test` ile hatasiz calisir (exit code 0).

---

## [Oncelik: Yuksek] 2. CI Pipeline: Her PR'da Calisacak Temel Kalite Kontrolleri

**Kategori:** CI/CD
**Mevcut durum:**
- `.github/workflows/security-scan.yml`: Yalnizca gitleaks secret taramasi yapiyor (her push/PR).
- `.github/workflows/release.yml`: Yalnizca `v*.*.*` tag push'larinda macOS/Windows build + GitHub Release olusturuyor.
- Her PR'da veya her push'ta calisacak bir lint, typecheck veya test job'u **mevcut degil**.
- Python kodu icin kurulu bir lint araci (flake8, ruff, mypy) requirements.txt'te yok.

**Sorun:** Gecersiz Python syntax'i, import hatalari veya temel mantik hatalari ancak calistirma sirasinda ortaya cikiyor. Bir PR merge edildikten sonra `main` branch'te runtime hatasi olusursa, bunu yakalamak icin mekanizma yok.

**Kabul kriterleri:**
- [ ] `.github/workflows/ci.yml` dosyasi olusturulur; `push` (main) ve `pull_request` olaylarinda tetiklenir.
- [ ] Job adimlari en az su 3 kontrolu icerir:
  1. Python syntax kontrolu (`python -m py_compile` veya `ruff check` veya `flake8 --select=E9,F63,F7,F82`).
  2. `pytest tests/ -v` (backlog #1 tamamlandiktan sonra).
  3. `python -c "from web.app import app; print('import OK')"` — uygulamanin import zincirinin kirilmamis oldugunu dogrular.
- [ ] CI job'u ubuntu-latest uzerinde calisan `python:3.9` (veya requirements.txt ile uyumlu surumu) kullanir.
- [ ] Herhangi bir adim basarisiz olursa PR merge edilemez (`branch protection` onerisi README'ye eklenir).

---

## [Oncelik: Yuksek] 3. Kubernetes Client Baslangic Kodunun Merkezilestirmesi ve verify_ssl Stratejisi

**Kategori:** Teknik Borc / Guvenlik
**Mevcut durum:**
- Asagidaki 6 satirlik blok, blueprint dosyalarinda toplamda **40'tan fazla yerde** birebir tekrarlaniyor:
  ```python
  load_kube_config_active()
  c = client.Configuration.get_default_copy()
  c.verify_ssl = False
  c.assert_hostname = False
  client.Configuration.set_default(c)
  ```
  Ornek konumlar: `explorer/core.py:174-178`, `explorer/network.py:22-26`, `explorer/storage.py:22-26`, `explorer/config.py:26-30`, `explorer/controllers.py:27-31`, `explorer/cluster.py:24-28`, `explorer/scaling.py:22-26`, `security/scanning.py:74-78`, `security/analysis.py` (birden fazla).
- `verify_ssl = False` **her yerde koşulsuz** olarak ayarlaniyor. Kullaniciya SSL dogrulamasini etkinlestirme secenegi sunulmuyor.
- `core.py:224` `k8s_explorer_describe()` endpoint'i diger route'lardan farkli olarak `os.environ.get('KUBECONFIG')` kullaniyor; `get_active_kubeconfig_path()` kullanmiyor. Bu, aktif kubeconfig ile tutarsizlik yaratir.

**Sorun:** (1) Bir hata duzeltmesi veya davranis degisikligi yapildiginda 40+ kopyayi ayri ayri guncellemek gerekiyor ve unutulan kopyalar tutarsizlik yaratir. (2) SSL dogrulamasinin koşulsuz devre disi birakilmasi, man-in-the-middle saldiri riskini artiriyor — ozellikle uzak cluster'larla iletisimde. (3) `describe` endpoint'i yanlis kubeconfig kullanabilir.

**Kabul kriterleri:**
- [ ] Yeni bir yardimci fonksiyon olusturulur (ornegin `kubeconfig_manager.py` icinde `get_kube_api_client()` veya benzeri) — `load_kube_config_active()` + `Configuration` ayarlamalarini tek bir yere toplar.
- [ ] Tum blueprint dosyalarindaki tekrarlanan 6 satirlik bloklar bu yeni fonksiyonla degistirilir.
- [ ] `verify_ssl` ayari bir ortam degiskeninden (`KUBESEC_VERIFY_SSL=1` gibi) okunur; varsayilan `False` kalabilir ama dokumante edilir.
- [ ] `core.py` icindeki `k8s_explorer_describe()` route'u `get_active_kubeconfig_path()` kullanacak sekilde duzeltilir; `os.environ.get('KUBECONFIG')` kullanimindan cekilir.
- [ ] Degisiklik sonrasi uygulama hatasiz baslar ve en az 3 farkli sayfa (workloads, nodes, network) duzgun calisir.

---

## [Oncelik: Yuksek] 4. API Endpoint'lerinde Sayfalama (Pagination) Destegi

**Kategori:** Performans
**Mevcut durum:**
- Tum liste endpoint'leri (`deployments-summary`, `services-summary`, `pvcs-summary`, `configmaps-summary`, `secrets-summary`, `nodes`, `rbac-summary`, `hpa-summary`, `pdb-summary`, `leases-summary`, vb.) tum kaynaklari tek bir JSON yaniti olarak donduruyor — `list_*_for_all_namespaces()` cagrisi sinirsiz.
- Frontend sablonlari (workloads.html, config.html, network.html, storage.html, access_control.html) tum verileri tek seferde client-side tabloya yukluyorlar.
- Buyuk cluster'larda (500+ pod, 200+ service, 100+ configmap) bu yaklasim:
  - Backend tarafinda yuksek bellek tuketimi ve uzun yanit sureleri yaratir.
  - Frontend tarafinda tarayicinin donmasina veya yavalamasina yol acar.
  - `background.py:86-199` `update_workload_stats_cache()` fonksiyonu tum pod'lari, deployment'lari, daemonset'leri, statefulset'leri, replicaset'leri, job'lari ve cronjob'lari tek seferde cekiyor.

**Sorun:** Uygulama kucuk/orta cluster'larda (50 pod, 10 namespace) sorunsuz calisir ancak buyuk/kurumsal cluster'larda (1000+ pod, 50+ namespace) kullanim disinda kalabilir.

**Kabul kriterleri:**
- [x] En az 3 yuksek hacimli endpoint (`deployments-summary`, `pods-summary`, `configmaps-summary`) `?page=N&per_page=M` (varsayilan: page=1, per_page=50 — spec'te 100'den 50'ye revize edildi) parametrelerini destekler.
- [x] Sayfalama olmayan mevcut istekler (parametre gonderilmediginde) geriye donuk uyumlu kalir (tum veriyi dondurur).
- [x] Frontend'te en az 1 sayfada (workloads.html — Pods ve Deployments sekmeleri) server-side pagination entegre edilir: "Onceki / Sonraki" butonlari + sayfa gostergesi, i18n uyumlu.
- [x] Sayfalama mantigi (dilim, total, total_pages hesabi) 31 birim test + bagimsiz QA ile dogrulandi; gercek 500+ kaynakli bir cluster bu ortamda mevcut olmadigindan gercek zamanlama testi yapilamadi, ancak in-memory slicing yaklasimi (tek K8s API cagrisi + Python tarafinda dilimleme) payload boyutunu buyuk oranda kucultuyor.
  - Spec: `docs/specs/20260721-api-pagination-destegi.md` (13 AC, 11 zorunlu CONFIRMED, 2 opsiyonel — per_page dropdown ve config.html UI — yapilmadi, acik birakildi).

---

## [Oncelik: Orta] 5. Guvenlik: Debug Endpoint'inin Uretimd Devre Disi Birakilmasi

**Kategori:** Guvenlik
**Mevcut durum:**
- `app.py:106-128` `/_debug/list-templates` endpoint'i her ortamda (development, production, PyInstaller bundle) erisime acik.
- Bu endpoint, sunucunun dosya sistemi yollarini (`template_folder`, `static_folder`) ve bu dizinlerdeki dosya isimlerini JSON olarak donduruyor.
- Hicbir kimlik dogrulama veya yetkilendirme kontrolu yok.

**Sorun:** Uretim ortaminda sunucu dosya sistemi yapisi disariya sizdirilir. Bu bilgi, bir saldirganin hedefli dosya dahil etme (file inclusion) veya path traversal saldirilari planlamasina yardimci olabilir.

**Kabul kriterleri:**
- [ ] `/_debug/list-templates` endpoint'i yalnizca `FLASK_ENV=development` veya `FLASK_DEBUG=1` iken erisime acik olur; aksi halde 404 dondurur.
- [ ] PyInstaller bundle'inda (`getattr(sys, 'frozen', False)` durumunda) bu endpoint her zaman devre disi kalir.
- [ ] Degisiklik sonrasi `make run-dev` ile endpoint erisilebilir, `make run` ile erisilemez.

---

## [Oncelik: Orta] 6. Guvenlik: CSRF Korumasi Eklenmesi

**Kategori:** Guvenlik
**Mevcut durum:**
- Flask uygulamasinda CSRF token mekanizmasi (Flask-WTF veya benzeri) kullanilmiyor.
- Mutasyon yapan tum POST endpoint'leri (`/k8s-explorer/delete`, `/k8s-explorer/yaml PATCH`, `/k8s-explorer/node-drain`, `/k8s-explorer/node-cordon`, `/k8s-explorer/update-configmap`, `/k8s-explorer/update-hpa`, `/k8s-explorer/update-pdb`, `/kubeconfigs/activate`, `/kubeconfigs POST`, `/trivy-operator/install`, `/trivy-operator/scan`) CSRF korumasindan yoksun.
- CORS ayarlari `app.py:7-48` ile `http://localhost:8080` ve `http://127.0.0.1:8080` origin'lerine kilitlenmis; bu, masaustu uygulamasi icin yeterli ancak Docker/uzak sunucu senaryosunda yetersiz olabilir.

**Sorun:** Bir kullanici Kube-Sec'e giris yapmis durumdayken kotu niyetli bir web sayfasini ziyaret ederse, o sayfa kullanicinin tarayicisi uzerinden Kube-Sec'e POST istekleri gonderebilir (ornegin node drain, kaynak silme). CORS bu riski kisitlar ancak basit POST isteklerini (application/x-www-form-urlencoded) engellemez.

**Kabul kriterleri:**
- [ ] Mutasyon yapan tum POST/PATCH/DELETE endpoint'leri icin CSRF koruma mekanizmasi eklenir (Flask-WTF `CSRFProtect` veya custom `X-CSRF-Token` header kontrolu).
- [ ] Frontend'teki tum `fetch()` POST cagrılari CSRF token'i iceren header veya body parametresi gonderir.
- [ ] CSRF token olmadan yapilan bir POST istegi HTTP 400 veya 403 ile reddedilir.
- [ ] Mevcut islevsellik (kaynak silme, YAML guncelleme, node drain, scale) CSRF token'li olarak calismaya devam eder.

---

## [Oncelik: Orta] 7. Guvenlik: Subprocess Komutlarinda Girdi Dogrulamasi

**Kategori:** Guvenlik
**Mevcut durum:**
- `explorer/core.py:213-234` `k8s_explorer_describe()` endpoint'i: `obj_type` parametresi `['pod', 'deployment']` listesiyle dogrulanıyor, ancak `name` ve `namespace` parametreleri **hicbir dogrulama veya sanitizasyon olmadan** dogrudan `subprocess.run()` komut dizisine ekleniyor.
  ```python
  cmd = ["kubectl", "describe", obj_type, name, "-n", namespace]
  ```
- `security/scanning.py:44-52` `_run_cmd()` fonksiyonu ve `_kubectl_base_args()` fonksiyonu benzer sekilde subprocess cagrilari yapiyor (satir 243-294 arasi Trivy Operator install ve scan islemleri).
- `subprocess.run()` ve `subprocess.Popen()` cagrıları `shell=False` ile yapiliyor (bu iyi) ancak arguman olarak kullanici girdisi dogrulanmiyor.

**Sorun:** `shell=False` kullanimi dogrudan shell injection'i onlese de, ozel karakterler iceren `name` veya `namespace` degerleri kubectl komutunun beklenmedik davranmasina yol acabilir. Ornegin, `--kubeconfig /etc/shadow` gibi bir `name` degeri kubectl'in beklenmedik dosyalari okumasina neden olabilir.

**Kabul kriterleri:**
- [ ] `name` ve `namespace` parametreleri icin bir dogrulama fonksiyonu olusturulur: yalnizca alfanumerik karakterler, tire (-), alt cizgi (_) ve nokta (.) kabul edilir; Kubernetes DNS naming kurallarina uygunluk kontrol edilir (RFC 1123).
- [ ] `k8s_explorer_describe()` endpoint'i ve `_kubectl_base_args()` kullanan tum endpoint'lerde bu dogrulama uygulanir.
- [ ] Gecersiz girdi durumunda HTTP 400 ile aciklayici hata mesaji dondurulur.
- [ ] `obj_type` icin mevcut whitelist kontrolu korunur ve genisletilir (sadece 'pod' ve 'deployment' degil, diger desteklenen tipler de eklenir).

---

## [Oncelik: Orta] 8. Docker Imajinin Iyilestirilmesi

**Kategori:** Paketleme / Dagitim
**Mevcut durum:**
- `Dockerfile`: `python:3.9-slim` temel imajı kullaniyor (Python 3.9 Ekim 2025'te end-of-life oldu).
- Container root kullanici olarak calisiyor — `USER` direktifi yok.
- Health check tanimlanmamis (`HEALTHCHECK` yok).
- `yaml/` dizini `COPY` edilmiyor; Trivy Operator install ve kubectl-based islemler `yaml/` altindaki manifest dosyalarina bagimli (icerisindeki dosyalar bulunamaz).
- `styles/` dizini de kopyalanmiyor (paketlenmis uygulama icin gerekli olabilir).
- Port expose edilmemis (`EXPOSE 8080` yok).
- `.dockerignore` dosyasi mevcut degil; `.venv/`, `node_modules/`, `dist/`, `build/`, `kubeconfigs/` gibi gereksiz dosyalar imaja dahil olabilir.

**Sorun:** Mevcut Docker imaji uretim ortami icin en iyi uygulamalara uymuyor. Root olarak calismasi container-escape senaryolarinda riski artirir; health check olmamasi orkestrasyon platformlarinin (Kubernetes, Docker Swarm) konteynerin saglik durumunu izlemesini engeller.

**Kabul kriterleri:**
- [ ] Temel imaj `python:3.11-slim` veya `python:3.12-slim` (aktif olarak desteklenen surum) olarak guncellenir.
- [ ] Dockerfile'a non-root kullanici eklenir (`RUN adduser --disabled-password appuser && USER appuser`).
- [ ] `HEALTHCHECK CMD curl -f http://localhost:8080/k8s-explorer/app-health || exit 1` (veya wget tabanlı) eklenir.
- [ ] `yaml/` dizini `COPY yaml/ ./yaml/` ile imaja dahil edilir.
- [ ] `EXPOSE 8080` eklenir.
- [ ] `.dockerignore` dosyasi olusturulur: `.venv/`, `node_modules/`, `dist/`, `build/`, `kubeconfigs/`, `.git/`, `__pycache__/`, `*.pyc` dahil edilir.
- [ ] `docker build -t kube-sec . && docker run --rm kube-sec` ile imaj basariyla build edilir ve uygulama baslar.

---

## [Oncelik: Orta] 9. K8sScanner Sinifinin Modernizasyonu veya Kaldirilmasi

**Kategori:** Teknik Borc
**Mevcut durum:**
- `src/scanner/k8s_scanner.py` (66 satir): Temel statik guvenlik kontrolleri yapiyor (image :latest, resource limits, security context, hostPath, capabilities, probes, service account, network policy).
- Zafiyet mesajlari **tamamen hardcoded Ingilizce** — i18n sistemini hic kullanmiyor (ornek: satir 15 "Deployment does not have a security context.", satir 21 "Container {container.name} uses 'latest' image tag.").
- Bu sinif YALNIZCA `security/scanning.py:85-86` icindeki `vulnerabilities` route'u tarafindan kullaniliyor (`scanner = K8sScanner(kube_client); vulns = scanner.list_vulnerabilities(dep)`).
- PSS analizi (`background.py` icindeki `_evaluate_pod_pss_compliance`) ve YAML linter (`security/analysis.py:51-100` icindeki `_yaml_lint_document`) zaten benzer kontrolleri **daha kapsamli** ve **i18n uyumlu** sekilde yapiyor.
- `K8sScanner.list_vulnerabilities()` yalnizca Deployment tipini destekliyor; StatefulSet, DaemonSet, Job gibi diger workload tipleri taranamiyor.

**Sorun:** K8sScanner sinifi, uygulamanin geri kalaniyla tutarsiz ve bakimsiz kalmis bir bilesenidir. i18n uyumsuzlugu nedeniyle dil EN olarak secildiginde bile mesajlar Ingilizce kalir (bu beklenen), ancak dil TR secildiginde de mesajlar Ingilizce kalir (bu beklenmez). Ayrica PSS analizi ile olasilikla cakisanlar var.

**Kabul kriterleri:**
- [ ] K8sScanner sinifinin ciktilarindaki hardcoded mesajlar i18n anahtarlarina cevrilir VEYA sinif tamamen kaldirilip `vulnerabilities` route'u mevcut PSS analiz/YAML linter mekanizmalariyla yeniden yazilir.
- [ ] `vulnerabilities` route'u Deployment disinda en az StatefulSet ve DaemonSet tiplerini de tarar.
- [ ] Degisiklik sonrasi `/vulnerabilities` sayfasi hatasiz yuklenip zafiyet sonuclarini gosterir.

---

## [Oncelik: Orta] 10. Gelistiriciye Yonelik Mimari Dokumantasyonu

**Kategori:** Dokumantasyon
**Mevcut durum:**
- `README.md` (60+ satir): Kullaniciya yonelik kurulum ve ozellik listesi iceriyor; yeterli seviyede.
- `CLAUDE.md`: AI asistani icin yonergeler iceriyor; mimari hakkinda ozet bilgi var ancak gelistiriciye yonelik degil.
- Blueprint yapisinin (hangi dosyada hangi route'lar, bagimlilik zinciri) dokumante edildigi bir kaynak yok.
- `src/web/background.py` icindeki cache thread'lerinin yasam dongusu, zamanlama ve hata yonetim stratejisi kodun icine gomulu ve yalnizca kodu okuyarak anlasilabilir.
- Yeni bir gelistirici icin "bu projeye nasil katki saglanir" rehberi mevcut degil.

**Sorun:** Proje artik 15 blueprint modulu, 5 arka plan cache thread'i, i18n altyapisi ve audit log modulu iceren olgun bir kod tabanina sahip. Yeni bir gelistirici icin onboarding suresi gereksiz yere uzun.

**Kabul kriterleri:**
- [ ] `CONTRIBUTING.md` (veya README.md icinde "Gelistirme Rehberi" bolumu) olusturulur ve su konulari kapsar:
  1. Blueprint yapisi ve her blueprint'in sorumlulugu (route listesi degil, sorumluluk alani).
  2. Yeni bir route/endpoint nasil eklenir (kalip: `load_kube_config_active()` -> is mantigi -> `record_audit_event()` -> yanit).
  3. i18n: Yeni bir arayuz metni nasil eklenir (I18N dict'e anahtar ekleme -> template'te `t()` kullanma).
  4. Cache thread'leri: Yeni bir cache nasil eklenir.
  5. Test calistirma talimatı (`make test`).
- [ ] Dokumantasyondaki her madde en az 1 dosya:satir referansi icerir.
- [ ] Dokumantasyon Turkce yazilir.

---

## [Oncelik: Dusuk] 11. Linux Masaustu Paketleme Destegi

**Kategori:** Paketleme / Dagitim
**Mevcut durum:**
- macOS: `build_macos_app.sh`, `Kube-Sec.spec` (PyInstaller), `release.yml` (GitHub Actions) — tamamen calisir durumda (v1.0.0-rc8 yayinda).
- Windows: `build-windows.sh` / `build-windows.ps1` mevcut.
- Linux: Native masaustu paketi (AppImage, .deb, .rpm veya Flatpak) **mevcut degil**. Yalnizca `python src/main.py` veya Docker ile calistirma secenekleri var.
- `launcher.py` macOS/Windows icin tasarlanmis; Linux icin test edilmemis (pywebview Linux'ta farkli backend'ler kullanabilir — GTK, Qt).

**Sorun:** Kubernetes yoneticilerinin cogunlugu Linux masaustu kullanir. Docker ile calistirma mumkun olsa da, Docker icinden kullanicinin yerel kubeconfig'ine ve kubectl'ine erismek ek konfigürasyon gerektirir. Native bir masaustu paketi, kurulumu ve kullanimi basitlestirirdi.

**Kabul kriterleri:**
- [ ] Linux icin PyInstaller veya AppImage build scripti (`build_linux_app.sh` veya benzeri) eklenir.
- [ ] Build scripti en az Ubuntu 22.04 / Fedora 38 uzerinde test edilir.
- [ ] `release.yml` icine opsiyonel bir `build-linux` job'u eklenir (macOS/Windows job'lariyla paralel).
- [ ] Olusturulan Linux paketi basarila calisir: `./Kube-Sec` calistirma -> tarayici acilir -> ana sayfa yuklenir.

---

## [Oncelik: Dusuk] 12. CIS Kubernetes Benchmark Uyumluluk Raporu

**Kategori:** Guvenlik Ozelligi
**Mevcut durum:**
- Uygulama mevcut durumda su guvenlik kontrollerini yapiyor:
  - Privileged/root container tespiti (`privileged_containers.html`, `security/analysis.py`)
  - Riskli RBAC rolleri (`/rbac-risky-roles` route'u)
  - PSA/PSS namespace uyumlulugu (`pod_security_standards.html`, `background.py` PSS cache)
  - NetworkPolicy kapsam analizi (`network.html` netpol tab'i, `background.py` netpol cache)
  - ConfigMap icerisinde gizli bilgi taramasi (`configmap_secrets.html`)
- Ancak bu kontroller birbirinden bagimsiz ve belirli bir uyumluluk cercevesine (CIS Benchmark, NSA/CISA Kubernetes Hardening Guide) eslenemez.
- Kullanici, cluster'inin genel guvenlik durusunu tek bir bakista goremez — farkli sayfalari tek tek gezmesi gerekir.

**Sorun:** Kurumsal kullanicilar genellikle CIS Kubernetes Benchmark veya NSA/CISA rehberine uyumluluk raporu talep eder. Mevcut kontroller bu ihtiyaci kismen karsilasa da, esleme ve toplu raporlama eksik.

**Kabul kriterleri:**
- [ ] Yeni bir ekran (`/compliance` veya `/security-overview`) eklenir; mevcut tum guvenlik kontrollerinin sonuclarini toplu olarak gosterir.
- [ ] Her kontrol, en az 1 CIS Benchmark maddesiyle eslenir (ornegin "5.2.1 — Ensure that the cluster has at least one active policy control mechanism in place" <-> PSA analizi).
- [ ] Ekranda genel uyumluluk skoru (yuzde) hesaplanir: (gecen kontrol sayisi / toplam kontrol sayisi * 100).
- [ ] Sonuclar CSV veya PDF olarak disari aktarilabilir.

---

## [Oncelik: Dusuk] 13. macOS App Store Dagitimi (Ertelenmis — Mimari Karar Gerektirir)

**Kategori:** Paketleme / Dagitim
**Mevcut durum:**
- macOS masaustu uygulamasi PyInstaller ile paketleniyor, Developer ID ile imzalaniyor ve notarize ediliyor (release pipeline'i tamamen calisir).
- App Store dagitimi icin Apple **sandbox** zorunlulugu var. Kube-Sec'in `subprocess.Popen` ile `kubectl` ve `helm` calistirmasi, ag baglantilari yapmasi ve dosya sistemi erisimleri (kubeconfig okuma/yazma) sandbox kisitlamalariyla uyumsuz.
- Alternatif yaklasim: `kubectl`/`helm` yerine tamamen Kubernetes Python client kullanimi; ancak Trivy Operator kurulumu (`helm`) ve `kubectl describe` gibi islemler su an subprocess'e bagimli.

**Sorun:** Bu konu kullaniciyla gorusulmus ve **ertelenmistir**. Dogrudan developer distribution (notarize + DMG) halihazirda calisir durumda ve yeterlidir. App Store dagitimi olmasi-iyi-olur ancak onemli bir mimari degisiklik gerektirir.

**Kabul kriterleri:**
- [ ] (Gelecek donem) Sandbox uyumluluk analizi dokumante edilir: hangi subprocess cagrilari sandbox'ta calismaz, hangileri Kubernetes Python client ile degistirilebilir.
- [ ] (Gelecek donem) En az `kubectl describe` islevselliginin Python client'a tasinmasi ile subprocess bagimliligi azaltilir.

**Not:** Bu madde bilinçli olarak ertelenmis bir karar noktasidir; aktif gelistirme onceligi degildir.
