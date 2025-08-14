## Copilot instructions for kube-sec

This repo is a Flask-based Kubernetes security explorer/scanner. The web app exposes JSON APIs and HTML views to inspect cluster resources and flag common misconfigurations.

Architecture and flow
- Entry point: `src/main.py` runs Flask on 0.0.0.0:8080 in debug mode and imports `web.app`.
- Web layer: `src/web/app.py` defines all routes (k8s explorer, scaling, logs, restarts, describe, etc.). It enables CORS and Swagger UI.
- Scanner: `src/scanner/k8s_scanner.py` contains `K8sScanner` with rule-style checks on Deployments (image tags, resource limits, securityContext, probes, NetworkPolicy, etc.).
- Utilities/Reports: `src/utils/helpers.py` (YAML load and simple formatting) and `src/reports/report_generator.py` (collect and save summaries).
- Legacy: `k8s-security-checker/` exists but contains mostly empty stubs—treat `src/` as the active code.

Kubernetes client patterns
- For API calls, endpoints follow this sequence (replicate for new handlers):
  1) `config.load_kube_config()`
  2) disable SSL verification for convenience: `c = client.Configuration.get_default_copy(); c.verify_ssl=False; c.assert_hostname=False; client.Configuration.set_default(c)`
  3) instantiate API: `client.CoreV1Api()`, `client.AppsV1Api()`, etc.
- Label selection is built as CSV: `label_selector=','.join([f"{k}={v}" for k,v in selector.items()])` for listing Pods of a DaemonSet/StatefulSet.
- Some operations shell out to kubectl (e.g., `/k8s-explorer/describe`); it respects `KUBECONFIG` and applies a 15s timeout.

API conventions and examples
- Route namespace: management endpoints live under `/k8s-explorer/*`.
- Read endpoints are GET and return JSON with a top-level key (e.g., `{'daemonsets': [...]}`); errors are `{'error': str(e)}` with appropriate status codes.
- Mutations are POST with JSON bodies, e.g. scale Deployment: `POST /k8s-explorer/scale-deployment` body `{"namespace":"ns","name":"app","replicas":3}`.
- Restart pattern uses a patch setting `metadata.annotations["kubectl.kubernetes.io/restartedAt"]` on the pod template.

Scanner conventions (K8sScanner)
- Returns a list of human-readable strings (e.g., "Container X uses 'latest' image tag.").
- Checks include: missing `securityContext`, containers without limits/requests, sensitive env var names (password/secret/key/token), hostPath volumes, `readOnlyRootFilesystem` disabled, dangerous capabilities (NET_ADMIN/SYS_ADMIN), `allow_privilege_escalation` true, missing liveness/readiness probes, default ServiceAccount, and absence of NetworkPolicy in the namespace.
- Note: `utils.format_output` expects dicts `{name,severity}`; current scanner emits strings. Keep string messages unless refactoring the formatter and all callers together.

Local dev workflow
- Install deps then run: `python3 src/main.py` (or use the VS Code task "Run Flask App"). App listens on port 8080; CORS allows `http://localhost:8080` and `http://127.0.0.1:8080`.
- Docker: `Dockerfile` installs from `requirements.txt` and starts `python src/main.py`.
- Cluster access: the app uses the local kubeconfig; set `KUBECONFIG` if non-default. Many endpoints disable TLS verification; this is convenient for dev but insecure for prod.

Dependencies and gotchas
- Key packages: Flask, flask-cors, kubernetes, pyyaml, requests, pytest. Code imports `flasgger` (Swagger) but it’s not listed—add `flasgger` if Swagger UI errors occur.
- Swagger UI host is hardcoded to `127.0.0.1:8080` in `web/app.py`; adjust if serving behind a different host/port.

Extending the app
- Place new k8s operations under `/k8s-explorer/*`, follow the client bootstrap and JSON response patterns above, and reuse label selectors and patch shapes from existing handlers.
- If adding UI, mirror the pattern under `src/web/templates/*` and ensure CORS/origins cover your frontend.
