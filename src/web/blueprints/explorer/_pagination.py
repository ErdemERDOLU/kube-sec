"""explorer/_pagination.py — Ortak sayfalama (pagination) yardımcı modülü.

In-memory slicing yaklaşımı: tam listeyi Python tarafında
page/per_page parametrelerine göre dilimleme.

Gerekçe (spec'ten):
- pods-summary zaten arka plan cache'inde bellekte tutulur — dilimleme
  sıfır ek K8s API maliyetidir.
- deployments-summary ve configmaps-summary K8s API'den tam listeyi çeker;
  dilimle frontend'e giden JSON boyutunu ve tarayıcı render yükünü düşürür.
- K8s client'ın limit/continue token'ları stateless page=N mantığıyla
  uyumsuzdur; bu nedenle client-side slicing seçildi.
"""

import math


def paginate_list(full_list, request_args):
    """Tam bir Python listesini request parametrelerine göre sayfalara böler.

    Parametreler:
        full_list (list): Tüm öğeleri içeren liste (filtrelenmiş ya da ham).
        request_args: Flask'ın request.args nesnesi (ImmutableMultiDict).

    Dönüş değeri:
        tuple(response_dict | None, is_paginated: bool)

        - ``page`` parametresi gönderilmemişse ``(None, False)`` döner;
          çağıran eski yanıt formatını kullanmalıdır (geriye dönük uyumluluk).
        - ``page`` parametresi gönderilmiş ve geçerliyse aşağıdaki zarf
          dict'ini ve ``True`` döner::

              {
                  "items":       [...],   # ilgili sayfanın öğeleri
                  "page":        N,       # istenen sayfa (1-tabanlı)
                  "per_page":    M,       # uygulanan sayfa boyutu
                  "total":       T,       # toplam kayıt sayısı
                  "total_pages": P,       # ceil(total / per_page)
              }

        - Geçersiz parametre durumunda ``ValueError`` fırlatır;
          çağıran bunu HTTP 400'e dönüştürmelidir.

    Kısıtlar:
        - page  >= 1
        - per_page 1-500 arasında
        - page > total_pages ise items boş liste döner, HTTP 200 korunur.
    """
    # page parametresi hiç gönderilmemişse sayfalama devre dışı
    if 'page' not in request_args:
        return None, False

    # --- page doğrulaması ---
    try:
        page = int(request_args.get('page'))
    except (TypeError, ValueError):
        raise ValueError(
            "Geçersiz sayfalama parametresi: page sayısal bir tamsayı olmalıdır"
        )

    # --- per_page doğrulaması (varsayılan: 50) ---
    try:
        per_page = int(request_args.get('per_page', 50))
    except (TypeError, ValueError):
        raise ValueError(
            "Geçersiz sayfalama parametresi: per_page sayısal bir tamsayı olmalıdır"
        )

    if page < 1:
        raise ValueError(
            f"Geçersiz sayfalama parametresi: page >= 1 olmalıdır (alınan: {page})"
        )

    if per_page < 1 or per_page > 500:
        raise ValueError(
            f"Geçersiz sayfalama parametresi: per_page 1-500 arasında olmalıdır"
            f" (alınan: {per_page})"
        )

    total = len(full_list)

    # Toplam sayfa sayısı; boş liste durumunda en az 1 döner
    total_pages = max(1, math.ceil(total / per_page)) if total > 0 else 1

    # Dilim sınırlarını hesapla (page > total_pages ise boş items — HTTP 200)
    start = (page - 1) * per_page
    end = start + per_page
    items = full_list[start:end]

    return {
        'items': items,
        'page': page,
        'per_page': per_page,
        'total': total,
        'total_pages': total_pages,
    }, True
