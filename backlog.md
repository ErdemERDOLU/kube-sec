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

---

## [Oncelik: Yuksek] 15. UI/UX: Kritik Gorsel Hatalar ve Kirik Islevsellik

**Kategori:** UI/UX
**Bulunma kaynagi:** `web-frontend-developer` agent tarafindan yapilan kapsamli masaustu UI/UX denetimi (2026-07-24). Denetim, `chromium-cli` ortamda kurulu olmadigi icin sistemdeki Chrome'un headless modu + ozel bir CDP (WebSocket) istemcisiyle 20 route, 3 viewport'ta (1440x900 / 768x1024 / 390x844) taranarak yapildi; uygulama gercek bir cluster'a (`mbs-dev` context) bagliydi, bu yuzden dolu-durum UX'i degerlendirildi.

**Mevcut durum:**
- **Gorunmez sayfa basliklari (hero):** `access_control.html` ve `storage.html`, `class="hero-section bg-gradient-primary text-white"` kullaniyor ama `.hero-section` yalnizca `network.html`'in kendi gomulu `<style>` blogunda tanimli, `.bg-gradient-primary` hicbir yerde tanimli degil. Sonuc: beyaz yazi saydam/varsayilan zeminde — baslik neredeyse gorunmez.
- **`/kubeconfigs` route'u tarayicida ham JSON donduruyor:** Bu bir JSON API'si (`kubeconfigs.py:33`), `kubeconfigs.html` sablonu yok. Dogrudan ziyaret edildiginde dosya sistemi yollarini da iceren ham JSON goruyor kullanici (gercek kubeconfig yonetim arayuzu `/configuration`'da).
- **Workloads "Genel Bakis" grafikleri kirik:** `Highcharts is not defined` — kutuphane hic yuklenmiyor, pasta grafikler sessizce bos kaliyor.
- **Audit-trail sayfasinda cevrilmemis ham i18n anahtarlari gorunuyor:** `audit.empty_state`, `audit.filter_resource_type`, `audit.filter_action`, `audit.filter_all` `I18N` dict'inde tanimli degil; kullanici harfiyen anahtar isimlerini goruyor.
- **Ek JS hatalari:** `config.html`'de `Uncaught TypeError: Cannot read properties of null (reading 'replace')`; `privileged_containers.html:1516`'da prod'da kalmis bir debug `console.log`.

**Sorun:** Bu maddeler kullaniciya uygulamanin "bozuk" oldugu izlenimini veriyor — gorunmez basliklar ve kirik grafikler ozellikle yeni kullanicilar icin guven kaybi yaratir; `/kubeconfigs`'in ham JSON donmesi ayrica kucuk bir bilgi sizintisi riskidir (dosya sistemi yollari).

**Kabul kriterleri:**
- [ ] `.hero-section` ve `.bg-gradient-primary` stilleri `base.html`'e (global CSS) tasinir; access-control ve storage sayfalarinda baslik okunabilir hale gelir.
- [ ] `GET /kubeconfigs` route'u ya `/api/kubeconfigs` altina tasinir ya da `/configuration`'a redirect eder; tarayicida dogrudan ziyaret edildiginde ham JSON gorunmez.
- [ ] Highcharts (veya esdeger bir chart kutuphanesi) uygulama bundle'ina eklenir, workloads "Genel Bakis" pasta grafikleri calisir hale gelir; kutuphane bulunamazsa en azindan kullaniciya anlamli bir fallback mesaji gosterilir.
- [ ] Eksik `audit.empty_state`, `audit.filter_resource_type`, `audit.filter_action`, `audit.filter_all` anahtarlari `I18N` dict'ine (TR+EN) eklenir; audit-trail sayfasinda ham anahtar gorunmez.
- [ ] `config.html`'deki null-reference hatasi giderilir (ilgili null-guard eklenir); `privileged_containers.html:1516`'daki debug `console.log` kaldirilir.
- [ ] Degisiklik sonrasi 5 sayfa (access-control, storage, kubeconfigs, workloads, audit-trail) `console --errors` temiz, gorsel olarak dogru render ediyor.

---

## [Oncelik: Orta] 16. UI/UX: Bilgi Mimarisi, Navigasyon ve Mobil Responsive Duzeltmeler

**Kategori:** UI/UX
**Bulunma kaynagi:** Ayni UI/UX denetimi (2026-07-24), bkz. backlog #15.

**Mevcut durum:**
- **"Config" (`/config`) ve "Configuration" (`/configuration`) menu isimleri neredeyse ayni ama tamamen farkli isler yapiyor:** biri cluster kaynak konfigurasyonu (ConfigMaps/Secrets/ResourceQuota/HPA), digeri kubeconfig/cluster baglantisi yonetimi. Uygulamanin en onemli eylemi (cluster ekleme/degistirme) belirsiz bir isim altinda.
- **Top-bar sayfa basligi coğu sayfada sabit "Dashboard":** `base.html`'deki `{% block page_title %}` home, workloads, k8s-explorer, config, access-control, privileged-containers, vulnerabilities sayfalarinda override edilmemis (nodes, compliance, pss, trivy, audit-trail dogru override ediyor — tutarsizlik).
- **Sidebar daraltildiginda (collapsed) alt-menulere erisim yok:** `.sidebar.collapsed .dropdown-menu { display:none !important; }` — Guvenlik alt-menusundeki 9 sayfaya (mesh, vulns, exec, privileged, pss, cm-secrets, yaml, trivy, compliance) collapsed modda hic erisilemiyor, flyout/tooltip yok.
- **Mobilde (390px) gercek yatay tasma:** `/vulnerabilities` namespace filtre satiri sarmiyor, viewport'u ~51px asiyor, alt buton satiri kirpiliyor. `/compliance`'da uzun sayfa basligi top-bar'da 5 satira sariyor ve context badge'i basligin ustune biniyor. `/nodes`'ta kucuk (~5px) bir tasma var.
- **Top-bar mobilde sikisik:** hamburger + baslik + context badge + dil dropdown 390px'te sikisiyor, badge basliga yapisik duruyor.

**Sorun:** Kullanici uygulamada nerede oldugunu (page title tutarsizligi) her zaman anlayamiyor; en kritik islevlerden biri (cluster degistirme) belirsiz isimlendirme yuzunden bulunmasi zor; mobil/dar ekranda bazi sayfalar kullanilamaz hale geliyor (tasan/kirpilan elemanlar); daraltilmis sidebar guvenlik ozelliklerinin cogunu erisilemez kiliyor.

**Kabul kriterleri:**
- [ ] `/configuration` route'u ve sidebar etiketi daha net bir isme alinir (or. "Cluster/Kubeconfig Yonetimi"); `/config` "Kaynak Ayarlari" gibi ayristirilir. i18n anahtarlari (TR+EN) guncellenir.
- [ ] Tum sablomlarda `{% block page_title %}` override edilir (home, workloads, k8s-explorer, config, access-control, privileged-containers, vulnerabilities dahil); top-bar basligi her sayfada dogru sayfa adini gosterir.
- [ ] Sidebar collapsed modda Guvenlik alt-menusune hover flyout (veya esdeger) ile erisim saglanir; 9 alt-sayfanin tamami collapsed modda da ulasilabilir olur.
- [ ] `/vulnerabilities` namespace filtre satiri mobilde `flex-wrap` ile sarar, 390px'te yatay tasma olmaz (`scrollWidth <= innerWidth`).
- [ ] `/compliance` top-bar basligi mobilde `text-truncate` ile kisaltilir, context badge basliga binmez (`flex-shrink:0` + yeterli gap).
- [ ] `/nodes` mobil tasmasi giderilir.
- [ ] Top-bar mobil duzeni (hamburger/baslik/badge/dil) sikismadan render olur — badge gerekirse mobilde gizlenir veya alt satira alinir.

---

## [Oncelik: Orta] 17. UI/UX: Gorsel Tasarim Sistemi Tutarliligi

**Kategori:** UI/UX
**Bulunma kaynagi:** Ayni UI/UX denetimi (2026-07-24), bkz. backlog #15.

**Mevcut durum:**
- **Hero renk paleti sayfalar arasi tutarsiz:** workloads mor, config yesil, network mor, audit-trail teal, trivy/compliance/pss mavi — ortak bir aksan rengi/CSS degiskeni yok.
- **Ayni tip veri farkli layout paradigmalariyla sunuluyor:** `access_control.html` kart-grid kullaniyor, config/nodes/network tablo kullaniyor — tarama/karsilastirma zorlasiyor.
- **`privileged_containers.html`'deki "Asiri Yetkili RBAC Rolleri" tablosu koyu lacivert zeminde**, diger liste tablolariyla (acik zemin, sadece baslik koyu) tutarsiz; bos metrikte "-" gibi zayif gosterim var.
- **`storage.html`'de sayac/icerik celismesi:** PVCs sekmesi badge'i cluster geneli "13" gosteriyor ama varsayilan namespace filtresiyle liste "PVC bulunamadi" gosteriyor — kullanici kafasi karisiyor.
- **`common.js`'deki `timeAgo()` fonksiyonu Ingilizce sabit ek kullaniyor** (`'d ago'`, `'h ago'` vb.) — TR arayuzde bile "280d ago" gorunuyor (workloads sayfasi `t("cache.ago")` ile bunu dogru yapiyor, o kalip genellenmeli).
- **`mesh.html` topoloji gorsellestirmesi zayif olcekleniyor:** dugumler kucuk, alanin cogu bos, etiketler ust uste biniyor, fit-to-viewport yok.
- **`trivy_operator.html`'de bos tablo durumu belirsiz** (diger sayfalardaki inbox ikonlu bos-durum kalibi kullanilmiyor).
- **Kucuk yazim hatasi:** workloads.html'de "10 saniye once" -> "önce" olmali.

**Sorun:** Tutarsiz gorsel dil, uygulamanin "birden fazla donemde, ortak bir standart olmadan buyumus" izlenimini veriyor; kullanici her sayfada yeniden ogrenme maliyeti odüyor.

**Kabul kriterleri:**
- [ ] 1-2 birincil aksan rengi CSS degiskeni olarak tanimlanir, tum hero gradyanlari buna baglanir.
- [ ] Kaynak listeleme sayfalari (access-control dahil) tutarli bir liste paradigmasina (tercihen tablo) getirilir.
- [ ] Privileged sayfasindaki RBAC tablosu ortak tablo stiline uydurulur; bos metrikte "-" yerine "0" veya acikca "Veri yok" gosterilir.
- [ ] Storage sayfasinda sayac ile aktif filtre senkronize edilir veya bos durumda filtre ipucu gosterilir.
- [ ] `timeAgo()` fonksiyonu `window.i18n`/`t("cache.ago")` kalibina tasinir, tum kullanim noktalarinda lokalize sure ekleri gosterilir.
- [ ] Mesh gorsellestirmesinde fit-to-viewport ve etiket cakisma onleme uygulanir.
- [ ] Trivy Operator sayfasinda bos tablo icin acik bir bos-durum satiri eklenir (inbox ikonlu ortak kalip).
- [ ] "once" -> "önce" yazim hatasi duzeltilir.

---

## [Oncelik: Orta] 18. UI/UX: Erisilebilirlik (Accessibility) Iyilestirmeleri

**Kategori:** UI/UX / Erisilebilirlik
**Bulunma kaynagi:** Ayni UI/UX denetimi (2026-07-24), bkz. backlog #15.

**Mevcut durum:**
- Genel olarak ikon-only butonlarin cogunda `aria-label` yok (`config.html`'de ~6 ornek).
- Filtre `select`/arama `input` alanlarinin cogunda `<label for=...>` yok, yalnizca `placeholder`'a dayaniyor (config, vulnerabilities, workloads birkac istisna).
- Custom `.btn`/`.nav-link` bilesenlerinde `focus-visible` outline stili tanimli degil — klavye ile gezinen kullanicilar odagin nerede oldugunu goremiyor.

**Sorun:** Ekran okuyucu kullanan veya klavye ile gezinen kullanicilar icin uygulama buyuk olcude kullanilamaz durumda; bu hem WCAG uyumu hem de kurumsal musteriler icin (erisilebilirlik denetimi gerektiren) bir risktir.

**Kabul kriterleri:**
- [ ] Tum ikon-only butonlara aciklayici `aria-label` eklenir.
- [ ] Tum filtre/arama form kontrollerine gorunur veya `aria-label`/gizli `<label>` eklenir.
- [ ] Custom interaktif bilesenlere (`.btn`, `.nav-link`, tablo satir aksiyonlari) belirgin bir `focus-visible` outline stili eklenir.
- [ ] En az 3 farkli sayfada (workloads, config, access-control) yalnizca klavye (Tab/Enter) ile temel islemler (filtre degistirme, satir detay acma) gerceklestirilebilir oldugu dogrulanir.

---

## [Oncelik: Dusuk] 19. UI/UX: Karanlik Tema (Dark Mode) Destegi

**Kategori:** UI/UX
**Bulunma kaynagi:** Ayni UI/UX denetimi (2026-07-24), bkz. backlog #15.

**Mevcut durum:**
- `base.html:2` `data-bs-theme="light"` sabit; hicbir tema toggle mekanizmasi yok (`theme.toggle` i18n anahtari mevcut ama kullanan bir UI elemani bulunamadi/calismiyor).
- Bootstrap 5.3 zaten `color-mode` (dark/light) destekliyor, custom CSS degiskenleri (`--dark-color` vb.) dark mod icin gozden gecirilmemis.

**Sorun:** DevOps/platform araclarinda karanlik tema guclu bir kullanici beklentisidir (genelde terminal/IDE ile birlikte, uzun sureli ekran kullanimi); hic sunulmuyor olmasi rakip araclara kiyasla eksiklik.

**Kabul kriterleri:**
- [ ] Top-bar'a bir tema toggle butonu eklenir (`theme.toggle` i18n anahtari kullanilarak), `data-bs-theme` degeri `localStorage`'da tutulur ve sayfa yenilemede korunur.
- [ ] Custom CSS degiskenleri (renkler, kart/tablo zeminleri) dark mod icin gozden gecirilir; en az 5 temsili sayfada (home, workloads, compliance, nodes, access-control) dark modda okunabilirlik/kontrast dogrulanir.
- [ ] Toggle her iki dilde de (TR/EN) dogru etiketlenir.

---

## [Oncelik: Dusuk] 20. UI/UX: DevOps Kullanilabilirlik Ozellikleri (Global Arama, Namespace Baglami, Kisayollar)

**Kategori:** UI/UX / Ozellik
**Bulunma kaynagi:** Ayni UI/UX denetimi (2026-07-24), bkz. backlog #15.

**Mevcut durum:**
- Global arama yok — kullanici bir kaynagi bulmak icin dogru sayfaya gidip sayfa-ici filtre kullanmak zorunda.
- Breadcrumb yok.
- Klavye kisayolu yok.
- Tablolarda coklu-secim/toplu islem yok.
- Namespace secimi her sayfada ayri ayri tutuluyor — global/paylasimli bir namespace context'i yok (kullanici her sayfaya gecince namespace'i yeniden seciyor).

**Sorun:** Bu kalip eksiklikleri, deneyimli DevOps kullanicilarinin gunluk kullanimda verimliligini dusuruyor; benzer araclarda (Lens, K9s, Rancher) bu ozellikler standart kabul edilir.

**Kabul kriterleri:**
- [ ] (Faz 1) Global bir namespace secici eklenir (top-bar'da), secim `sessionStorage`/URL query param ile sayfalar arasi korunur.
- [ ] (Faz 2) Global kaynak arama eklenir (en azindan isim bazli, mevcut liste endpoint'lerini kullanarak).
- [ ] (Gelecek donem, opsiyonel) Breadcrumb, klavye kisayollari, tablo coklu-secim/toplu islem — ayri alt-maddeler olarak degerlendirilebilir, bu maddenin ilk surumu kapsam disi.

**Not:** Bu madde diger UI/UX maddelerine (#15-18) kiyasla daha buyuk bir ozellik calismasidir; ayri bir spec/tasarim onerisi gerektirir, oncelik dusuk.

---

## [Oncelik: Kritik] 21. Guvenlik: Kimlik Dogrulama Katmani ve Ag Erisim Kontrolu Eksikligi

**Kategori:** Guvenlik (A01:2021 Broken Access Control / A07 Identification & Authentication Failures)
**Bulunma kaynagi:** `security-engineer` agent tarafindan yapilan kapsamli statik guvenlik denetimi (2026-07-24), OWASP Top 10 cercevesinde ~25 Python dosyasi ve 100+ route tarandi.

**Mevcut durum:**
- Kod tabaninda hicbir login, API key, token veya `before_request` auth kontrolu yok (grep ile dogrulandi).
- Paketlenmis masaustu uygulamasi (`launcher.py`) `127.0.0.1`'e bind ediyor (guvenli), ANCAK `make run` / `python src/main.py` / Docker yolu (`src/main.py:5`, `host="0.0.0.0"`) tum ag arayuzlerine bind ediyor.
- Uygulama kubeconfig'in tum RBAC yetkileriyle calisiyor (genelde cluster-admin'e yakin).

**Sorun:** Aym agdaki (ofis Wi-Fi, paylasilan VPN) kimlik dogrulamasi olmayan herhangi biri, `0.0.0.0` modunda calisan bir Kube-Sec ornegine tarayicidan erisip: tum Secret'lari okuyabilir (`/k8s-explorer/secret`, base64 degerleri doner), pod silebilir, node drain edebilir, Secret guncelleyebilir, ClusterRoleBinding silebilir — hepsi tek istekle, geri donusu olmadan. Bu, uygulamanin en kritik bulgusu.

**Kabul kriterleri:**
- [ ] `src/main.py`'nin varsayilan bind adresi `127.0.0.1` olarak degistirilir; `0.0.0.0` (ag disina acilma) yalnizca bilincli bir env var (or. `KUBESEC_ALLOW_NETWORK_BIND=1`) ile mumkun olur.
- [ ] Ag disina acik modda (bilincli opt-in ile) calistirildiginda EN AZINDAN basit bir zorunlu erisim katmani (yerel PIN/parola veya token — `before_request` hook'u ile) eklenir; auth'suz istekler 401 doner.
- [ ] Docker imaji (deprecated olsa da hala repoda) ayni varsayilan `127.0.0.1`/auth gereksinimini yansitir veya acikca "sadece guvenilir/izole ag icin" diye README/CLAUDE.md'de belgelenir.
- [ ] Degisiklik sonrasi `make run` varsayilan olarak yalnizca localhost'tan erisilebilir; masaustu (frozen) davranisi (zaten 127.0.0.1) bozulmaz.

---

## [Oncelik: Yuksek] 22. Guvenlik: Sabit SECRET_KEY (CSRF'i Etkisiz Kiliyor) ve Cookie Guvenlik Bayraklari

**Kategori:** Guvenlik (A02:2021 Cryptographic Failures)
**Bulunma kaynagi:** Ayni guvenlik denetimi (2026-07-24), bkz. backlog #21.

**Mevcut durum:**
- `src/web/app.py:47-48`: frozen olmayan (yani `make run` / Docker / plain Flask) yolda `app.secret_key = 'dev-secret-do-not-use-in-production'` — kaynak kodda sabit deger. Masaustu (frozen) yol `~/.kubesec/secret_key`'te rastgele uretilip `chmod 600` yapiyor (bu kisim saglam).
- `SESSION_COOKIE_SAMESITE` ve `SESSION_COOKIE_SECURE` hic set edilmemis (Flask varsayilani `HTTPONLY=True` iyi durumda, ama `SAMESITE` set degil).

**Sorun:** Secret key kaynak kodda herkese acik oldugundan, ag'a acik `make run`/Docker dagitiminda saldirgan hem `session` cookie'lerini forge edebilir hem de **backlog #6'da eklenen CSRF korumasini tumuyle atlatabilir** (Flask-WTF CSRF token'i `secret_key`'ten turetilir). Yani mevcut CSRF korumasi bu dagitim modunda fiilen calismiyor.

**Kabul kriterleri:**
- [ ] Non-frozen yolda sabit `secret_key` kaldirilir; her baslatmada `secrets.token_hex(32)` ile rastgele uretilir VEYA `APP_SECRET_KEY` env var'i zorunlu kilinir (yoksa uygulama acik bir hata ile baslamayi reddeder). Sabit dev anahtari yalnizca `FLASK_ENV=development` altinda kullanilabilir.
- [ ] `SESSION_COOKIE_SAMESITE='Lax'` acikca set edilir; HTTPS destegi eklenirse `SESSION_COOKIE_SECURE=True` de eklenir.
- [ ] Degisiklik sonrasi CSRF korumasi (backlog #6, `tests/test_csrf.py`) hala calisir; session tabanli ozellikler (kubeconfig aktivasyonu vb.) bozulmaz.

---

## [Oncelik: Yuksek] 23. Guvenlik: Kubeconfig Dosya Islemlerinde Path Traversal ve Izin Sorunlari

**Kategori:** Guvenlik (A01/A03:2021 — Path Traversal, Hassas Veri Ifsasi)
**Bulunma kaynagi:** Ayni guvenlik denetimi (2026-07-24), bkz. backlog #21.

**Mevcut durum:**
- `src/web/blueprints/kubeconfigs.py:175-177` (DELETE route): JSON'dan alinan `name` parametresi hic sanitize edilmeden `os.path.join(KUBECONFIG_UPLOAD_DIR, name)` -> `os.remove(path)`'e geciyor. Karsilastirma: `kubeconfigs_add` (satir 58) `safe_name` filtresiyle `/` karakterini engelliyor ama DELETE'te bu filtre yok.
- `kubeconfigs.py:60-61` ve `kubeconfig_manager.py:16-17`: kubeconfig dosyalari (cluster kimlik bilgileri icerir) `open(path, 'w')` ile varsayilan umask'la (tipik `0644`, dunya-okunabilir) yaziliyor; yukleme dizini de varsayilan izinlerle olusturuluyor. `secret_key` gibi hassas dosyalar `chmod 600` alirken kubeconfig'ler almiyor.

**Sorun:** `name = "../../../../etc/..."` gibi bir degerle disk uzerinde keyfi dosyalar silinebilir (backlog #21'deki auth eksikligiyle birlesince ag'daki bir saldirgan bunu tetikleyebilir). Ayrica coklu-kullanicili bir makinede diger yerel kullanicilar kubeconfig dosyalarini okuyup cluster kimlik bilgilerini ele gecirebilir.

**Kabul kriterleri:**
- [ ] DELETE route'unda `add` ile ayni `safe_name` filtresi uygulanir; ek olarak `os.path.realpath(path)` sonucunun `KUBECONFIG_UPLOAD_DIR` altinda kaldigi (`os.path.commonpath` ile) dogrulanir.
- [ ] Kubeconfig dosyalari yazildiktan hemen sonra `os.chmod(path, 0o600)` uygulanir; yukleme dizini `os.makedirs(..., mode=0o700)` ile olusturulur.
- [ ] Gecerli bir kubeconfig adiyla silme islemi hala calisir (regresyon yok); `../` iceren bir `name` denemesi HTTP 400 ile reddedilir.

---

## [Oncelik: Orta] 24. Guvenlik: SSRF — Prometheus Proxy Endpoint'i Dogrulanmamis URL Kabul Ediyor

**Kategori:** Guvenlik (A10:2021 Server-Side Request Forgery)
**Bulunma kaynagi:** Ayni guvenlik denetimi (2026-07-24), bkz. backlog #21.

**Mevcut durum:**
- `src/web/blueprints/explorer/pods.py:57,143` (ve benzer desen 320,329 / 578,599): `manual_url = request.args.get('prometheus')` ile kullanici kontrolundeki host, dogrulama/whitelist olmadan `requests.get(f"{manual_url.rstrip('/')}/api/v1/{api_path}", ..., verify=False)`'e geciyor; yanit govdesi (`r.json()`) cagirana geri donuyor.

**Sorun:** Saldirgan `?prometheus=http://10.0.0.5:6379` gibi bir degerle sunucuyu ic agdaki keyfi host:port'lara istek yapmaya zorlayabilir (port tarama, ic HTTP servislerine erisim, veri sizdirma). `verify=False` ek olarak TLS dogrulamasini kapatiyor.

**Kabul kriterleri:**
- [ ] `prometheus` query param'i bir allowlist'e/sema-host dogrulamasina tabi tutulur; mumkunse yalnizca env `PROMETHEUS_URL`'e izin verilir, kullanici query param override'i kaldirilir veya sadece bilinen/kayitli Prometheus instance'larina kisitlanir.
- [ ] Loopback (127.0.0.0/8), link-local (169.254.0.0/16) ve ozel IP araliklari (RFC1918) icin URL reddedilir (kullanici bunu bilerek kendi Prometheus'una izin vermek isterse ayri bir mekanizma dusunulebilir).
- [ ] Degisiklik sonrasi gecerli/beklenen Prometheus URL'leriyle pod-metrics ozelligi calismaya devam eder.

---

## [Oncelik: Orta] 25. Guvenlik: HTTP Guvenlik Basliklari Eksik ve Hassas Veri Ifsasi (Secret Endpoint'i, Hata Mesajlari)

**Kategori:** Guvenlik (A05:2021 Security Misconfiguration / A02 Hassas Veri Ifsasi)
**Bulunma kaynagi:** Ayni guvenlik denetimi (2026-07-24), bkz. backlog #21.

**Mevcut durum:**
- `src/web/app.py`: CSP, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, HSTS basliklarinin hicbiri set edilmiyor (`after_request` hook'u yok).
- `src/web/blueprints/explorer/config.py:183-186`: `/k8s-explorer/secret` route'u, `read_namespaced_secret` sonucunun TUM `data` alanini (base64 — trivially decode edilebilir) tarayiciya donduruyor.
- Cok sayida route'ta (`config.py:192`, `scanning.py:291,430,578` vb.) `jsonify({'error': str(e)})` seklinde ham `str(e)`/K8s `ApiException.body` istemciye donuyor — ic host/namespace/dosya yolu ipuclari icerebilir.

**Sorun:** Guvenlik basliklarinin yoklugu clickjacking riski yaratir (panel destructive islemler icerdiginden ozellikle riskli — gorunmez iframe ile "drain" tiklatma). Secret degerlerinin acikca donmesi, auth eksikligiyle (backlog #21) birlesince kritik bir veri ifsasi riskidir. Hata mesajlarindaki ic detaylar kesif (reconnaissance) icin kullanilabilir.

**Kabul kriterleri:**
- [ ] Bir `after_request` hook'u ile en azindan `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff` ve makul bir CSP eklenir.
- [ ] `/k8s-explorer/secret` route'u degerleri varsayilan olarak maskeler; acik bir "goster" talebi (ayri bir parametre/onay) olmadan ham deger donmez. (Bu madde backlog #21'deki auth katmaniyla birlikte degerlendirilebilir — auth eklenirse bu route'un o katmanin arkasina alinmasi da bu maddenin bir parcasidir.)
- [ ] Kullaniciya donen hata mesajlari genellestirilir (`str(e)` yerine sabit/genel bir mesaj); ayrintili hata yalnizca sunucu logunda kalir.
- [ ] Degisiklik sonrasi mevcut Secret editor islevi (dogru yetkiyle) calismaya devam eder; hata donduren route'lar hala anlamli (ama genel) bir mesaj verir.

---

## [Oncelik: Orta] 26. Guvenlik: Yikici Kubernetes Islemleri icin Sunucu Tarafi Onay Mekanizmasi Yok

**Kategori:** Guvenlik / Tasarim (A04:2021 Insecure Design)
**Bulunma kaynagi:** Ayni guvenlik denetimi (2026-07-24), bkz. backlog #21.

**Mevcut durum:**
- Node drain (`cluster.py:96`), generic kaynak silme (`core.py:441-478`), Secret silme (`config.py:244`), scaling islemleri (`scaling.py:136,306`) gibi geri donusu olmayan islemler yalnizca POST alir almaz yuruyor; sunucu tarafinda ikinci bir onay/token (or. kaynak adinin yeniden yazilmasi, `confirm=true` gibi) yok. Onay yalnizca istemci JS'ine (bir tarayici dialog'u) bagli.

**Sorun:** Yanlis cluster context'inde (bkz. CLAUDE.md'deki coklu-sekme global kubeconfig sinirlamasi) yanlislikla production'da node drain'e tiklamak cok kolay; auth yoksa (backlog #21) kotu niyetli tetikleme de trivial hale gelir (istemci tarafi confirm dialog'u atlanabilir, dogrudan API cagrisi yapilabilir).

**Kabul kriterleri:**
- [ ] En az node-drain ve generic delete route'lari icin sunucu tarafi bir onay parametresi eklenir (or. istegin body'sinde kaynak adinin tekrar gonderilmesi zorunlu kilinir, sadece istemci dialog'una guvenilmez).
- [ ] "Production" olarak isaretlenmis/adlandirilmis context'lerde (kullanici tanimli veya isim deseni ile, or. context adinda "prod" gecen) ek bir uyari/onay adimi degerlendirilir (opsiyonel, nice-to-have).
- [ ] Degisiklik sonrasi mevcut UI akisi (tek tiklamalik onay dialog'u) dogru parametreyi gonderdigi surece calismaya devam eder; API'yi dogrudan cagiranlar icin (onay parametresi olmadan) 400 doner.

---

## [Oncelik: Dusuk] 27. Guvenlik: Production Sertlestirme (WSGI Sunucusu, Bagimlilik Guncelleme, Deprecated Dockerfile, Audit Log)

**Kategori:** Guvenlik / Teknik Borc
**Bulunma kaynagi:** Ayni guvenlik denetimi (2026-07-24), bkz. backlog #21.

**Mevcut durum:**
- `launcher.py:52,165,170` ve `src/main.py:5`: hem masaustu paket hem de `make run`, uretim icin guvenli/saglam olmayan Werkzeug gelistirme sunucusunu kullaniyor.
- `requirements.txt`: `pytest==6.2.5` (yalnizca test), `Flask>=2.2,<3.0` (kurulu 2.3.3), `Werkzeug<3.0`, `flask-cors` pin'siz, `urllib3 1.26.20` — surumler yaslaniyor, `<3.0` kisiti guvenlik yamalarini engelleyebilir.
- `Dockerfile`: "deprecated" yorumu olsa da hala repoda duruyor; `python src/main.py` calistiriyor (-> 0.0.0.0 + backlog #22'deki sabit secret key sorunlarini tetikler), `python:3.9-slim` tabani EOL'e yaklasiyor.
- `audit_log.py`: `session_id` yalnizca session cookie hash'inin ilk 8 karakteri (auth olmadigindan gercek kullanici kimligi degil); loglar yalnizca yerel `~/.kube-sec/audit.jsonl`'de tutuluyor, harici SIEM'e gonderilmiyor, dosya izinleri chmod'lanmamis.

**Sorun:** Bunlarin hicbiri tek basina kritik degil ama toplu olarak "production-ready" olgunlugunu dusuruyor; ozellikle Dockerfile'in silinmeyip zayif varsayilanlarla durmasi, birinin onu kopyalayip kullanmasi durumunda backlog #21/#22'deki sorunlari yeniden tetikler.

**Kabul kriterleri:**
- [ ] Ag'a acik dagitim (Docker/`make run`, 0.0.0.0 opt-in) destekleniyorsa Werkzeug yerine `waitress` veya `gunicorn` gibi bir WSGI sunucusuna gecilir.
- [ ] `Flask`/`Werkzeug` 3.x'e tasima degerlendirilir; `flask-cors` pinlenir; CI'ya (backlog #2) periyodik bir bagimlilik/guvenlik taramasi (`pip-audit` gibi) eklenmesi degerlendirilir.
- [ ] Deprecated `Dockerfile` ya tamamen kaldirilir ya da guvenli varsayilanlarla (127.0.0.1, zorunlu `APP_SECRET_KEY`, non-root user, WSGI sunucusu, guncel Python) yeniden yazilir.
- [ ] `audit_log.py` dosyasina yaziminda `chmod 600` uygulanir; auth eklendiginde (backlog #21) gercek aktor kimligi audit kayitlarina yansitilir.
