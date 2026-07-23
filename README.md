# Kube-Sec

A Kubernetes security and operations dashboard built with Python Flask. Kube-Sec connects to a live cluster via the official Kubernetes Python client, renders server-side Jinja2 pages, and provides both security-focused checks (privileged containers, risky RBAC, vulnerability reports) and everyday operations views (workloads, nodes, storage, networking). It runs as a browser-based Flask server, and can also be packaged as a standalone desktop application for macOS or Windows using PyInstaller.

---

## Features

All features listed below are backed by a route in `src/web/app.py` and a corresponding template under `src/web/templates/`.

**Cluster exploration and management**

- Kubernetes Explorer — browse, inspect, edit, and delete cluster resources (Deployments, Pods, Services, Ingresses, ConfigMaps, Secrets, and more) with inline YAML viewing and patching
- Workload management — Deployments, DaemonSets, StatefulSets, ReplicaSets, Jobs, and CronJobs; scale, restart, and view logs from the UI
- Node monitoring — list nodes, view resource usage, cordon/uncordon/drain
- Storage — PersistentVolumeClaims, PersistentVolumes, and StorageClasses
- Networking — Services, Endpoints, Ingresses, IngressClasses, and NetworkPolicies
- Access control — ClusterRoles, Roles, ClusterRoleBindings, and RoleBindings
- Policy resources — HorizontalPodAutoscalers (HPA), PodDisruptionBudgets (PDB), ResourceQuotas, LimitRanges, PriorityClasses, RuntimeClasses, and Leases
- Admission webhooks — MutatingWebhookConfigurations and ValidatingWebhookConfigurations (read-only summary)

**Security checks**

- Privileged/root container detection — scans all running pods and flags containers with `privileged: true` or `runAsUser: 0`
- Risky RBAC role analysis — identifies roles and cluster roles with wildcard (`*`) permissions
- Pod exec event monitoring — tracks `exec` invocations against pods in real time
- ConfigMap and Secret data exposure scan — surfaces Secrets and ConfigMaps that may contain sensitive plaintext values
- YAML Linter — validates Kubernetes manifests against API conventions before applying them

**Vulnerability reporting**

- Trivy Operator integration — install Trivy Operator into the cluster, trigger scans, and view `VulnerabilityReport` CRDs from the UI
- Harbor Trivy vulnerability results — query a Harbor registry's Trivy scan results via the UI
- Vulnerability summary view — aggregated vulnerability dashboard

**Observability**

- Prometheus metrics integration — proxy Prometheus queries from the UI; display per-pod CPU and memory time-series charts (`PROMETHEUS_URL` or in-cluster auto-discovery)
- Service mesh visualization — renders a pod-to-service communication map

**Platform**

- Multi-cluster support — upload and switch between multiple kubeconfig files from within the UI; active cluster is tracked per browser session
- Internationalization (i18n) — Turkish and English UI; language is stored in a `lang` cookie and toggled via `/set-locale`
- Swagger/OpenAPI documentation — auto-generated and served at `/apidocs/` by Flasgger

---

## Prerequisites

- **Python 3.9+** (the Docker image uses `python:3.9-slim`)
- **A valid kubeconfig file** with access to a running Kubernetes cluster
- **kubectl** available in `PATH` — required for Trivy Operator shell operations (`_run_cmd`)
- **Docker** — only if you intend to run the container image
- **PyInstaller** — only if you intend to build the desktop application locally

---

## Installation

```bash
# 1. Create a Python virtual environment
make venv

# 2. Install runtime dependencies from requirements.txt
make install
```

`make venv` creates `.venv/` in the project root using the system `python3`. `make install` installs into `.venv/bin/python` if that file exists on disk, or the system `python3` otherwise — it checks for the file, not whether a virtualenv is currently activated in your shell.

**Dependencies installed** (from `requirements.txt`):

| Package | Version constraint |
|---|---|
| Flask | `>=2.2,<3.0` |
| Werkzeug | `>=2.2,<3.0` |
| kubernetes | `==21.7.0` |
| PyYAML | `>=6.0,<7.0` |
| requests | `==2.26.0` |
| flasgger | `==0.9.7.1` |
| flask-cors | latest |

---

## Running the Application

### Local Development

```bash
# Standard mode — serves on http://0.0.0.0:8080
make run

# Development mode — sets FLASK_ENV=development before starting
make run-dev
```

Both targets execute `python src/main.py`, which imports `web.app:app` and calls `app.run(host="0.0.0.0", port=8080, debug=True)`.

Open your browser at `http://localhost:8080` after startup.

### Docker

> **DEPRECATED:** Docker destegi artik bakim altinda degildir. Uygulama yalnizca masaustu (desktop) paketi olarak kullanilmalidir.

```bash
# Build the image
docker build -t kube-sec .

# Run with a kubeconfig mounted from the host
docker run -p 8080:8080 \
  -v ~/.kube/config:/root/.kube/config:ro \
  -e KUBECONFIG=/root/.kube/config \
  kube-sec
```

The image is based on `python:3.9-slim`. The entry point is `python src/main.py`; no `EXPOSE` instruction is present in the Dockerfile, so the `-p 8080:8080` flag is required for host access.

### Desktop Application (macOS / Windows)

The desktop build uses `launcher.py` as the PyInstaller entry point instead of `src/main.py`. The launcher:

- Adjusts `sys.path` so the bundled app can be imported, then imports `web.app` — which itself detects the frozen (`sys.frozen`) environment and adjusts its template/static paths accordingly
- Selects a free port starting at 8080 (scans up to 30 consecutive ports)
- Opens the system default browser automatically on startup

To suppress the automatic browser open:

```bash
NO_AUTO_BROWSER=1 ./Kube-Sec.app/Contents/MacOS/Kube-Sec
```

To override the port:

```bash
APP_PORT=9090 ./Kube-Sec.app/Contents/MacOS/Kube-Sec
```

Pre-built binaries are distributed as `.app` (macOS) or `.exe` (Windows). To build locally, see [Packaging & Release](#packaging--release).

---

## Configuration

### Kubeconfig Management

Kube-Sec supports multiple clusters simultaneously through its built-in kubeconfig manager (`/kubeconfigs` routes):

- **Upload a kubeconfig** — POST to `/kubeconfigs` to upload a file; it is stored under `kubeconfigs/` on disk
- **Activate a cluster** — POST to `/kubeconfigs/activate`; the active kubeconfig name is stored in the browser session (`flask.session`) and mirrored to a process-global variable (`KUBECONFIG_ACTIVE_GLOBAL`) so background threads can read it outside a request context
- **Remove a kubeconfig** — DELETE to `/kubeconfigs`

Resolution order when a route needs to know which cluster to talk to (`get_active_kubeconfig_path()`):

1. Flask session (`active_kubeconfig` key)
2. Process-global `KUBECONFIG_ACTIVE_GLOBAL`
3. Auto-select if exactly one file exists in `kubeconfigs/`
4. Last successfully loaded path (`KUBECONFIG_LAST_PATH`)
5. `KUBECONFIG` environment variable

Every route handler calls `load_kube_config_active()` per request; there is no shared persistent `ApiClient`.

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `APP_SECRET_KEY` | `dev-secret` | Flask session signing key. **Must be changed in any non-local deployment.** |
| `KUBECONFIG` | — | Path to a kubeconfig file; used as the final fallback in cluster resolution |
| `PROMETHEUS_URL` | — | Base URL of a Prometheus instance; used by the metrics proxy when in-cluster discovery is not available |
| `NO_AUTO_BROWSER` | — | Set to `1` to prevent the desktop launcher from opening a browser tab on startup |
| `APP_PORT` | first free port from `8080` up | Port the desktop launcher binds to (overrides automatic free-port selection with a fixed value) |
| `METRICS_TS_INTERVAL_SEC` | `10` | Polling interval in seconds for the background metrics sampler thread |
| `FLASK_ENV` | — | Set to `development` by `make run-dev`; enables Flask debug reloader |

---

## Security Notes

> **Read this section before exposing Kube-Sec to any network beyond your local machine.**

**TLS verification is disabled for all Kubernetes API calls.** Every route handler in `src/web/app.py` sets `c.verify_ssl = False` on the Kubernetes client configuration before making API calls. This means man-in-the-middle attacks against the cluster API server are not detected. Do not expose the application on an untrusted network without adding a TLS-terminating reverse proxy and re-enabling certificate verification.

**The default Flask secret key is `dev-secret`.** `app.secret_key` is set to `os.environ.get('APP_SECRET_KEY', 'dev-secret')` (line 44 of `src/web/app.py`). Flask uses this key to sign session cookies. Anyone who knows the key can forge session cookies. Set `APP_SECRET_KEY` to a strong random value in any deployment beyond a single-user local workstation.

**`kubeconfigs/` contains real cluster credentials.** Files uploaded through the UI are stored as plaintext under `kubeconfigs/`. This directory is listed in `.gitignore` and must never be committed to version control. Treat its contents with the same care as private keys.

**Private key and certificate files are gitignored.** The `.gitignore` excludes `*.pem` and `*.key` patterns project-wide, in addition to `kubeconfigs/` and `.env`/`.env.*` files.

---

## Architecture Overview

- **Single-file Flask application** — almost all page routes and AJAX/JSON endpoints live in `src/web/app.py` (approximately 5,500 lines). There are no Flask blueprints or sub-packages. The application follows a consistent pattern: a `/<page>` route renders a Jinja2 template, and one or more `/k8s-explorer/<resource>-summary` or `/api/k8s/<resource>` JSON endpoints supply the data that the page's JavaScript fetches.

- **Server-side templates** — UI pages are rendered by Jinja2 templates in `src/web/templates/`. All templates extend `base.html`. Page-specific JavaScript is either embedded in the template or placed in `src/web/static/`.

- **Kubernetes Python client** — cluster communication uses the official `kubernetes` Python library (`kubernetes==21.7.0`). The client configuration is reloaded per request via the active kubeconfig path.

- **Background cache threads** — three daemon threads run continuously to reduce per-request latency on frequently accessed views: `workload_stats_cache_refresher` (workload counts), `pods_summary_cache_refresher` (pod list), and `_metrics_sampler_loop` (time-series metrics). They populate module-level dicts that route handlers read. Switching the active kubeconfig invalidates and refreshes these caches.

- **Shell-out for Trivy/kubectl operations** — Trivy Operator install and scan operations call `kubectl` as a subprocess via `_run_cmd`/`_kubectl_base_args`. Everything else uses the Python Kubernetes client directly.

- **`src/scanner/` and `src/reports/`** — `K8sScanner` and `ReportGenerator` classes exist but most active scanning logic is embedded directly in `app.py` route handlers; these classes are largely vestigial.

- **`app/` and `components/` directories in the repo root** — these are an unused Next.js/shadcn skeleton generated by v0.app. They are not connected to the Flask backend and have no effect on the running application. The real UI is the Flask/Jinja2 layer described above.

---

## API Documentation

When the application is running, interactive API documentation is available at:

```
http://localhost:8080/apidocs/
```

This is a Swagger UI generated automatically by [Flasgger](https://github.com/flasgger/flasgger) from the route definitions in `src/web/app.py`. The raw OpenAPI spec is served at `/apispec_1.json`.

---

## Packaging & Release

The desktop application is built with [PyInstaller](https://pyinstaller.org/) using `Kube-Sec.spec`. `launcher.py` is the entry point for the bundle; it bundles `src/`, `src/web/templates/`, `src/web/static/`, `styles/`, and `yaml/` into a single `Kube-Sec.app`.

### macOS

```bash
# Build for the current architecture
make build-macos

# Architecture-specific builds
make build-macos-arm          # Apple Silicon (arm64)
make build-macos-intel        # Intel (x86_64)
make build-macos-universal    # universal2 (best-effort; see Makefile note)

# Code signing (requires SIGN_IDENTITY env var)
make sign SIGN_IDENTITY='Developer ID Application: Your Name (TEAMID)'

# Notarization (requires NOTARY_APPLE_ID, NOTARY_TEAM_ID, NOTARY_PASSWORD)
make notarize

# Create a distributable DMG
make dmg

# Full release workflow: sign + notarize + DMG in one step
make release-macos \
  SIGN_IDENTITY='Developer ID Application: Your Name (TEAMID)' \
  NOTARY_APPLE_ID='you@example.com' \
  NOTARY_TEAM_ID='TEAMID' \
  NOTARY_PASSWORD='app-specific-password'
```

All macOS build targets call `build_macos_app.sh` with the appropriate environment variables. Refer to that script and the Makefile for the exact steps.

### Windows

```bash
# Bash (Git Bash / WSL)
bash build-windows.sh

# PowerShell
.\build-windows.ps1
```

---

## Version Management

The authoritative version is stored in the `VERSION` file in the repository root. `src/version.py` is a generated file kept in sync with `VERSION`.

```bash
# Display the current version
make version-show

# Increment version components (updates VERSION and regenerates src/version.py)
make bump-patch     # 1.0.0 -> 1.0.1
make bump-minor     # 1.0.0 -> 1.1.0
make bump-major     # 1.0.0 -> 2.0.0

# Set an explicit version
make set-version VERSION=1.2.3

# Sync VERSION -> src/version.py without bumping
make version-sync

# Tag the current version in git and push the tag
make tag
make push-tag
```

Current version: **1.0.0**

---

## Güvenlik: Pre-commit Secret Taraması

Bu repo, yanlışlıkla commit edilen secret/credential'ları yakalamak için iki katmanlı bir koruma kullanır:

**1. Katman — Yerel pre-commit hook (geliştirici makinasında):**

Repo'yu ilk clone'ladıktan sonra aşağıdaki iki komutu bir kez çalıştır:

```bash
pip install pre-commit
pre-commit install
```

Bu komutlar `.git/hooks/pre-commit` dosyasını oluşturur. Bundan sonra her `git commit` işleminde [gitleaks](https://github.com/gitleaks/gitleaks) otomatik olarak çalışır ve staged değişikliklerde bilinen secret pattern'ları (API key, token, private key, parola vb.) arar. Bulgu varsa commit reddedilir.

Manuel tarama (tüm tracked dosyalar):

```bash
pre-commit run gitleaks --all-files
```

**2. Katman — CI (GitHub Actions):**

Her push ve her pull request'te `.github/workflows/security-scan.yml` otomatik tetiklenir. Pre-commit hook'unu kurmadan push eden bir geliştirici olsa bile, CI bu taramayı çalıştırır ve secret bulunursa build'i kırar.

---

## Contributing

Contributions are welcome. To report a bug or request a feature, please open an issue on GitHub. To submit a change, fork the repository, make your changes on a branch, and open a pull request against `main`.

There is no automated test suite at present (pytest is listed in `requirements.txt` but no tests exist). When adding a feature, please verify manually that the affected routes return the expected responses and that the corresponding Jinja2 templates render without errors.

---

## License

License: TBD — a license file has not yet been added to this repository. Until a license is published, the source code is not explicitly available for reuse, modification, or distribution. If you intend to use or contribute to this project, please contact the project owner first.
