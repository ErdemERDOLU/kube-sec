# Kube-Sec — Geliştirici Katkı Rehberi

Bu belge, Kube-Sec projesine katkıda bulunmak isteyen geliştiriciler için yol haritası sunar.
Okuyucunun Python ve Flask konusunda deneyimli olduğu, ancak bu kod tabanına yeni olduğu varsayılır.

---

## İçindekiler

1. [Genel Bakış](#genel-bakis)
2. [Blueprint Yapısı ve Sorumluluk Alanları](#blueprint-yapisi)
3. [Yeni Route/Endpoint Ekleme Kalıbı](#yeni-route-ekleme)
4. [i18n: Yeni Arayüz Metni Ekleme](#i18n)
5. [Arka Plan Cache Thread'leri](#cache-threadleri)
6. [Testler](#testler)

---

## Genel Bakış

Kube-Sec, tek bir Flask uygulamasıdır. Giriş noktası `src/web/app.py` dosyasıdır; tüm blueprint
kayıtları, CSRF kurulumu, i18n context processor ve arka plan thread başlatıcıları bu dosyada
yer alır. Blueprint paketleri `src/web/blueprints/` altında gruplandırılmıştır.

Import zinciri (bağımlılık yönü):

```
kubeconfig_manager.py  <-  background.py  <-  blueprint'ler  <-  app.py
```

`kubeconfig_manager.py` ve `background.py` Flask'a bağımlı değildir; arka plan thread'lerinden
güvenle çağrılabilirler.

---

## Blueprint Yapısı

### 1. `kubeconfigs` Blueprint

| Özellik | Değer |
|---------|-------|
| Kayıt dosyası | `src/web/blueprints/kubeconfigs.py:30` |
| Alt-modüller | (tek dosya) |
| Sorumluluk | Kubeconfig dosyalarını listeleme, ekleme ve silme; aktif cluster'ı değiştirme (`/kubeconfigs/activate`); değişim sonrası cache'leri proaktif olarak geçersiz kılma. |
| Kayıt noktası | `src/web/app.py:164` |

Kubeconfig değiştirildiğinde `kubeconfigs_activate()` (satır 76) çağrılır. Bu fonksiyon aktif
kubeconfig'i global değişkene yazar, ardından tüm cache'leri yeni cluster verisiyle tazeler.

### 2. `workloads` Blueprint

| Özellik | Değer |
|---------|-------|
| Kayıt dosyası | `src/web/blueprints/workloads.py:21` |
| Alt-modüller | (tek dosya) |
| Sorumluluk | Kullanıcı arayüzü sayfa route'ları: `/workloads`, `/config`, `/network`, `/storage`, `/nodes`, `/access-control`, `/configuration`, `/mesh`. Çoğu route yalnızca `render_template` döner; `/mesh-data` gerçek küme verisi dönen JSON endpoint'idir. |
| Kayıt noktası | `src/web/app.py:168` |

### 3. `security` Blueprint

| Özellik | Değer |
|---------|-------|
| Kayıt dosyası | `src/web/blueprints/security/__init__.py:3` |
| Alt-modüller | `scanning.py`, `analysis.py`, `compliance.py`, `_vuln_checks.py` |
| Sorumluluk | Güvenlik kontrol ve raporlama sayfaları ile API endpoint'leri. |
| Kayıt noktası | `src/web/app.py:172` |

Alt-modüllerin görevleri:

- `scanning.py` — Trivy Operator kurulum/sorgulama, zafiyet raporları (`/trivy-operator*`,
  `/vulnerabilities`), PSS (`/pod-security-standards`), NetworkPolicy kapsam analizi
  (`/network-policy-coverage`).
- `analysis.py` — YAML linter (`/yaml-linter`, `/yaml-lint-api`), ConfigMap/Secret gizli veri
  tespiti (`/configmap-secrets*`), RBAC risk analizi (`/rbac-risky-roles`), ayrıcalıklı container
  (`/privileged-containers*`), exec olayları (`/exec-events*`).
- `compliance.py` — CIS Kubernetes Benchmark uyumluluk raporu (`/cis-benchmark`).
- `_vuln_checks.py` — Yardımcı fonksiyonlar; doğrudan route içermez, `scanning.py` tarafından
  kullanılır.

### 4. `explorer` Blueprint

| Özellik | Değer |
|---------|-------|
| Kayıt dosyası | `src/web/blueprints/explorer/__init__.py:3` |
| Alt-modüller | `core.py`, `pods.py`, `controllers.py`, `network.py`, `storage.py`, `config.py`, `cluster.py`, `scaling.py`, `_pagination.py` |
| Sorumluluk | Tüm `/k8s-explorer/*` ve `/api/k8s/*` route'ları: küme kaynaklarını listeleme, detay görüntüleme, düzenleme ve silme. |
| Kayıt noktası | `src/web/app.py:176` |

`_pagination.py` yardımcı modüldür; doğrudan route içermez.

### Blueprint Kayıt Zinciri

`app.py` içinde tüm blueprint'ler şu sırayla kayıt edilir:

```python
# src/web/app.py:162-176
app.register_blueprint(bp_kubeconfigs)  # 164
app.register_blueprint(bp_workloads)    # 168
app.register_blueprint(bp_security)     # 172
app.register_blueprint(bp_explorer)     # 176
```

`security` ve `explorer` blueprint'leri paket (`__init__.py`) yapısındadır. `__init__.py` Blueprint
nesnesini oluşturur, ardından alt-modülleri import ederek route dekoratörlerinin tetiklenmesini
sağlar:

```python
# src/web/blueprints/security/__init__.py:1-8
from flask import Blueprint
bp_security = Blueprint('security', __name__)
from web.blueprints.security import scanning   # noqa
from web.blueprints.security import analysis   # noqa
from web.blueprints.security import compliance # noqa
```

---

## Yeni Route/Endpoint Ekleme Kalıbı

Yeni bir route eklerken aşağıdaki standart adım sırasını uygula.

### Adım 1 — Aktif kubeconfig'i yükle

Her route handler'ının başında `configure_kube_client()` çağrısı yapılmalıdır. Bu fonksiyon
aktif kubeconfig'i session -> global değişken -> ortam değişkeni öncelik sırasıyla çözer ve
Kubernetes client konfigürasyonunu günceller. Kalıcı/paylaşılan bir `ApiClient` tutma — istek
başına yeniden yükleme bu kod tabanının tasarım kararıdır.

```python
# src/web/kubeconfig_manager.py:108
from web.kubeconfig_manager import configure_kube_client

configure_kube_client()
```

### Adım 2 — Kubernetes API çağrısıyla iş mantığı

`configure_kube_client()` sonrasında standart `kubernetes.client.*Api()` nesneleri oluşturulabilir:

```python
from kubernetes import client

apps_v1 = client.AppsV1Api()
result = apps_v1.patch_namespaced_deployment(name, namespace, patch)
```

### Adım 3 — Mutasyon route'larında `record_audit_event(...)` çağrısı

Veri değiştiren (POST/PATCH/DELETE) her route; işlem başarıyla tamamlandıktan sonra
`record_audit_event(...)` çağırmalıdır. Salt okunur (GET) route'lar bu çağrıyı yapmaz.

```python
# src/web/audit_log.py:161
from web.audit_log import record_audit_event, _short_session_id

record_audit_event(
    action='restart',           # 'update', 'delete', 'scale', 'restart', vb.
    resource_type='Deployment',
    resource_name=name,
    namespace=namespace,
    session_id=_short_session_id(request.cookies.get('session')),
)
```

### Adım 4 — `session_id` elde et

`_short_session_id` fonksiyonu (`src/web/audit_log.py:66`) Flask session cookie'sinin ham değerinden
8 karakterlik kısa bir kimlik üretir. Flask'a bağımlı değildir; parametre olarak ham cookie değeri
alır:

```python
session_id = _short_session_id(request.cookies.get('session'))
```

### Adım 5 — Yanıt döndür

Sayfa route'ları `render_template(...)`, JSON endpoint'leri `jsonify(...)` döndürür. Hata
durumunda HTTP durum kodu eklenir:

```python
return jsonify({'ok': True})
# veya
return jsonify({'error': str(e)}), 500
```

### Tam Örnek — `restart_deployment` route'u

Aşağıdaki örnek yukarıdaki tüm adımları tek bir route içinde göstermektedir:

```python
# src/web/blueprints/explorer/controllers.py:185-227

@bp_explorer.route('/k8s-explorer/restart-deployment', methods=['POST'])
def restart_deployment():
    try:
        data = request.get_json(force=True)
        namespace = data.get('namespace')
        name = data.get('name')
        if not namespace or not name:
            return jsonify({'error': 'namespace ve name zorunlu'}), 400

        # Adım 1: Aktif kubeconfig'i yükle
        configure_kube_client()

        # Adım 2: Kubernetes API çağrısı
        apps_v1 = client.AppsV1Api()
        now = datetime.utcnow().isoformat() + 'Z'
        patch = {"spec": {"template": {"metadata": {"annotations":
                    {"kubectl.kubernetes.io/restartedAt": now}}}}}
        apps_v1.patch_namespaced_deployment(name, namespace, patch)

        # Adım 3 & 4: Audit log kaydı
        record_audit_event(
            action='restart',
            resource_type='Deployment',
            resource_name=name,
            namespace=namespace,
            session_id=_short_session_id(request.cookies.get('session')),
        )

        # Adım 5: Yanıt
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
```

### CSRF Koruması

`CSRFProtect(app)` (`src/web/app.py:65`) tüm POST/PUT/PATCH/DELETE isteklerini global olarak
korur; route bazında ek dekoratör gerekmez. Frontend, mutasyon isteklerinde
`X-CSRFToken` header'ını göndermek zorundadır. Token değeri `/` veya herhangi bir sayfa isteğinin
yanıtındaki `<meta name="csrf-token">` etiketinden okunur.

---

## i18n: Yeni Arayüz Metni Ekleme

Kube-Sec, dict tabanlı basit bir i18n altyapısı kullanır. Şablonlara sabit metin yazma — bunun
yerine her yeni metin için `I18N` dict'ine anahtar ekle.

### Adım 1 — `I18N` dict'ine anahtar ekle

`src/web/i18n.py` dosyasının başındaki `I18N` dict'ine (satır 8) yeni anahtarı ekle.
Anahtar formatı `bolum.alt_bolum.aciklama` şeklindedir:

```python
# src/web/i18n.py:8
I18N = {
    # ... mevcut anahtarlar ...
    'myfeature.button.save': {'tr': 'Kaydet', 'en': 'Save'},
    'myfeature.label.count': {'tr': 'Toplam kayıt', 'en': 'Total records'},
}
```

### Adım 2 — Template içinde `t()` ile kullan

`inject_i18n` context processor (`src/web/app.py:105`) her template render'ında `t`, `current_locale`
ve `i18n_json` değişkenlerini otomatik olarak enjekte eder:

```html
<button>{{ t('myfeature.button.save') }}</button>
<span>{{ t('myfeature.label.count') }}: {{ count }}</span>
```

### Adım 3 — JS tarafında `i18n_json` ile eriş

Template içindeki JavaScript, `i18n_json` nesnesini kullanabilir:

```html
<script>
  const i18n = {{ i18n_json | tojson }};
  const lang = '{{ current_locale }}';
  const label = (i18n['myfeature.label.count'] || {})[lang] || 'myfeature.label.count';
</script>
```

### Dil değiştirme

Kullanıcı dili `/set-locale?lang=tr` veya `/set-locale?lang=en` isteğiyle değiştirilir
(`src/web/app.py:211`). Seçilen dil `lang` adlı cookie'ye yazılır; sonraki tüm sayfa render'larında
bu cookie okunur (varsayılan `tr`).

### `translate()` fonksiyonunun fallback davranışı

`translate(key, lang)` (`src/web/i18n.py:1138`) şu öncelik sırasıyla çalışır:

1. `I18N[key][lang]` — istenen dilde değer.
2. `I18N[key]['tr']` — Türkçe fallback.
3. `key` string'inin kendisi — anahtar dict'te yoksa veya değer boşsa.

Bu sayede eksik bir anahtar UI'da hata vermez; key string'i görünür, bu da eksik çeviriyi
tespit etmeyi kolaylaştırır.

---

## Arka Plan Cache Thread'leri

Maliyetli Kubernetes API sorguları, her istekte tekrar çalıştırılmak yerine arka plan thread'leriyle
periyodik olarak örneklenir ve modül seviyesi dict'lerde saklanır. Route handler'ları bu dict'leri
okur.

### Mevcut Cache'ler

| Cache | TTL | `update_` fonksiyonu | Refresher | `start_` fonksiyonu | Kaynak |
|-------|-----|---------------------|-----------|---------------------|--------|
| Workload Stats | 20 sn | `update_workload_stats_cache` | `workload_stats_cache_refresher` | `start_workload_stats_cache` | `src/web/background.py:86` |
| Pods Summary | 180 sn | `update_pods_summary_cache` | `pods_summary_cache_refresher` | `start_pods_summary_cache` | `src/web/background.py:247` |
| Metrics Sampler | ~10 sn* | — | `_metrics_sampler_loop` | `start_metrics_sampler` | `src/web/background.py:364` |
| PSS | 30 sn | `update_pss_cache` | `pss_cache_refresher` | `start_pss_cache` | `src/web/background.py:550` |
| NetworkPolicy Coverage | 30 sn | `update_netpol_coverage_cache` | `netpol_coverage_cache_refresher` | `start_netpol_coverage_cache` | `src/web/background.py:762` |

*Metrics Sampler TTL'i `METRICS_TS_INTERVAL_SEC` ortam değişkeniyle kontrol edilir (varsayılan 10
saniye).

Tüm `start_*` fonksiyonları `src/web/app.py:255-259` satırlarında, tüm import'lar ve blueprint
kayıtları tamamlandıktan sonra çağrılır.

### Backoff Mekanizması

Bir cache yenilenirken Kubernetes API'ye erişilemezse, refresher hemen yeniden denemek yerine
exponential backoff ile bekler. Bu süreyi kontrol eden ortam değişkenleri (`src/web/background.py:45-47`):

| Ortam Değişkeni | Varsayılan | Açıklama |
|----------------|-----------|----------|
| `KUBESEC_BACKOFF_INITIAL` | 5 sn | İlk hata sonrası bekleme süresi |
| `KUBESEC_BACKOFF_MAX` | 300 sn | Maksimum bekleme süresi (5 dakika) |
| `KUBESEC_MAX_CONSECUTIVE_ERRORS` | 10 | Bu sayıda ardışık hata sonrası log throttling devreye girer |

Bekleme formülü: `min(KUBESEC_BACKOFF_INITIAL * 2^(n-1), KUBESEC_BACKOFF_MAX)` (n = ardışık hata sayısı).

### Yeni Cache Ekleme Kalıbı

`background.py` içinde tüm cache'ler aynı yapıyı izler. Yeni bir cache eklerken:

**1. Modül seviyesi değişkenleri tanımla:**

```python
# src/web/background.py
myresource_cache = None
myresource_cache_time = 0
MYRESOURCE_CACHE_TTL = 30  # saniye
_mrc_last_error = None
_mrc_consecutive_errors: int = 0
```

**2. `update_myresource_cache()` fonksiyonunu yaz:**

```python
def update_myresource_cache():
    global myresource_cache, myresource_cache_time, _mrc_last_error
    try:
        configure_kube_client()
        # ... Kubernetes API çağrıları ...
        myresource_cache = { ... }
        myresource_cache_time = time.time()
        _mrc_last_error = None
    except Exception as e:
        _mrc_last_error = str(e)
```

**3. `myresource_cache_refresher()` daemon döngüsünü yaz:**

```python
def myresource_cache_refresher():
    global _mrc_consecutive_errors
    while True:
        prev_error = _mrc_last_error
        update_myresource_cache()
        if _mrc_last_error is None:
            _mrc_consecutive_errors = 0
            time.sleep(MYRESOURCE_CACHE_TTL)
        else:
            _mrc_consecutive_errors += 1
            if _should_log(_mrc_consecutive_errors):
                print(f'MYRESOURCE CACHE: hata #{_mrc_consecutive_errors}: {_mrc_last_error}',
                      file=sys.stderr)
            time.sleep(compute_backoff_sleep(_mrc_consecutive_errors, MYRESOURCE_CACHE_TTL))
```

**4. `start_myresource_cache()` fonksiyonunu yaz:**

```python
def start_myresource_cache():
    t = threading.Thread(target=myresource_cache_refresher, daemon=True)
    t.start()
```

**5. `app.py`'de çağır:**

`src/web/app.py:255-259` bloğuna yeni `start_myresource_cache()` satırını ekle.

**6. `kubeconfigs_activate()` içinde geçersiz kıl:**

Aktif kubeconfig değiştiğinde yeni cache de tazele. `src/web/blueprints/kubeconfigs.py:76` içindeki
`kubeconfigs_activate()` fonksiyonundaki cache tazeleme bloğuna `update_myresource_cache()` çağrısı ekle.

> **Not:** Metrics Sampler diğer cache'lerden farklıdır; `update_` + `refresher` ikilisi yerine
> tek bir `_metrics_sampler_loop()` döngüsü kullanır. Yeni cache eklerken diğer dört cache'in
> kalıbını örnek al.

---

## Testler

Şu an bu projede otomatik test paketi bulunmamaktadır. `pytest` `requirements.txt` içinde
listelenmiş olsa da proje içinde henüz test dosyası yoktur ve `make test` hedefi tanımlı değildir.

### Manuel Doğrulama Önerileri

Yeni bir özellik veya düzeltme eklerken:

- Etkilenen route'ları tarayıcı üzerinden elle test et.
- Mutasyon işlemleri (POST/DELETE/PATCH) için CSRF token gönderimini doğrula
  (`X-CSRFToken` header'ı veya form alanı).
- Birden fazla namespace içeren bir cluster'a karşı test et; namespace filtresi olan endpoint'lerde
  filtrelemenin doğru çalıştığını kontrol et.
- Kubeconfig değiştirme sonrası cache'lerin yeni cluster verisini yansıtıp yansıtmadığını doğrula.
- `render_template` kullanan route'larda Jinja2 şablonunun hata vermeden render edildiğini kontrol et.
- Yeni i18n anahtarı eklendiyse hem `tr` hem `en` locale ile sayfayı aç; eksik çevirinin key
  string olarak göründüğünü doğrula.

### Test Altyapısı Katkısı

Otomatik test altyapısı oluşturmak istiyorsan Flask test client'ı üzerinden başlayabilirsin:

```python
import pytest
from web.app import app

@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as c:
        yield c
```

`make test` hedefinin eklenmesi `Makefile`'a `pytest src/` satırı eklenmesiyle sağlanabilir;
ancak bu değişiklik şu an kapsam dışıdır.

---

Daha fazla bilgi için [README.md](README.md) dosyasını veya `src/web/app.py` içindeki
kod yorumlarını incele.
