# Kube-Sec Backlog (v2)

> **Onceki backlog (v1) durumu:** 17 madde, 57 kabul kriteri — TAMAMI tamamlandi ve dogrulandi (2026-07-05 – 2026-07-20).
> **Bu backlog olusturulma tarihi:** 2026-07-21
> **Analiz kapsami:** 19 sablon dosyasi (`src/web/templates/*.html`), 15 blueprint modulu (`src/web/blueprints/**/*.py`), 7 altyapi modulu (`src/web/`), `src/scanner/k8s_scanner.py`, CI/CD dosyalari (`.github/workflows/`), `Dockerfile`, `Makefile`, `requirements.txt`

---

## [Oncelik: Yuksek] 1. Test Altyapisinin Kurulmasi — TAMAMLANDI

**Kategori:** Teknik Borc / Kalite Guvencesi
**Mevcut durum (onceki):**
- `requirements.txt:6` pytest==6.2.5 bagimlilik olarak listelenmis ancak proje genelinde tek bir test dosyasi bile yok: `find src/ -name "test_*.py" -o -name "*_test.py"` komutu sifir sonuc donuyor.
- `conftest.py` dosyasi mevcut degil.
- `Makefile` icerisinde `test` hedefi tanimlanmamis.
- CI pipeline'da (`security-scan.yml`, `release.yml`) test calistiran hicbir adim yok.

**Sorun:** Kod tabaninda ~4.000 satir Python (blueprint'ler + altyapi modulleri) ve ~60 route handler mevcut. Herhangi bir degisikligin mevcut islevselligi bozup bozmadigini dogrulamanin otomatik bir yolu yok. Refactoring (ornegin verify_ssl deseni merkezilestirmesi, backlog #3) veya yeni ozellik eklemek yuksek regresyon riski tasiyor.

**Kabul kriterleri:**
- [x] `tests/` dizini olusturulur ve en az 1 adet `conftest.py` dosyasi eklenir (Flask test client fixture'u iceren).
- [x] Asagidaki 4 kategori icin en az birer test dosyasi yazilir:
  - `tests/test_health.py`: `/k8s-explorer/app-health` ve `/k8s-explorer/health` endpoint'leri icin en az 2 test (happy path + cluster baglanti hatasi simulasyonu).
  - `tests/test_audit_log.py`: `audit_log.py` icindeki `record_audit_event()` ve `get_recent_events()` fonksiyonlari icin en az 3 birim testi (kayit ekleme, limit kontrolu, disk yazma mock'u).
  - `tests/test_i18n.py`: `translate()` fonksiyonu icin en az 2 test (gecerli anahtar, gecersiz anahtar fallback'i).
  - `tests/test_kubeconfig_manager.py`: `list_kubeconfigs()` ve `get_active_kubeconfig_path()` icin en az 2 test.
- [x] `Makefile`'a `test` hedefi eklenir: `$(PYTHON) -m pytest tests/ -v`.
- [x] Tum testler `make test` ile hatasiz calisir (exit code 0).

**Uygulama notu (2026-07-23):** product-manager -> qa-engineer -> bagimsiz code-reviewer (statik dogrulama) + ben (bizzat `make test` calistirarak AC-7/AC-9/AC-10 teyidi) zinciriyle tamamlandi. Spec: `docs/specs/20260723-test-altyapisi-kurulumu.md` (12 AC). Mevcut `test_csrf.py`/`test_validators.py` (backlog #6/#7'den) `conftest.py`'ye tasindi (tekrarlanan `sys.path.insert` kaldirildi). Sonuc: 59 test, `make test` ile PASSED, exit code 0; audit log ve kubeconfig testleri gercek disk/dizine dokunmuyor (dogrulandi). AC-12 (basarili cluster mock testi) opsiyoneldi, kismi yapildi (Content-Type testi eklendi, `ok:true` senaryosu acik birakildi).

---

## [Oncelik: Yuksek] 2. CI Pipeline: Her PR'da Calisacak Temel Kalite Kontrolleri — TAMAMLANDI

**Kategori:** CI/CD
**Mevcut durum (onceki):**
- `.github/workflows/security-scan.yml`: Yalnizca gitleaks secret taramasi yapiyor (her push/PR).
- `.github/workflows/release.yml`: Yalnizca `v*.*.*` tag push'larinda macOS/Windows build + GitHub Release olusturuyor.
- Her PR'da veya her push'ta calisacak bir lint, typecheck veya test job'u **mevcut degil**.
- Python kodu icin kurulu bir lint araci (flake8, ruff, mypy) requirements.txt'te yok.

**Sorun:** Gecersiz Python syntax'i, import hatalari veya temel mantik hatalari ancak calistirma sirasinda ortaya cikiyor. Bir PR merge edildikten sonra `main` branch'te runtime hatasi olusursa, bunu yakalamak icin mekanizma yok.

**Kabul kriterleri:**
- [x] `.github/workflows/ci.yml` dosyasi olusturulur; `push` (main) ve `pull_request` olaylarinda tetiklenir.
- [x] Job adimlari en az su 3 kontrolu icerir:
  1. Python syntax kontrolu (`python -m py_compile` veya `ruff check` veya `flake8 --select=E9,F63,F7,F82`).
  2. `pytest tests/ -v` (backlog #1 tamamlandiktan sonra).
  3. `python -c "from web.app import app; print('import OK')"` — uygulamanin import zincirinin kirilmamis oldugunu dogrular.
- [x] CI job'u ubuntu-latest uzerinde calisan `python:3.9` (veya requirements.txt ile uyumlu surumu) kullanir.
- [x] Herhangi bir adim basarisiz olursa PR merge edilemez (`branch protection` onerisi README'ye eklenir).

**Uygulama notu (2026-07-24):** product-manager -> devops-engineer -> bagimsiz code-reviewer (statik dogrulama) + ben (bizzat YAML/import/pytest calistirarak teyit) zinciriyle tamamlandi. Spec: `docs/specs/20260723-ci-pipeline-temel-kalite-kontrolleri.md` (14 AC, tumu CONFIRMED). Mekanizma: `.github/workflows/ci.yml` — `ubuntu-latest` + Python 3.9, 3 adim (ruff `E9,F63,F7,F82` -> import zinciri kontrolu -> `pytest tests/ -v`), `permissions: contents: read`, `continue-on-error` yok (herhangi bir adim basarisiz olursa job FAIL olur). `ruff` yalnizca CI'da kuruluyor, `requirements.txt`'e kalici bagimlilik eklenmedi. `README.md`'ye "Branch Protection Onerisi" bolumu eklendi (repo ayarlarindan manuel etkinlestirme gerektigi belirtildi — bu bir kod degisikligi degil). Yerel dogrulama: YAML gecerli, `PYTHONPATH=src python -c "from web.app import app"` OK, `pytest tests/ -v` PASSED (calisma anindaki toplam test sayisi, backlog #1'deki 59'dan fazla oldu cunku es zamanli baska bir oturum `tests/test_error_handler.py` ekliyordu — bu maddenin kapsami disinda, path olarak ayrisiyor).

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
- [x] Yeni bir yardimci fonksiyon olusturulur (`kubeconfig_manager.py` icinde `configure_kube_client()`) — `load_kube_config_active()` + `Configuration` ayarlamalarini tek bir yere toplar.
- [x] Tum blueprint dosyalarindaki tekrarlanan 6 satirlik bloklar bu yeni fonksiyonla degistirilir (13 dosya, gercek envanter 94 degil **99 konum** — spec'in tahmininden fazlasi bulunup duzeltildi; `grep -rn "verify_ssl\s*=\s*False" src/web/` sifir sonuc).
- [x] `verify_ssl` ayari bir ortam degiskeninden (`KUBESEC_VERIFY_SSL=1` gibi) okunur; varsayilan `False` kalir, `CLAUDE.md`'de dokumante edildi. Breaking change yok.
- [x] `core.py` icindeki `k8s_explorer_describe()` route'u `get_active_kubeconfig_path()` kullanacak sekilde duzeltildi; `os.environ.get('KUBECONFIG')` kullanimindan cekildi.
- [x] Degisiklik sonrasi uygulama hatasiz basliyor, `/k8s-explorer/health`, `/compliance`, `/k8s-explorer/nodes`, `/k8s-explorer/services-summary`, `/k8s-explorer/rbac-summary` HTTP 200 donuyor.
  - Spec: `docs/specs/20260722-kube-client-merkezilestirme.md` (10 AC, 8 zorunlu/orta CONFIRMED — iki bagimsiz dogrulama; code-reviewer 2 kucuk bulgu (kullanilmayan import x2, guncel olmayan docstring) tespit etti, dogrudan duzeltildi. AC-9 dokumantasyon opsiyoneldi, yapildi.

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
- [x] `/_debug/list-templates` endpoint'i yalnizca `FLASK_ENV=development` veya `FLASK_DEBUG=1` iken erisime acik olur; aksi halde route Flask'in `url_map`'ine hic kayit edilmez (guvenlik hedefi: handler kodu hicbir zaman calismiyor, dosya sistemi bilgisi sizmiyor).
- [x] PyInstaller bundle'inda (`getattr(sys, 'frozen', False)` durumunda) bu endpoint her zaman devre disi kalir (env var'lardan bagimsiz, `AND` kisa devre).
- [x] Degisiklik sonrasi `make run-dev` ile endpoint erisilebilir (HTTP 200), `make run` ile erisilemez.
  - Spec: `docs/specs/20260723-debug-endpoint-flask-env-kapisi.md` (10 AC, tumu CONFIRMED — iki bagimsiz dogrulama). **Not:** `make run` modunda literal HTTP kodu 404 degil 500 donuyor; nedeni bu maddenin degisikligi degil, uygulamadaki onceden var olan genel `@app.errorhandler(Exception)` handler'inin `NotFound` dahil TUM exception'lari 500'e cevirmesi (bkz. madde 14). Route `url_map`'te kesin olarak yok (dogrulandi), guvenlik hedefi tam saglaniyor.

---

## [Oncelik: Orta] 6. Guvenlik: CSRF Korumasi Eklenmesi

**Kategori:** Guvenlik
**Mevcut durum:**
- Flask uygulamasinda CSRF token mekanizmasi (Flask-WTF veya benzeri) kullanilmiyor.
- Mutasyon yapan tum POST endpoint'leri (`/k8s-explorer/delete`, `/k8s-explorer/yaml PATCH`, `/k8s-explorer/node-drain`, `/k8s-explorer/node-cordon`, `/k8s-explorer/update-configmap`, `/k8s-explorer/update-hpa`, `/k8s-explorer/update-pdb`, `/kubeconfigs/activate`, `/kubeconfigs POST`, `/trivy-operator/install`, `/trivy-operator/scan`) CSRF korumasindan yoksun.
- CORS ayarlari `app.py:7-48` ile `http://localhost:8080` ve `http://127.0.0.1:8080` origin'lerine kilitlenmis; bu, masaustu uygulamasi icin yeterli ancak Docker/uzak sunucu senaryosunda yetersiz olabilir.

**Sorun:** Bir kullanici Kube-Sec'e giris yapmis durumdayken kotu niyetli bir web sayfasini ziyaret ederse, o sayfa kullanicinin tarayicisi uzerinden Kube-Sec'e POST istekleri gonderebilir (ornegin node drain, kaynak silme). CORS bu riski kisitlar ancak basit POST isteklerini (application/x-www-form-urlencoded) engellemez.

**Kabul kriterleri:**
- [x] Mutasyon yapan tum POST/PATCH/DELETE endpoint'leri icin CSRF koruma mekanizmasi eklenir (Flask-WTF `CSRFProtect` veya custom `X-CSRF-Token` header kontrolu).
- [x] Frontend'teki tum `fetch()` POST cagrılari CSRF token'i iceren header veya body parametresi gonderir.
- [x] CSRF token olmadan yapilan bir POST istegi HTTP 400 veya 403 ile reddedilir.
- [x] Mevcut islevsellik (kaynak silme, YAML guncelleme, node drain, scale) CSRF token'li olarak calismaya devam eder.

**Uygulama notu (2026-07-21):** product-manager -> backend-developer + web-frontend-developer (paralel) -> qa-engineer zinciriyle tamamlandi. Mekanizma: Flask-WTF `CSRFProtect` (global, route bazinda decorator gerekmiyor), `X-CSRFToken` header, `base.html`'de `csrf_token()` meta tag, `common.js`'de `getCsrfToken()`. 9 sablondaki toplam 35 POST/PATCH/DELETE fetch cagrisinin tamamina header eklendi (cift-grep ile 0 atlama dogrulandi). Spec: `docs/specs/20260721-csrf-korumasi-eklenmesi.md` (11 AC). Ilk QA turunde tek eksik olan AC-8 (kalici test dosyasi) icin `tests/test_csrf.py` eklendi ve 4/4 test gecti; QA sonrasinda genel karar APPROVE'a donustu. Not: repo o sirada paylasimliydi (paralel bir session #9/#12 uzerinde calisiyordu) — `app.py` ve `base.html`'deki CSRF disi hunk'lar bilerek unstaged birakilip yalniz kendi degisikliklerim commit edildi.

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
- [x] `name` ve `namespace` parametreleri icin bir dogrulama fonksiyonu olusturulur (`src/web/validators.py`: `validate_k8s_name()`, `validate_k8s_namespace()`, `validate_helm_version()`) — RFC 1123 DNS subdomain/label kurallarina uygunluk regex ile kontrol edilir (alt cizgi RFC 1123'e uymadigi icin kapsanmadi, K8s'in kendi kurallarina sadik kalindi).
- [x] `k8s_explorer_describe()` route'unda `name`/`namespace` ve `trivy_operator_install()` route'unda `version` parametresi bu dogrulamadan gecer (guncel kod tabaninda subprocess cagrisi yalnizca bu 2 dosyada, 2 kullanici-girdili noktada bulundu — `_kubectl_base_args()` kendisi subprocess kullanmiyor, sadece arguman listesi uretiyor).
- [x] Gecersiz girdi durumunda HTTP 400 + aciklayici hata mesaji donduruluyor (flag injection: `name=--kubeconfig`, path traversal: `namespace=../../etc/shadow` dogrulandi).
- [x] `obj_type` whitelist'i 2 tipten (`pod`, `deployment`) 34 tipe genisletildi (`ALLOWED_DESCRIBE_TYPES` frozenset — workloads, network, config/storage, RBAC, cluster, scaling/policy kaynaklari).
  - Spec: `docs/specs/20260723-subprocess-girdi-dogrulama.md` (10 AC, 9 zorunlu/orta CONFIRMED — iki bagimsiz dogrulama turu; 1. turda code-reviewer bir teknik kusur buldu (`$` regex anchor'i Python'da trailing `\n`'i gormezden gelebiliyordu, `\Z` ile duzeltildi), 2. turda APPROVE. `tests/test_validators.py` 42 test ile eklendi (backlog #1'in ilk somut adimi). AC-10 (import'lari dosya basina tasima) opsiyoneldi, yapilmadi.

---

## [Oncelik: --] 8. Docker Destegi (DEPRECATE EDILDI)

Mimari karar geregi Kube-Sec yalnizca masaustu (PyInstaller) paketleme ile dagitilmaktadir. Docker imaji artik bakim altinda degildir ve iyilestirme planlanmamaktadir.

---

## [Oncelik: Orta] 9. K8sScanner Sinifinin Modernizasyonu veya Kaldirilmasi ✅ TAMAMLANDI

**Kategori:** Teknik Borc
**Mevcut durum:**
- `src/scanner/k8s_scanner.py` (66 satir): Temel statik guvenlik kontrolleri yapiyor (image :latest, resource limits, security context, hostPath, capabilities, probes, service account, network policy).
- Zafiyet mesajlari **tamamen hardcoded Ingilizce** — i18n sistemini hic kullanmiyor (ornek: satir 15 "Deployment does not have a security context.", satir 21 "Container {container.name} uses 'latest' image tag.").
- Bu sinif YALNIZCA `security/scanning.py:85-86` icindeki `vulnerabilities` route'u tarafindan kullaniliyor (`scanner = K8sScanner(kube_client); vulns = scanner.list_vulnerabilities(dep)`).
- PSS analizi (`background.py` icindeki `_evaluate_pod_pss_compliance`) ve YAML linter (`security/analysis.py:51-100` icindeki `_yaml_lint_document`) zaten benzer kontrolleri **daha kapsamli** ve **i18n uyumlu** sekilde yapiyor.
- `K8sScanner.list_vulnerabilities()` yalnizca Deployment tipini destekliyor; StatefulSet, DaemonSet, Job gibi diger workload tipleri taranamiyor.

**Sorun:** K8sScanner sinifi, uygulamanin geri kalaniyla tutarsiz ve bakimsiz kalmis bir bilesenidir. i18n uyumsuzlugu nedeniyle dil EN olarak secildiginde bile mesajlar Ingilizce kalir (bu beklenen), ancak dil TR secildiginde de mesajlar Ingilizce kalir (bu beklenmez). Ayrica PSS analizi ile olasilikla cakisanlar var.

**Kabul kriterleri:**
- [x] K8sScanner sinifinin ciktilarindaki hardcoded mesajlar i18n anahtarlarina cevrilir VEYA sinif tamamen kaldirilip `vulnerabilities` route'u mevcut PSS analiz/YAML linter mekanizmalariyla yeniden yazilir. (Secenek B uygulandi: `src/scanner/k8s_scanner.py` silindi, `src/web/blueprints/security/_vuln_checks.py` ile yeniden yazildi.)
- [x] `vulnerabilities` route'u Deployment disinda en az StatefulSet ve DaemonSet tiplerini de tarar.
- [x] Degisiklik sonrasi `/vulnerabilities` sayfasi hatasiz yuklenip zafiyet sonuclarini gosterir.

**Uygulama notu (2026-07-21):** product-manager -> backend-developer + localization-engineer (paralel) -> qa-engineer zinciriyle tamamlandi. Spec: `docs/specs/20260721-k8sscanner-modernizasyonu.md`. QA dogrulamasinda 12 kabul kriterinin (AC-1..AC-12) tamami CONFIRMED (AC-12, ilk QA turunde bos-durum ekranindaki kalan hardcoded metin nedeniyle FAILED cikti, hemen ardindan 6 yeni i18n anahtariyla kapatildi).

---

## [Oncelik: Orta] 10. Gelistiriciye Yonelik Mimari Dokumantasyonu — TAMAMLANDI

**Kategori:** Dokumantasyon
**Mevcut durum (onceki):**
- `README.md` (60+ satir): Kullaniciya yonelik kurulum ve ozellik listesi iceriyor; yeterli seviyede.
- `CLAUDE.md`: AI asistani icin yonergeler iceriyor; mimari hakkinda ozet bilgi var ancak gelistiriciye yonelik degil.
- Blueprint yapisinin (hangi dosyada hangi route'lar, bagimlilik zinciri) dokumante edildigi bir kaynak yok.
- `src/web/background.py` icindeki cache thread'lerinin yasam dongusu, zamanlama ve hata yonetim stratejisi kodun icine gomulu ve yalnizca kodu okuyarak anlasilabilir.
- Yeni bir gelistirici icin "bu projeye nasil katki saglanir" rehberi mevcut degil.

**Sorun:** Proje artik 15 blueprint modulu, 5 arka plan cache thread'i, i18n altyapisi ve audit log modulu iceren olgun bir kod tabanina sahip. Yeni bir gelistirici icin onboarding suresi gereksiz yere uzun.

**Kabul kriterleri:**
- [x] `CONTRIBUTING.md` olusturuldu (repo kokunde, 444 satir) ve su konulari kapsiyor:
  1. Blueprint yapisi ve her blueprint'in sorumlulugu (kubeconfigs, workloads, security, explorer + alt-moduller).
  2. Yeni bir route/endpoint nasil eklenir (kalip: `configure_kube_client()` -> is mantigi -> `record_audit_event()` -> `session_id` -> yanit).
  3. i18n: Yeni bir arayuz metni nasil eklenir (I18N dict'e anahtar ekleme -> template'te `t()` kullanma -> `i18n_json`).
  4. Cache thread'leri: 5 mevcut cache tablo halinde + yeni cache ekleme kalibi + backoff mekanizmasi.
  5. Test calistirma talimatı (otomatik test yok, manuel dogrulama onerileri).
- [x] Dokumantasyondaki her ana bolum en az 1 dosya:satir referansi icerir — bagimsiz code-reviewer tum referanslari gercek kaynak koduyla tek tek dogruladi (26 referans, tumu ESLESTI).
- [x] Dokumantasyon Turkce yazildi.
- Ek: `README.md`'nin Contributing bolumu `CONTRIBUTING.md`'ye yonlendirecek sekilde guncellendi.
- Surec: Spec `product-manager` agent tarafindan hazirlandi (15 AC), `technical-writer` agent tarafindan uygulandi, bagimsiz `code-reviewer` agent tarafindan dogrulandi (15/15 AC CONFIRMED, 0 FAILED).
- Bilinen kucuk tutarsizlik (kapsam disi, ayri is): `README.md`'deki "Architecture Overview" bolumu hala eski "tek dosya, blueprint yok" tanimini kullaniyor; guncel degil.

---

## [Oncelik: Dusuk] 11. Linux Masaustu Paketleme Destegi — TAMAMLANDI

**Kategori:** Paketleme / Dagitim
**Mevcut durum (onceki):**
- macOS: `build_macos_app.sh`, `Kube-Sec.spec` (PyInstaller), `release.yml` (GitHub Actions) — tamamen calisir durumda (v1.0.0-rc8 yayinda).
- Windows: `build-windows.sh` / `build-windows.ps1` mevcut.
- Linux: Native masaustu paketi (AppImage, .deb, .rpm veya Flatpak) **mevcut degil**. Yalnizca `python src/main.py` veya Docker ile calistirma secenekleri var.
- `launcher.py` macOS/Windows icin tasarlanmis; Linux icin test edilmemis (pywebview Linux'ta farkli backend'ler kullanabilir — GTK, Qt).

**Sorun:** Kubernetes yoneticilerinin cogunlugu Linux masaustu kullanir. Docker ile calistirma mumkun olsa da, Docker icinden kullanicinin yerel kubeconfig'ine ve kubectl'ine erismek ek konfigürasyon gerektirir. Native bir masaustu paketi, kurulumu ve kullanimi basitlestirirdi.

**Karar:** PyInstaller `--onedir` + `tar.gz` (AppImage/.deb/.rpm/Flatpak kapsam disi birakildi — bkz. spec). Tam spec: `docs/specs/20260723-linux-masaustu-paketleme.md`.

**Kabul kriterleri:**
- [x] Linux icin PyInstaller build scripti eklendi: `build_linux_app.sh` (repo koku, `--onedir`, macOS'la ayni `--add-data` eslemeleri, pywebview/PyObjC modulleri disliyor, cikti `Kube-Sec-{VERSION}-linux-x86_64.tar.gz`).
- [x] `Makefile`'a `build-linux: version-sync` hedefi eklendi (`.PHONY`'ye eklendi).
- [x] `release.yml` icine opsiyonel/bloklamayan bir `build-linux` job'u eklendi (`ubuntu-latest`, macOS/Windows job'lariyla paralel, `create-release.needs` listesine EKLENMEDI, artifact indirme `continue-on-error: true`).
- [x] CI icinde smoke test: binary arka planda baslatilip `curl` ile ana sayfadan HTTP 200 dogrulaniyor.
- Not: "Fedora 38'de test edilir" kriteri kapsam disi birakildi — GitHub Actions'ta hosted Fedora runner yok; yalnizca `ubuntu-latest` ile dogrulaniyor (bkz. spec, Acik Sorular/Riskler).
- Surec: Spec `product-manager` agent tarafindan hazirlandi, `devops-engineer` agent tarafindan uygulandi, bagimsiz `qa-engineer` agent tarafindan dogrulandi (8/8 AC CONFIRMED, 0 FAILED). Gercek Ubuntu/Fedora runner'da fiili calisma dogrulamasi bir sonraki tag push'unda GitHub Actions uzerinden yapilacak (macOS'ta cross-compile mumkun degil).

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
- [x] Yeni bir ekran (`/compliance`) eklenir; mevcut tum guvenlik kontrollerinin sonuclarini toplu olarak gosterir.
- [x] Her kontrol, en az 1 CIS Benchmark maddesiyle eslenir (7 kontrol -> 5.2.1, 5.2.6, 5.2.2, 5.3.2, 5.4.1, 5.1.1, 5.2.7 — best-effort esleme, resmi CIS dogrulamasi kapsam disi).
- [x] Ekranda genel uyumluluk skoru (yuzde) hesaplanir: (gecen kontrol sayisi / (toplam - hata) * 100).
- [x] Sonuclar CSV olarak disari aktarilabilir (PDF kapsam disi birakildi — tarayicinin native "Print to PDF" ozelligi ile karsilaniyor, bkz. spec).
  - Spec: `docs/specs/20260721-cis-benchmark-uyumluluk-raporu.md` (13 AC, 11 zorunlu CONFIRMED — iki bagimsiz dogrulama turu; 1. turda code-reviewer'in buldugu kritik bir hata (C6 RBAC kontrolu, API erisim hatasinda sessizce PASS donuyordu) ve 4 orta duzey sorun 2. turda duzeltildi ve tekrar dogrulandi. AC-12/AC-13 opsiyonel, yapilmadi, acik birakildi).

---

## [Oncelik: Orta] 14. Guvenlik: Global Error Handler Stack Trace Sizintisi ve Yanlis HTTP Status Kodlari

**Kategori:** Guvenlik / Teknik Borc
**Bulunma kaynagi:** Backlog #5 (debug endpoint kapatma) dogrulama sirasinda code-reviewer tarafindan tespit edildi (2026-07-23).

**Mevcut durum:**
- `src/web/app.py` icindeki `@app.errorhandler(Exception)` handler'i (`handle_exception()`), `isinstance(e, HTTPException)` kontrolu yapmadan **TUM** exception turlerini yakalayip kosulsuz `jsonify({'error': str(e), 'traceback': tb}), 500` donduruyor.
- Flask'in kendi `_find_error_handler` mekanizmasi (`(code, None)` cift gecis mantigi), `werkzeug.exceptions.NotFound` (404), `MethodNotAllowed` (405) gibi standart HTTP exception'lari da bu genel handler'a yonlendiriyor — bu yuzden var olmayan HERHANGI bir route icin dogru 404 yerine 500 donuyor.
- **Daha ciddisi:** `'traceback': tb` satiri, tam Python stack trace'ini `make run` (production-benzeri, `FLASK_ENV`/`FLASK_DEBUG` set edilmemis) modunda bile HTTP yanit body'sine JSON olarak ekliyor. Bu, dosya yollari, fonksiyon isimleri, satir numaralari, bazen degisken degerleri gibi hassas ic bilgiyi disariya sizdirir.

**Sorun:** (1) Uretim benzeri modda calisan bir saldirgan, kasitli olarak hatali istekler (var olmayan route, gecersiz parametre vb.) gondererek uygulamanin ic yapisi (dosya yollari, kullanilan kutuphaneler, kod akisi) hakkinda detayli bilgi toplayabilir — bu, hedefli saldirilar icin bir kesif (reconnaissance) vektorudur. (2) Var olmayan route'lar icin 404 yerine 500 donmesi, izleme/monitoring araclarinin (ornegin bir uptime checker) yanlis alarm uretmesine veya gercek sunucu hatalarini 404'lerden ayirt edememesine yol acar.

**Kabul kriterleri:**
- [x] `handle_exception()` fonksiyonu `isinstance(e, HTTPException)` kontrolu yapar: `e` bir `HTTPException` ise (404, 405, 400 vb.), kendi `e.code` status kodu ve `e.description` mesajiyla doner — genel 500'e cevrilmez.
- [x] Yalnizca gercek beklenmeyen sunucu hatalari (HTTPException OLMAYAN exception'lar) icin 500 donulmeye devam eder; stderr loglamasi bu dalda korunur.
- [x] `traceback` alani production modda response'dan kaldirildi; yalnizca `FLASK_ENV=development`/`FLASK_DEBUG=1` iken (backlog #5'teki `_debug_enabled` degiskeni yeniden kullanilarak) eklenir.
- [x] Degisiklik sonrasi var olmayan bir route `make run` modunda dogru HTTP 404 doner (500 degil); yanlis HTTP metodu 405 doner. CSRF (backlog #6) ve validators (backlog #7) regresyon testleri (`tests/test_csrf.py`, `tests/test_validators.py`) etkilenmeden gecmeye devam ediyor — bu iki mekanizma zaten kendi `jsonify(...), 4xx` donuslerini exception firlatmadan yaptigi icin bu handler'a hic ugramiyor.
  - Spec: `docs/specs/20260723-error-handler-duzeltme.md` (10 AC, tumu CONFIRMED — iki bagimsiz dogrulama, ikisi de APPROVE; yuksek regresyon riski tasiyan bir degisiklik oldugu icin CSRF/validators/normal route'lar ozellikle test edildi, regresyon YOK. Yeni `tests/test_error_handler.py` (8 test) eklendi, toplam test paketi 67/67 PASSED. Code-reviewer'in bulgulari (500 yolu icin dogrudan unit test eksikligi, kucuk kod temizligi onerileri) dusuk/orta oncelikli, merge'i bloklamiyor, sonraki ise birakildi).
- [ ] Mevcut hata loglamasi (stderr'e `traceback.format_exc()` yazma) korunur — sadece HTTP yanitina traceback eklenmesi kisitlanir, sunucu taraflarindaki loglama kaybolmaz.
