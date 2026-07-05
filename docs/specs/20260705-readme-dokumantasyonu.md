# Spec: Kube-Sec README.md Dokumantasyonu

**Tarih:** 2026-07-05
**Talep eden:** Proje sahibi
**Uygulayici:** technical-writer agent

---

## Problem Tanimi

Kube-Sec projesi acik kaynak olarak GitHub'da yayinlandi ancak kok dizinde bir README.md dosyasi bulunmuyor. Potansiyel kullanicilar ve katkilcilar projenin ne oldugunu, nasil kurulacagini, nasil calistirilacagini ve guvenlik ozelliklerini anlayamiyor. Bu durum projenin kesfedilebilirligini ve benimsenmesini dogrudan engelliyor.

## Kullanici Hikayeleri

1. Bir **potansiyel kullanici** olarak, GitHub repo sayfasinda projenin ne yaptigi hakkinda hizli bir ozet okumak istiyorum, boylece bu aracin ihtiyacima uygun olup olmadigina karar verebilirim.
2. Bir **DevOps muhendisi** olarak, projeyi yerel makinemde kurma ve calistirma adimlarini gormek istiyorum, boylece 10 dakika icinde calisan bir orneye ulasmam gereken bilgiyi hemen bulabilirim.
3. Bir **guvenlik muhendisi** olarak, hangi guvenlik kontrollerinin sunuldugunun listesini gormek istiyorum, boylece mevcut guvenlik araclarimla karsilastirma yapabilirim.
4. Bir **katkilci** olarak, projenin teknik mimarisini ve gelistirme ortami kurulumunu anlatan bir bolum okumak istiyorum, boylece katki yapabilecegim alanlari hizlica belirleyebilirim.

---

## Kabul Kriterleri

### Kritik Gereksinimler

**AC-01 (Dil karari):** README.md dosyasi Ingilizce yazilmali. Gerekce: Acik kaynak proje oldugu icin uluslararasi kesfedilebilirlik ve erisim onceliklidir. CLAUDE.md'deki Turkce kurali, projenin dahili gelistirme iletisimi ve commit mesajlari icindir; README.md, projenin dis dunyaya acilan yuzudur ve Ingilizce olmalidir. Turkce ceviri ihtiyaci varsa ileride ayri bir README.tr.md ile karsilanabilir ancak bu spec'in kapsami disindadir.

**AC-02 (Proje tanitimi):** README.md, en ustte projenin ne oldugunu 2-4 cumle ile ozetleyen bir paragraf icermeli. Bu ozet su unsurlari kapsamali: (a) Kubernetes guvenlik/operasyon panosu oldugu, (b) Python Flask tabanli oldugu, (c) hem web tarayici hem bagimsiz masaustu uygulamasi olarak calistigi. Bu ozet, kaynak kodla dogrulanabilir olmalidir (src/main.py'nin Flask uygulamasi baslattigini, launcher.py'nin masaustu modunu calistirdigini teyit eden bilgiler).

**AC-03 (Ozellik listesi - dogruluk):** README.md, projenin sunduklari ozelliklerin bir listesini icermeli ve bu liste yalnizca gercekte var olan route'lardan/sablonlardan turetilmeli, uydurma ozellik icermemeli. Listenin asagidaki maddelerin tamamini kapsamasi zorunludur (bunlarin her biri src/web/app.py'deki route'lar ve src/web/templates/ altindaki sablonlarla dogrulanabilir):
   - Kubernetes Explorer (kaynaklari listeleme, detay goruntuleme, YAML duzenleme, silme)
   - Privileged/Root konteyner tespiti
   - Riskli RBAC rol analizi (wildcard izinler)
   - Pod Exec olaylari izleme
   - ConfigMap/Secret veri aciga cikma taramasi
   - YAML Linter (Kubernetes manifest dogrulama)
   - Trivy Operator raporlari entegrasyonu
   - Harbor Trivy zafiyet sonuclari entegrasyonu
   - Prometheus metrik entegrasyonu (pod CPU/bellek metrikleri)
   - Service Mesh gorsellestime (pod-servis iletisim haritasi)
   - Workload yonetimi (Deployment, DaemonSet, StatefulSet, ReplicaSet, Job, CronJob)
   - Node izleme
   - Coklu kume destegi (kubeconfig yonetimi)
   - i18n destegi (Turkce/Ingilizce arayuz)
   - Swagger/OpenAPI dokumantasyonu (/apidocs/)
   - HPA, PDB, Lease, PriorityClass, RuntimeClass, ResourceQuota, LimitRange, NetworkPolicy yonetimi

**AC-04 (Kurulum talimatlari):** README.md, asagidaki komutlari Makefile'daki gercek hedeflerle birebir eslesen sekilde icermeli:
   - `make venv` (Python sanal ortam olusturma)
   - `make install` (requirements.txt bagimliliklari kurma)
   - `make run` (uygulamayi 0.0.0.0:8080 uzerinde baslatma)
   - `make run-dev` (gelistirme modunda baslatma)
   - Docker ile calistirma: `docker build -t kube-sec .` ve `docker run` komutu
   - Python versiyonu (3.9+, Dockerfile'daki python:3.9-slim'den dogrulanabilir)

**AC-05 (Onkosuller):** README.md, uygulamanin calisabilmesi icin gerekli onkosullari acikca belirtmeli: (a) Python 3.9+ kurulu olmali, (b) calisan bir Kubernetes kumesine erisim icin gecerli kubeconfig dosyasi gerekli, (c) Docker kurulumu (Docker ile calistirma icin, opsiyonel).

**AC-06 (Kubeconfig yonetimi bolumu):** README.md, coklu kume desteginin nasil calistigini aciklayan bir bolum icermeli. Bu bolum su bilgileri kapsamali: (a) kubeconfig dosyalarinin uygulama icinden yuklenebilecegi, (b) KUBECONFIG ortam degiskeninin desteklendigi, (c) aktif kumenin tarayici oturumu bazinda secilebildigi.

**AC-07 (Guvenlik uyarilari):** README.md, su guvenlik bildirimlerini acikca belirten bir bolum veya uyari kutusu icermeli: (a) kubeconfigs/ dizininin gercek kume kimlik bilgileri icerebilecegi ve git'e commit edilmemesi gerektigi, (b) .pem/.key dosyalarinin .gitignore tarafindan haric tutuldugu, (c) uygulamanin varsayilan olarak TLS dogrulama kapatilmis (verify_ssl=False) calistigi (bu, app.py'deki tum route handler'larda dogrulanabilir).

### Orta Gereksinimler

**AC-08 (Paketleme/masaustu build bolumu):** README.md, masaustu uygulamasi olarak paketleme surecini ozetleyen bir bolum icermeli. Bu bolum su bilgileri kapsamali: (a) PyInstaller ile .app paketlendigini, (b) `make build-macos`, `make build-macos-arm`, `make build-macos-intel` hedeflerinin var oldugunu, (c) `make sign`, `make notarize`, `make dmg`, `make release-macos` akisini, (d) Windows build scriptlerinin (build-windows.sh/build-windows.ps1) var oldugunu. Tam env degiskeni detaylarina girilmesine gerek yok; Makefile'a referans vermek yeterlidir.

**AC-09 (Versiyon bilgisi):** README.md, mevcut versiyonun VERSION dosyasindan ogrenilebildigini ve `make version-show`, `make bump-patch|bump-minor|bump-major` komutlarinin varligini belirtmeli.

**AC-10 (API dokumantasyonu referansi):** README.md, uygulamanin calisir durumda olduguunda /apidocs/ adresinde Swagger UI ile otomatik uretilmis API dokumantasyonuna erisilebilecegini belirten bir satir icermeli.

**AC-11 (Mimari ozeti):** README.md, projenin teknik mimarisini kisa bir paragrafta (veya madde listesinde) ozetlemeli. En az su bilgileri kapsamali: (a) Flask monolitik tek dosya yaklasimi (src/web/app.py), (b) Jinja2 sunucu tarafli sablonlar (src/web/templates/), (c) resmi kubernetes Python istemcisi uzerinden API erisimi, (d) arka plan cache thread'leri ile performans optimizasyonu.

**AC-12 (Lisans bolumu):** Repo kokunde LICENSE dosyasi bulunmadigi icin (dogrulanmistir), README.md'de "License" basliginda "Bu proje henuz bir lisans belirlemedi. Katki saglamadan once proje sahibiyle iletisime gecin." anlaminda bir not yer almali. Ya da proje sahibi bir lisans turu belirleyip ayri bir LICENSE dosyasi eklenmeli -- bu karar acik soru olarak PM'in kullaniciya sormasi gereken bir maddedir.

### Nice-to-have Gereksinimler

**AC-13 (Ekran goruntusu / demo):** README.md, ekran goruntusu icin bir placeholder bolumu icermeli (ornegin "## Screenshots" basligi altinda "Screenshots will be added soon" veya benzeri bir not). Gercek ekran goruntuleri bu spec'in kapsami disindadir.

**AC-14 (Katki rehberi referansi):** README.md, "Contributing" basliginda katki yonergelerini iceren kisa bir paragraf veya "Katkilar memnuniyetle karsilanir, lutfen bir issue aciniz" gibi bir yonlendirme icermeli. Ayri bir CONTRIBUTING.md dosyasi bu spec'in kapsami disindadir.

**AC-15 (Badge'ler):** README.md'nin en ustunde Python versiyonu, Flask ve lisans (lisans belirlendiginde) icin badge'ler yer alabilir. Bu zorunlu degildir; ancak eklenmesi durumunda dogru teknik bilgiyi yansitmalidir.

**AC-16 (Ortam degiskenleri tablosu):** README.md, uygulamanin kabul ettigi ortam degiskenlerini bir tabloda listeleyebilir: APP_SECRET_KEY, KUBECONFIG, PROMETHEUS_URL, NO_AUTO_BROWSER, APP_PORT, FLASK_ENV. Bu zorunlu degildir ancak eklenirse her birinin kaynak koddaki karsiligi dogrulanabilir olmalidir.

---

## Kapsam Disi

- Gercek ekran goruntulerinin olusturulmasi (sadece placeholder)
- Ayri bir CONTRIBUTING.md dosyasi
- Ayri bir README.tr.md (Turkce ceviri)
- LICENSE dosyasinin oluisturulmasi (lisans secimi kullanicinin kararidir)
- Kod degisikligi veya yeni ozellik implementasyonu
- Next.js/shadcn proje iskeleti hakkinda bilgi (bu calismiyor ve README'de yer almamalidir)
- CLAUDE.md veya context.md dosyalarina referans (bunlar dahili gelistirme dosyalaridir, .gitignore'da haric tutulmustur)

---

## Onerilen README.md Basliklari (H2 iskeleti)

```
# Kube-Sec

(Kisa tanitim paragrafi + varsa badge'ler)

## Features

## Prerequisites

## Installation

## Running the Application
  ### Local Development
  ### Docker
  ### Desktop Application (macOS / Windows)

## Configuration
  ### Kubeconfig Management
  ### Environment Variables

## Security Notes

## Architecture Overview

## API Documentation

## Packaging & Release

## Version Management

## Screenshots

## Contributing

## License
```

---

## Acik Sorular / Riskler

1. **[KARAR GEREKLI] Lisans secimi:** Repo'da LICENSE dosyasi yok. Acik kaynak projeler icin bir lisans (MIT, Apache 2.0, GPL vb.) secilmesi gerekiyor. Bu karar proje sahibine ait; README'deki lisans bolumu bu karara bagli.

2. **[KARAR GEREKLI] Ekran goruntuleri:** Gercek ekran goruntuleri README'nin cezbediciligi icin onemlidir. Placeholder mi konulsun yoksa ilk surumde ekran goruntuleri de mi eklensin?

3. **[RISK] verify_ssl=False:** Uygulamanin tum Kubernetes API cagrilarinda TLS dogrulamayi kapatmasi, guvenlik uyarilarinda belirtilmesi gereken bilinen bir durumdur. README'deki guvenlik notlari bolumu bu konuda bilgi icermeli.

4. **[RISK] Varsayilan secret key:** app.secret_key varsayilan olarak 'dev-secret' kullaniyor (app.py:44). Bu, README'nin guvenlik notlarinda veya konfigürasyon bolumunde belirtilmeli (APP_SECRET_KEY ortam degiskeninin uretimde degistirilmesi gerektigi).

---

## Aksion Listesi

1. [ ] Proje sahibinden lisans tercihi alinmali (MIT, Apache 2.0, GPL vb.)
2. [ ] Ekran goruntusu stratejisi karari (placeholder mi, ilk surumde gercek ekran goruntuleri mi)
3. [ ] technical-writer agent bu spec'teki AC-01 -- AC-16 kriterlerine gore README.md dosyasini olusturmali
4. [ ] qa-engineer agent, olusturulan README.md'yi her bir kabul kriterine gore CONFIRMED/FAILED olarak dogrulamali
