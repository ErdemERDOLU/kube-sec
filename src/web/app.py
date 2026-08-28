from flask import Flask, render_template, jsonify, request, redirect, send_from_directory, session, url_for
from flask_cors import CORS
from flask_wtf.csrf import CSRFProtect, CSRFError
from flasgger import Swagger
import sys, traceback, os, secrets
from pathlib import Path
from urllib.parse import urlencode, urlparse

CORS_ORIGINS = ["http://localhost:8080", "http://127.0.0.1:8080"]

# PyInstaller bundle içinde template/static yolları düzelt
if getattr(sys, 'frozen', False):  # bundle
    BASE_DIR = getattr(sys, '_MEIPASS', os.path.abspath(os.path.dirname(__file__)))  # type: ignore[attr-defined]
    # PyInstaller may place bundled data under different relative paths depending on how --add-data was given.
    # Check a few likely candidate locations and pick the first that exists.
    cand_templates = [
        os.path.join(BASE_DIR, 'web', 'templates'),
        os.path.join(BASE_DIR, 'templates'),
        os.path.join(BASE_DIR, 'src', 'web', 'templates'),
    ]
    cand_static = [
        os.path.join(BASE_DIR, 'web', 'static'),
        os.path.join(BASE_DIR, 'static'),
        os.path.join(BASE_DIR, 'src', 'web', 'static'),
    ]
    TEMPLATE_DIR = next((p for p in cand_templates if os.path.isdir(p)), cand_templates[0])
    STATIC_DIR = next((p for p in cand_static if os.path.isdir(p)), cand_static[0])
else:
    SRC_WEB_DIR = os.path.abspath(os.path.dirname(__file__))
    TEMPLATE_DIR = os.path.join(SRC_WEB_DIR, 'templates')
    STATIC_DIR = os.path.join(SRC_WEB_DIR, 'static')

app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR)
_env_secret = os.environ.get('APP_SECRET_KEY')
if _env_secret:
    app.secret_key = _env_secret
elif getattr(sys, 'frozen', False):
    _key_path = Path.home() / '.kubesec' / 'secret_key'
    if _key_path.exists():
        app.secret_key = _key_path.read_text().strip()
    else:
        _generated_key = secrets.token_hex(32)
        _key_path.parent.mkdir(parents=True, exist_ok=True)
        _key_path.write_text(_generated_key)
        _key_path.chmod(0o600)
        app.secret_key = _generated_key
    app.logger.warning("APP_SECRET_KEY not set; using key from ~/.kubesec/secret_key")
else:
    if os.environ.get('FLASK_ENV') == 'development':
        app.secret_key = 'dev-secret-do-not-use-in-production'
        app.logger.warning(
            "FLASK_ENV=development: sabit gelistirme anahtari kullaniliyor. "
            "Production icin APP_SECRET_KEY env var'ini set edin."
        )
    else:
        app.secret_key = secrets.token_hex(32)
        app.logger.warning(
            "APP_SECRET_KEY env var'i set edilmemis; rastgele anahtar uretildi. "
            "Oturumlar uygulama yeniden baslatildiginda gecersiz olacaktir. "
            "Kalici oturumlar icin APP_SECRET_KEY env var'ini set edin."
        )

# ---------------------------------------------------------------------------
# Cookie Guvenlik Bayraklari
# ---------------------------------------------------------------------------
# SESSION_COOKIE_HTTPONLY: JS'den cookie erisimini engeller (XSS korumasi).
# Flask varsayilani zaten True; acikca set edilerek kasitli oldugu belirtilir.
app.config['SESSION_COOKIE_HTTPONLY'] = True
# SESSION_COOKIE_SAMESITE: Cross-origin isteklerde cookie gonderimini kisitlar.
# 'Lax' = ayni site + top-level navigasyonlarda cookie gonderilir; CSRF riskini azaltir.
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
# SESSION_COOKIE_SECURE: Yalnizca HTTPS uzerinde cookie gonder.
# HTTP-only ortamda (varsayilan) True yapmak cookie'nin hic gonderilmemesine yol acar.
# KUBESEC_SECURE_COOKIES=1 ile HTTPS reverse proxy arkasindan calistirildiginda True yapilmali.
app.config['SESSION_COOKIE_SECURE'] = (
    os.environ.get('KUBESEC_SECURE_COOKIES', '').lower() in ('1', 'true', 'yes', 'on')
)

CORS(app, origins=CORS_ORIGINS, supports_credentials=True)

# ---------------------------------------------------------------------------
# Auth Katmani — Ag Erisim Kontrolu (Backlog #21)
# ---------------------------------------------------------------------------
# KUBESEC_ALLOW_NETWORK_BIND=1 ile ag modunda calistirildiysa, tum isteklerde
# (beyaz listedeki yollar haric) kimlik dogrulama zorunludur.
# Localhost modunda (env var yok/pasif): auth hook hicbir kontrol yapmaz.
# ---------------------------------------------------------------------------

_NETWORK_BIND_ACTIVE = os.environ.get('KUBESEC_ALLOW_NETWORK_BIND', '').lower() in ('1', 'true', 'yes', 'on')

if _NETWORK_BIND_ACTIVE:
    _env_password = os.environ.get('KUBESEC_ACCESS_PASSWORD')
    if _env_password:
        _ACCESS_TOKEN = _env_password
    else:
        _ACCESS_TOKEN = secrets.token_urlsafe(24)
        # NOT: token bilerek logging.warning() ile YAZDIRILMIYOR — logging handler'lari
        # (varsa) uzak log toplayicilara (Sentry, syslog vb.) yonlendirebilir. Yalnizca
        # stdout'a print edilir; bu, konsolu okuyan kisiyle sinirli kalir.
        print('=' * 60, flush=True)
        print(f"  Kube-Sec erisim token'i: {_ACCESS_TOKEN}", flush=True)
        print("  Bu token'i tarayicida login formuna girin.", flush=True)
        print(f"  Veya dogrudan erisin: http://<makine-ip>:8080/?token={_ACCESS_TOKEN}", flush=True)
        print("  (0.0.0.0 tum arayuzlere bind eder — tarayicida makinenizin gercek", flush=True)
        print("   ag IP'sini veya localhost:8080'i kullanin.)", flush=True)
        print('=' * 60, flush=True)
else:
    _ACCESS_TOKEN = None

# Auth beyaz listesi — bu yollara auth kontrolu uygulanmaz
_AUTH_WHITELIST_EXACT = {'/login', '/favicon.ico', '/k8s-explorer/app-health', '/set-locale'}


def _safe_next_url(candidate):
    """Open-redirect'i onlemek icin yalnizca site-ici (goreli) yollara izin verir.

    `next` parametresi kullanicidan geldigi icin dogrudan redirect'e verilemez —
    `https://evil.com` gibi mutlak bir URL geçilirse kullanici site disina yonlendirilebilir.
    """
    if not candidate:
        return '/'
    parsed = urlparse(candidate)
    if parsed.scheme or parsed.netloc:
        return '/'
    return candidate


def _kubesec_auth_check():
    """Auth before_request hook: yalnizca ag modunda (_NETWORK_BIND_ACTIVE=True) calisir.

    Beyaz listedeki yollar (login, static, favicon, app-health, set-locale) muaftir.
    URL ?token= query parametresiyle veya session cookie ile auth yapilabilir.
    HTML isteklerinde /login'e redirect, AJAX/JSON isteklerinde 401 JSON doner.
    """
    if not _NETWORK_BIND_ACTIVE:
        return  # localhost modunda auth yok — hicbir kontrol yapma

    path = request.path

    # Beyaz liste: /login, /static/*, /favicon.ico, /k8s-explorer/app-health, /set-locale
    if path in _AUTH_WHITELIST_EXACT or path.startswith('/static/'):
        return

    # URL ?token= parametresiyle auth
    token_param = request.args.get('token')
    if token_param and _ACCESS_TOKEN and secrets.compare_digest(token_param, _ACCESS_TOKEN):
        session.clear()
        session['_kubesec_authenticated'] = True
        # Token'i URL'den temizle (tarayici gecmisi/bookmark/log sizintisini onlemek icin)
        clean_qs = urlencode({k: v for k, v in request.args.items() if k != 'token'})
        clean_url = path + ('?' + clean_qs if clean_qs else '')
        return redirect(clean_url)

    # Session cookie ile auth
    if session.get('_kubesec_authenticated'):
        return

    # Auth gerekiyor — AJAX/JSON mi HTML mi?
    accept = request.headers.get('Accept', '')
    xhr = request.headers.get('X-Requested-With', '')
    is_json_request = 'application/json' in accept or xhr == 'XMLHttpRequest'
    if is_json_request:
        return jsonify({'error': 'Unauthorized', 'message': 'Kimlik dogrulama gerekiyor.'}), 401
    # Goreli yol kullan (request.url degil) — _safe_next_url mutlak URL'leri reddeder
    next_url = request.full_path if request.query_string else request.path
    return redirect(url_for('login', next=next_url))


# Auth hook'unu CSRF'den ONCE kaydet (R-3 — CSRF hatasi gelmeden once 401/redirect alsinlar)
app.before_request(_kubesec_auth_check)

# ---------------------------------------------------------------------------
# CSRF Koruması — Flask-WTF CSRFProtect (Backlog #6)
# ---------------------------------------------------------------------------
# CSRFProtect(app) çağrısı, @app.before_request hook'u aracılığıyla
# POST/PUT/PATCH/DELETE metodlarını uygulama genelinde (global) otomatik olarak
# korur. Route bazında tek tek decorator eklemek gerekmez.
#
# Kabul edilen header'lar (varsayılan): ['X-CSRFToken', 'X-CSRF-Token']
# Frontend'in göndereceği header: X-CSRFToken (spec sözleşmesi)
#
# WTF_CSRF_TIME_LIMIT = None: Masaüstü uygulama saatlerce açık kalabileceğinden
# token'ı session ömrü boyunca geçerli yapıyoruz (varsayılan 3600s yerine).
app.config['WTF_CSRF_TIME_LIMIT'] = None
app.config['WTF_CSRF_HEADERS'] = ['X-CSRFToken', 'X-CSRF-Token']
csrf = CSRFProtect(app)

swagger = Swagger(app, config={
    "headers": [],
    "specs": [
        {
            "endpoint": 'apispec_1',
            "route": '/apispec_1.json',
            "rule_filter": lambda rule: True,
            "model_filter": lambda tag: True,
        }
    ],
    "static_url_path": "/flasgger_static",
    "swagger_ui": True,
    "specs_route": "/apidocs/",
    "host": "127.0.0.1:8080",
    "schemes": ["http"]
})

# Suppress noisy InsecureRequestWarning globally (dev convenience; remove for prod hardening)
try:
    import urllib3
    from urllib3.exceptions import InsecureRequestWarning
    urllib3.disable_warnings(InsecureRequestWarning)
except Exception:
    pass

# Favicon route to avoid 404 spam in logs; serve from static if present else empty 204
@app.route('/favicon.ico')
def favicon():
    static_path = os.path.join(app.root_path, 'static')
    ico_path = os.path.join(static_path, 'favicon.ico')
    if os.path.exists(ico_path):
        return send_from_directory(static_path, 'favicon.ico', mimetype='image/vnd.microsoft.icon')
    return ('', 204)

# --- i18n — i18n.py'den import edildi ---
from web.i18n import I18N, translate
import web.kubeconfig_manager as _kcm

@app.context_processor
def inject_i18n():
    try:
        lang = request.cookies.get('lang') or 'tr'
    except Exception:
        lang = 'tr'
    # active_kubeconfig_name: her template render'ında aktif kubeconfig adını sağlar.
    # base.html'de {{ active_kubeconfig_name or t('base.context_none') }} ile kullanılır.
    # _kcm modül referansından okuma thread-safe'dir (CPython GIL; sadece okuma).
    active_kubeconfig_name = _kcm.KUBECONFIG_ACTIVE_GLOBAL
    return {
        't': lambda key: translate(key, lang),
        'current_locale': lang,
        'i18n_json': I18N,
        'active_kubeconfig_name': active_kubeconfig_name,
    }


# Guvenlik: Debug endpoint'ini yalnizca gelistirme ortaminda aktif et.
# Kosul: (1) PyInstaller frozen build DEGILSE *VE* (2) FLASK_ENV=development veya
# FLASK_DEBUG=1 ise route kayit edilir. Aksi halde Flask otomatik 404 doner.
# - make run-dev (FLASK_ENV=development) -> endpoint AKTIF
# - make run (env var yok) -> endpoint PASIF (404)
# - PyInstaller build (frozen=True) -> endpoint PASIF (404), env var'lardan bagimsiz
# Not: Ileride eklenecek tum /_debug/* route'lari ayni if blogu icinde tanimlanmalidir.
_debug_enabled = (
    not getattr(sys, 'frozen', False)
    and (os.environ.get('FLASK_ENV') == 'development'
         or os.environ.get('FLASK_DEBUG') == '1')
)
if _debug_enabled:
    @app.route('/_debug/list-templates')
    def _debug_list_templates():
        try:
            tpl = app.template_folder
            static = app.static_folder
            tpl_exists = os.path.isdir(tpl)
            static_exists = os.path.isdir(static)
            tpl_files = []
            static_files = []
            if tpl_exists:
                for root, dirs, files in os.walk(tpl):
                    for f in files[:50]:
                        tpl_files.append(os.path.relpath(os.path.join(root, f), tpl))
                    break
            if static_exists:
                for root, dirs, files in os.walk(static):
                    for f in files[:50]:
                        static_files.append(os.path.relpath(os.path.join(root, f), static))
                    break
            return jsonify({'template_folder': tpl, 'template_exists': tpl_exists, 'template_sample': tpl_files,
                            'static_folder': static, 'static_exists': static_exists, 'static_sample': static_files})
        except Exception as e:
            return jsonify({'error': str(e)})

# ---- Arka Plan Cache Sistemi — background.py'den import edildi (sadece thread başlatıcılar; ----
# ---- route'ların ihtiyaç duyduğu cache erişimi kendi blueprint modüllerinde yapılır) ----
from web.background import (
    start_workload_stats_cache,
    start_pods_summary_cache,
    start_metrics_sampler,
    start_pss_cache,
    start_netpol_coverage_cache,
)

# ---- Blueprint: kubeconfigs (GET/POST/DELETE /kubeconfigs, POST /kubeconfigs/activate) ----
from web.blueprints.kubeconfigs import bp_kubeconfigs
app.register_blueprint(bp_kubeconfigs)

# ---- Blueprint: workloads (sayfa route'ları: /workloads, /config, /network, /storage, /nodes, /access-control, /configuration, /mesh, /mesh-data) ----
from web.blueprints.workloads import bp_workloads
app.register_blueprint(bp_workloads)

# ---- Blueprint: security (güvenlik route'ları: configmap-secrets, rbac, privileged, exec-events, yaml-linter, trivy, pss, netpol) ----
from web.blueprints.security import bp_security
app.register_blueprint(bp_security)

# ---- Blueprint: explorer (tüm /k8s-explorer/* ve /api/k8s/* route'ları) ----
from web.blueprints.explorer import bp_explorer
app.register_blueprint(bp_explorer)

@app.route('/api/version-check')
def api_version_check():
    """Güncelleme kontrolü endpoint'i — GitHub Releases API üzerinden yeni sürüm var mı kontrol eder.

    Tüm hata durumlarında (ağ, 404, parse) sessizce ``update_available: false`` döner.
    Sonuç 1 saat bellekte cache'lenir.

    :returns: JSON — ``{update_available, current_version?, latest_version?, release_url?, disabled?}``

    ---
    tags:
      - version
    responses:
      200:
        description: Sürüm kontrol sonucu
        schema:
          type: object
          properties:
            update_available:
              type: boolean
            current_version:
              type: string
            latest_version:
              type: string
            release_url:
              type: string
            disabled:
              type: boolean
    """
    from web.version_check import get_cached_version_info
    return jsonify(get_cached_version_info())


@app.route('/set-locale')
def set_locale():
    lang = request.args.get('lang', 'tr')
    if lang not in ('tr', 'en'):
        lang = 'tr'
    next_url = request.args.get('next') or request.referrer or '/'
    resp = redirect(next_url)
    # 180 days
    resp.set_cookie('lang', lang, max_age=60*60*24*180, httponly=False, samesite='Lax')
    return resp

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login sayfasi — GET: form goster, POST: token/parola dogrula.

    Yalnizca ag modu (_NETWORK_BIND_ACTIVE=True) anlamlidir; localhost modunda
    auth hook devredisi oldugu icin bu sayfaya nadiren ulasılır ancak route aktiftir.

    POST parametreleri:
        token (str): kullanicinin girdigi token veya parola
        next (str, opsiyonel): basarili giris sonrasi yonlendirilecek URL

    Yanıt:
        GET  200: login formu (login.html)
        POST 302: dogru token — / veya next URL'ye redirect
        POST 200: yanlis token — login.html + hata mesaji
    """
    from web.i18n import translate
    try:
        lang = request.cookies.get('lang') or 'tr'
    except Exception:
        lang = 'tr'

    if request.method == 'POST':
        token_input = request.form.get('token', '').strip()
        next_url = _safe_next_url(request.form.get('next'))
        if _ACCESS_TOKEN and secrets.compare_digest(token_input, _ACCESS_TOKEN):
            session.clear()
            session['_kubesec_authenticated'] = True
            return redirect(next_url)
        error_msg = translate('auth.invalid_token', lang)
        return render_template('login.html', error=error_msg, next=next_url, lang=lang), 200

    next_url = _safe_next_url(request.args.get('next'))
    return render_template('login.html', error=None, next=next_url, lang=lang), 200


@app.route('/logout')
def logout():
    """Oturumu kapat ve login sayfasina yonlendir.

    Session'daki auth isaretcisini temizler; kullanici /login'e yonlendirilir.

    Yanit:
        302: /login
    """
    session.pop('_kubesec_authenticated', None)
    return redirect(url_for('login'))


@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    """CSRF doğrulama hatası için JSON yanıt döndürür.

    Flask-WTF CSRFProtect, token eksik veya geçersiz olduğunda CSRFError
    fırlatır. Bu handler JSON formatında yanıt döndürür (HTML değil) çünkü
    tüm mutasyon istekleri fetch() üzerinden AJAX olarak yapılır.

    HTTP 400 döndürür.
    """
    return jsonify({'error': 'CSRF token eksik veya geçersiz. Sayfayı yenileyip tekrar deneyin.'}), 400


@app.errorhandler(Exception)
def handle_exception(e):
    from werkzeug.exceptions import HTTPException
    import sys

    # HTTPException ise (404 NotFound, 405 MethodNotAllowed, 400 BadRequest vb.)
    # Flask/Werkzeug'un kendi status kodunu ve aciklamasini koru — 500'e cevirme.
    if isinstance(e, HTTPException):
        response = {'error': e.description}
        if _debug_enabled:
            response['traceback'] = traceback.format_exc()
        return jsonify(response), e.code

    # Gercek beklenmeyen sunucu hatasi (HTTPException OLMAYAN) — 500 don.
    tb = traceback.format_exc()
    print('GLOBAL ERROR HANDLER:', e, file=sys.stderr)
    print(tb, file=sys.stderr)
    response = {'error': str(e)}
    # Traceback yalnizca gelistirme modunda yanita eklenir (production'da bilgi sizintisi onlenir).
    # _debug_enabled: app.py satir 130-134'te tanimli (FLASK_ENV=development veya FLASK_DEBUG=1).
    if _debug_enabled:
        response['traceback'] = tb
    return jsonify(response), 500

@app.route('/')
def index():
    return render_template('index.html')


# ---------------------------------------------------------------------------
# Arka plan cache thread'lerini başlat (tüm import'lar ve registrasyonlar sonrasında)
# ---------------------------------------------------------------------------
start_workload_stats_cache()
start_pods_summary_cache()
start_metrics_sampler()
start_pss_cache()
start_netpol_coverage_cache()
