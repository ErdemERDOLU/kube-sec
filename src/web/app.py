from flask import Flask, render_template, jsonify, request, redirect, send_from_directory
from flask_cors import CORS
from flasgger import Swagger
import sys, traceback, os, secrets
from pathlib import Path

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
    app.secret_key = 'dev-secret-do-not-use-in-production'
CORS(app, origins=CORS_ORIGINS, supports_credentials=True)
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


# Lightweight debug helper to inspect where Flask is resolving templates/static when frozen.
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

@app.errorhandler(Exception)
def handle_exception(e):
    import sys
    tb = traceback.format_exc()
    print('GLOBAL ERROR HANDLER:', e, file=sys.stderr)
    print(tb, file=sys.stderr)
    response = {
        'error': str(e),
        'traceback': tb
    }
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
