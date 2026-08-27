"""web/confirmation.py — Yikici islemler icin sunucu tarafi onay mekanizmasi.

require_confirm_name() ve require_confirm_names() yardimci fonksiyonlari,
14 yikici endpoint'te tekrarlanan onay kontrolunu merkezi olarak saglar.
confirm_name eksik veya yanlis ise (Response, 400) tuple dondurur; cagiran
endpoint bu degeri dogrudan return edebilir.

Backlog #26 — OWASP A04:2021 Insecure Design kapatma.

Eslestirme buyuk/kucuk harf duyarlidir (AC-12): Kubernetes kaynak adlari
RFC 1123 geregi kucuk harftir; bu nedenle case-sensitive eslestirme dogru
davranistir. Ornek: confirm_name='Worker-1' vs name='worker-1' -> 400.

Cagri kaliplari::

    # Tekil silme / restart:
    err = require_confirm_name(data)
    if err:
        return err

    # Node endpoint'leri (name_field='node'):
    err = require_confirm_name(data, name_field='node')
    if err:
        return err

    # Toplu silme:
    err = require_confirm_names(data, items)
    if err:
        return err
"""

from flask import jsonify


_MSG_MISSING = (
    "Onay parametresi eksik: istegin body'sinde confirm_name alani, "
    "kaynak adiyla ayni degerle gonderilmelidir."
)
_MSG_MISMATCH = (
    "Onay parametresi eslesmedi: confirm_name degeri, kaynak adiyla "
    "birebir ayni olmalidir (buyuk/kucuk harf duyarli)."
)
_MSG_NAMES_MISSING = (
    "Onay parametresi eksik: toplu islem icin istegin body'sinde "
    "confirm_names alani (string dizisi) gonderilmelidir."
)
_MSG_NAMES_MISMATCH = (
    "Onay parametresi eslesmedi: confirm_names listesi, silinecek "
    "kaynaklarin name listesiyle birebir ayni olmalidir."
)


def require_confirm_name(data: dict, name_field: str = "name"):
    """confirm_name alani eksikse veya name_field degeriyle eslesmezse (response, 400) dondurur.

    Basari durumunda ``None`` dondurur.

    :param data: Request JSON body veya esdeger dict.
                 Hem ``name_field`` hem de ``confirm_name`` anahtarlarini icermeli.
    :param name_field: Karsilastirilacak alan adi. Tekil endpoint'lerde ``'name'``
                       (varsayilan), node endpoint'lerinde ``'node'``.
    :returns: ``None`` (basari) veya ``(flask.Response, 400)`` tuple (basarisiz).

    Eslestirme buyuk/kucuk harf duyarlidir (AC-12):
    ``confirm_name='Worker-1'`` vs ``name='worker-1'`` -> 400 tuple.

    Ornek kullanim::

        data = request.get_json(force=True) or {}
        name = data.get('name')
        if not name:
            return jsonify({'error': 'name zorunlu'}), 400
        err = require_confirm_name(data)
        if err:
            return err
        # K8s API cagrilari...
    """
    expected = (data.get(name_field) or "").strip()
    confirm = (data.get("confirm_name") or "").strip()

    if not confirm:
        return jsonify({"error": _MSG_MISSING}), 400
    if confirm != expected:
        return jsonify({"error": _MSG_MISMATCH}), 400
    return None


def require_confirm_names(data: dict, items: list):
    """Toplu silme icin: confirm_names listesi items'taki name'lerle eslesmezse (response, 400) dondurur.

    Basari durumunda ``None`` dondurur.

    :param data: Request JSON body (dict). ``confirm_names`` anahtari (string listesi) icermeli.
    :param items: Silinecek kaynaklarin listesi. Her eleman ``'name'`` anahtari olan dict olmali.
    :returns: ``None`` (basari) veya ``(flask.Response, 400)`` tuple (basarisiz).

    Siralama onemsizdir; elemanlar birebir eslesmelidir (buyuk/kucuk harf duyarli).

    Ornek kullanim::

        items = data.get('items')
        if not items or not isinstance(items, list):
            return jsonify({'error': 'items listesi zorunlu'}), 400
        err = require_confirm_names(data, items)
        if err:
            return err
        # K8s API cagrilari...
    """
    confirm_names = data.get("confirm_names")

    if not isinstance(confirm_names, list):
        return jsonify({"error": _MSG_NAMES_MISSING}), 400

    expected = sorted(str(it.get("name", "")) for it in items if it.get("name"))
    provided = sorted(str(n) for n in confirm_names if n)

    if provided != expected:
        return jsonify({"error": _MSG_NAMES_MISMATCH}), 400

    return None
