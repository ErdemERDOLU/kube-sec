"""web/validators.py — Merkezi girdi dogrulama fonksiyonlari.

Subprocess ve harici komut cagrisi yapan route'larda kullanici girdisini
RFC 1123 kurallarina gore dogrulamak icin kullanilir. Flask'a bagimli degildir;
herhangi bir blueprint veya servis katmanindan import edilebilir.
"""

import re

# RFC 1123 DNS Subdomain: kucuk harf alfanumerik + '-' + '.', basta/sonda alfanumerik, max 253.
# Kubernetes kaynak adlari (pod, deployment, configmap, vb.) bu kurala tabidir.
_RE_K8S_NAME = re.compile(r'^[a-z0-9]([a-z0-9.\-]{0,251}[a-z0-9])?\Z')

# RFC 1123 DNS Label: kucuk harf alfanumerik + '-', basta/sonda alfanumerik, max 63.
# Kubernetes namespace adlari nokta icermez; bu sebeple ayri bir regex kullanilir.
_RE_K8S_NAMESPACE = re.compile(r'^[a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?\Z')

# Helm chart versiyonu (semver uyumlu): rakamla baslar, alfanumerik + '.' + '-' + '+', max 128.
_RE_HELM_VERSION = re.compile(r'^[0-9][a-zA-Z0-9.\-+]{0,127}\Z')


def validate_k8s_name(value):
    """Kubernetes kaynak adini RFC 1123 DNS subdomain kuralina gore dogrular.

    Kurallar:
      - Bos olamaz
      - En fazla 253 karakter
      - Yalnizca kucuk harf alfanumerik, tire (-) ve nokta (.) icerabilir
      - Alfanumerik karakterle baslamali ve bitmeli

    :param value: Dogrulanacak kaynak adi (str)
    :returns: True ise gecerli, False ise gecersiz
    :rtype: bool

    Ornekler::

        >>> validate_k8s_name('nginx-deployment')
        True
        >>> validate_k8s_name('my-app.v2')
        True
        >>> validate_k8s_name('--kubeconfig')
        False
        >>> validate_k8s_name('MyPod')
        False
    """
    if not value or not isinstance(value, str):
        return False
    return bool(_RE_K8S_NAME.match(value))


def validate_k8s_namespace(value):
    """Kubernetes namespace adini RFC 1123 DNS label kuralina gore dogrular.

    Kurallar:
      - Bos olamaz
      - En fazla 63 karakter
      - Yalnizca kucuk harf alfanumerik ve tire (-) icerebilir (nokta YASAK)
      - Alfanumerik karakterle baslamali ve bitmeli

    :param value: Dogrulanacak namespace adi (str)
    :returns: True ise gecerli, False ise gecersiz
    :rtype: bool

    Ornekler::

        >>> validate_k8s_namespace('default')
        True
        >>> validate_k8s_namespace('kube-system')
        True
        >>> validate_k8s_namespace('my.namespace')
        False
        >>> validate_k8s_namespace('../../etc/shadow')
        False
    """
    if not value or not isinstance(value, str):
        return False
    return bool(_RE_K8S_NAMESPACE.match(value))


def validate_helm_version(value):
    """Helm chart versiyon stringini dogrular (semver uyumlu).

    Kurallar:
      - Bos olamaz
      - Rakamla baslamali (ornegin '0.31.0', '1.0.0-rc1')
      - Yalnizca alfanumerik, nokta (.), tire (-) ve arti (+) icerebilir
      - En fazla 128 karakter

    :param value: Dogrulanacak versiyon stringi (str)
    :returns: True ise gecerli, False ise gecersiz
    :rtype: bool

    Ornekler::

        >>> validate_helm_version('0.31.0')
        True
        >>> validate_helm_version('1.0.0-rc1')
        True
        >>> validate_helm_version('--set image.tag=evil')
        False
    """
    if not value or not isinstance(value, str):
        return False
    return bool(_RE_HELM_VERSION.match(value))
