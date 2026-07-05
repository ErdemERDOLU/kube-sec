# Spec: Masaustu Sidebar Collapse Toggle Butonu Gorunurluk Hatasi

**Tarih:** 2026-07-05
**Dosya:** `src/web/templates/base.html` (tek kaynak; satir 15-619 arasi ilgili bloklar)
**Tip:** Bugfix (CSS layout)

---

## Problem Tanimi

Masaustu gorunumunde sidebar daraltildiginda (collapsed state, 70px genislik), `.sidebar-header` icindeki uc alt eleman (logo, marka metni, toggle butonu) 70px - ~32px padding = ~38px icerik alanina sigmiyor. Toggle butonu `margin-left: auto` ile saga itildigi ve `.sidebar` uzerinde acik bir `overflow-x: hidden` olmadigi icin buton gorunur alandan tasan ve tiklanamaz hale geliyor. Kullanici sidebar'i daralttiginda tekrar genisletmek icin sayfayi yenilemek veya localStorage'i elle temizlemek zorunda kaliyor.

---

## Kullanici Hikayesi

Bir Kube-Sec kullanicisi olarak, masaustu gorunumunde sidebar'i daralttigimda toggle butonunu her zaman gorebilmek ve tek tikla sidebar'i tekrar genisletebilmek istiyorum; boylece sayfa yenilemeye veya tarayici aracilarina basvurmadan calismama devam edebilirim.

---

## Kapsam

**Dahil:**
- `src/web/templates/base.html` icindeki gomulu `<style>` blogunda `.sidebar.collapsed` durumuna ozgu CSS duzeltmeleri (overflow, header layout, toggle buton konumlandirma).
- Gerekirse ayni dosyadaki HTML markup'inda minimal yapisal degisiklik (ornegin toggle butonunu header disina cikarmak gibi -- yalnizca CSS ile cozum mumkun degilse).

**Kapsam Disi (dokunulmayacak):**
- Mobil collapse/expand mekanizmasi (`.mobile-open`, `max-width: 768px` media query, satir 251-287).
- `<script>` blogundaki `sidebarToggle` click listener mantigi (zaten dogru calisiyor, yeniden yazilmayacak).
- Sidebar disindaki herhangi bir stil veya baska sablonlar.
- Yeni JavaScript davranisi eklenmesi (ornegin hover-to-expand gibi alternatif UX degisiklikleri).
- `--sidebar-width` veya `--sidebar-collapsed-width` CSS degisken degerlerinin degistirilmesi.

---

## Kabul Kriterleri

### Kritik Gereksinim

| # | Kriter | Dogrulama Yontemi |
|---|--------|-------------------|
| 1 | `.sidebar.collapsed` durumunda toggle butonu (`.sidebar-toggle`) tamamen gorunur ve tiklanabilir olmalidir. Butonun hicbir kismi 70px genislikli sidebar sinirinin disina tasmamalidir. | Tarayici DevTools ile inspect: butonun `getBoundingClientRect()` degerleri sidebar'in sinirlari icinde kalmali. |
| 2 | `.sidebar` elemaninda yatay kaydirma cubugu (horizontal scrollbar) her iki durumda da (expanded ve collapsed) gorunmemelidir. | Chrome/Firefox'ta 1440px ve 1920px viewport genisliginde gorsel kontrol + `element.scrollWidth <= element.clientWidth` assertion'i. |
| 3 | Toggle butonuna art arda tiklandiginda (collapse -> expand -> collapse -> expand, en az 4 gecis) her tiklamada durum dogru sekilde degismeli; ekstra tiklama veya sayfa yenileme gerektirmemelidir. | Manuel test: 4 ardisik tiklama, her birinde sidebar genisligi beklenen degere gecmeli. |
| 4 | localStorage'daki `sidebarCollapsed` degeri sayfa yenilendikten sonra korunmali ve sidebar dogru durumda acilmalidir (collapsed ise collapsed, expanded ise expanded). | Sayfa yenile -> sidebar durumu localStorage ile tutarli olmali. |

### Orta Gereksinim

| # | Kriter | Dogrulama Yontemi |
|---|--------|-------------------|
| 5 | Collapsed durumda sidebar-header alani, altindaki navigasyon oge ikonlarini (`.nav-item` satirlari) gorsel olarak bozmamaldir -- ikonlar yatay olarak ortalanmis ve tiklanabilir kalmalidir. | Gorsel inceleme: ilk 5 nav-item ikonu dogru hizalanmis ve tiklanabilir. |
| 6 | Expanded durumda sidebar-header gorunumu mevcut tasarimla ayni kalmalidir (logo + marka metni + toggle butonu yatay hizali, `gap: 0.75rem` korunmali). | Oncesi/sonrasi ekran goruntusu karsilastirmasi. |

### Nice-to-have

| # | Kriter | Dogrulama Yontemi |
|---|--------|-------------------|
| 7 | Collapsed durumda toggle butonu gorsel olarak merkezlenmis olmali (yatay olarak sidebar'in ortasinda). | DevTools ile butonun margin degerlerinin simetrik oldugunu dogrula. |

---

## Acik Sorular / Riskler

1. **HTML degisikligi gerekli mi?** Eger toggle butonunun konumunu salt CSS ile cozmek mumkun degilse (ornegin absolute positioning ile), butonun DOM'daki yerinin degismesi gerekebilir. Bu durumda JS selector'unun (`document.querySelector('.sidebar-toggle')`) hala dogru elemani buldugunu dogrulamak gerekir.
2. **`overflow-x: hidden` yan etkileri:** Sidebar iceriginde yatay tasan baska elemanlar varsa (ornegin uzun nav-item etiketleri) bunlarin kesilmesi gorsel bir regresyon yaratabilir -- expanded durumda `overflow-x` davranisinin degismediginden emin olunmali.

---

## Aksiyon Listesi

1. [ ] `.sidebar.collapsed` durumuna `overflow-x: hidden` ekle (veya `.sidebar` geneline -- her iki durumda da scrollbar gorunmemeli).
2. [ ] `.sidebar.collapsed .sidebar-header` icin layout kurallarini guncelle: toggle butonunun 38px icerik alanina sigmasi icin gereksiz elemanlari gizle (`brand-text` -> `display:none`) ve buton konumlandirmasini duzelt.
3. [ ] Kabul kriteri 1-6'yi karsilayan degisiklikleri uygula.
4. [ ] Degisiklik sonrasi expanded durumda gorsel regresyon olmadigini dogrula (kriter 6).
