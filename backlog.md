# Kube-Sec Backlog

> Oluşturma tarihi: 2026-07-05
> Analiz kapsamı: 22 şablon dosyası (`src/web/templates/*.html`), `src/web/app.py` (~5.474 satır, 119 route), `src/web/static/pod_describe.js`, I18N sözlüğü

---

## [Öncelik: Yüksek] 1. Hata Durumlarının Kullanıcıya Tutarsız Gösterilmesi

**Kategori:** UX
**Mevcut durum:**
- `base.html:648-745` cluster health toast'u ancak 30 saniye sürekli başarısızlık sonrası görünür (`FAILURE_THRESHOLD = 30000`). İlk 30 saniye boyunca kullanıcı hiç geri bildirim almaz.
- `exec_events.html:39-41` hata durumunda sadece "Hata oluştu." yazısı gösterilir; hata detayı yok, retry butonu yok.
- `vulnerabilities.html:376-382` `exportDeploymentReport()` ve `viewDeploymentDetails()` fonksiyonları `alert()` ile "yakında eklenecek" gösteriyor -- bu, kullanıcının tıklanabilir butonları gerçek işlevsellik sanmasına yol açıyor.
- `k8s_explorer.html:246-249` `fetchApi()` fonksiyonu HTTP durum kodu kontrolü yapmadan direkt `resp.json()` çağırıyor; 403/401/500 dönerse sessiz bir JSON parse hatası oluşur.

**Sorun:** 403 Forbidden gibi kimlik doğrulama hataları kullanıcıya hiç veya çok geç gösteriliyor. Kullanıcı, cluster bağlantısının kesildiğini veya yetkisiz olduğunu anlayamıyor.

**Kabul kriterleri:**
- [x] Cluster health check başarısız olduğunda ilk 5 saniye içinde kullanıcıya görsel bir uyarı (banner veya toast) gösterilir.
- [x] Tüm sayfa bazlı fetch çağrılarında (en az 15 farklı template'teki fetch blokları) HTTP 401/403/500 yanıtı için açıklayıcı hata mesajı gösterilir; `"Hata oluştu"` gibi genel mesajlar yerine HTTP durum kodu ve backend'den dönen hata metni kullanıcıya iletilir.
- [x] `vulnerabilities.html` içindeki `exportDeploymentReport` ve `viewDeploymentDetails` butonları ya gerçek işlevselliğe kavuşturulur ya da kullanıcıya görünmez yapılır (buton DOM'dan kaldırılır).
- [x] `k8s_explorer.html` içindeki `fetchApi()` fonksiyonunda `resp.ok` kontrolü eklenir ve başarısız HTTP durumları kullanıcıya gösterilir.

---

## [Öncelik: Yüksek] 2. i18n Kapsamındaki Büyük Eksiklikler

**Kategori:** i18n
**Mevcut durum:**
- `k8s_explorer.html`: Tüm arayüz metinleri hardcoded Türkçe (örnek: satır 12 "Kubernetes kaynaklarınızı keşfedin ve yönetin", satır 267 "Ingress Listesi", satır 283-285, satır 382 "Geri", satır 840 "Yükleniyor..."). `t()` fonksiyonu hiç kullanılmıyor.
- `access_control.html`: Hardcoded İngilizce (satır 8 "Access Control", satır 82 "No ${label} found", satır 14-18 tab etiketleri).
- `network.html`: Tamamen hardcoded İngilizce (satır 15 "Network Dashboard", satır 75-76 "Search services...", satır 831-840 empty state mesajları).
- `trivy_operator.html`: Tamamen hardcoded İngilizce (satır 409 başlık, satır 480 "No vulnerability reports found", satır 499 Note kutusu).
- `storage.html`: Karışık İngilizce/Türkçe (satır 183 "No ${label} found", satır 9 Türkçe açıklama).
- `exec_events.html`: Hardcoded Türkçe, `t()` kullanılmıyor (satır 2, 15-16, 29-30).
- `harbor_trivy.html`: Hardcoded Türkçe başlık (satır 3), İngilizce/Türkçe karışık.
- `configmap_secrets.html`: Tüm metinler hardcoded Türkçe (satır 244-245, satır 311-315).
- `base.html:521-523` footer "Created by One Plus Mon" hardcoded İngilizce.
- `app.py:82-179` I18N sözlüğünde yalnızca ~40 anahtar var; UI'da en az 200+ farklı metin string'i mevcut.

**Sorun:** Uygulama iki dil destekliyor (TR/EN) ancak sayfaların büyük çoğunluğu bu sistemden geçmiyor. Dil değiştirme kullanıcıya yanlış bir beklenti oluşturuyor; İngilizce'ye geçildiğinde sayfaların %70'inden fazlası hâlâ Türkçe veya karışık görünüyor.

**Kabul kriterleri:**
- [x] Tüm 22 şablon dosyasındaki kullanıcıya görünen statik metinler `t()` fonksiyonu üzerinden I18N sözlüğüne bağlanır.
- [x] I18N sözlüğüne en az 150 yeni anahtar eklenir (mevcut ~40 üzerine).
- [x] Dil EN olarak seçildiğinde hiçbir sayfada Türkçe hardcoded metin kalmaz (JS içindeki `alert()` mesajları dahil).
- [x] Dil TR olarak seçildiğinde hiçbir sayfada İngilizce hardcoded metin kalmaz.

---

## [Öncelik: Yüksek] 3. Stub (Yer Tutucu) Şablon Dosyalarının Temizlenmesi

**Kategori:** Teknik Borç
**Mevcut durum:**
- `workloads_overview.html` (7 satır): Sadece "Genel özet ve istatistikler burada gösterilecek." yazıyor.
- `workloads_deployments.html` (7 satır): Sadece "Tüm deployments burada listelenecek." yazıyor.
- `workloads_daemonsets.html` (7 satır): Sadece "Tüm DaemonSet'ler burada listelenecek." yazıyor.
- `workloads_pods.html` (7 satır): Sadece "Tüm podlar burada listelenecek." yazıyor.
- Bu 4 dosya için karşılık gelen route'lar `app.py`'de tarandığında, render ediliyor olabilirler ancak gerçek `workloads.html` (2490 satır) tüm işlevselliği içeriyor.

**Sorun:** Kullanıcı yanlış URL'ye ulaşırsa boş bir sayfa ile karşılaşır. Bakımcı için hangi dosyanın gerçek olduğu belirsizleşir.

**Kabul kriterleri:**
- [x] 4 stub şablon dosyası silinir veya ana `workloads.html`'e yönlendiren redirect route'ları eklenir.
- [x] Silinen/yönlendirilen dosyalar için `app.py`'deki render_template çağrıları güncellenir.
- [x] Silme sonrası uygulama hatasız başlar ve workloads sayfası tam işlevsel kalır.

---

## [Öncelik: Yüksek] 4. Güvenlik: Pod Security Standards (PSS/PSA) Analiz Ekranı

**Kategori:** Güvenlik
**Mevcut durum:**
- `privileged_containers.html` yalnızca `privileged: true` ve `runAsUser: 0 / runAsNonRoot: false` kontrollerini yapıyor.
- Kubernetes 1.25+ ile enforce edilen Pod Security Standards (Baseline, Restricted profilleri) için bir analiz veya uyumluluk raporu yok.
- Namespace'lere atanmış PSA etiketlerini (`pod-security.kubernetes.io/enforce`, `warn`, `audit`) gösterecek bir ekran yok.

**Sorun:** Kullanıcı, cluster'ındaki namespace'lerin hangi güvenlik profiline uygun olduğunu göremez; yalnızca tekil container özelliklerini tablo şeklinde görüyor ama bütünsel uyumluluk resmi eksik.

**Kabul kriterleri:**
- [x] Yeni bir ekran veya mevcut `privileged_containers.html` içerisinde bir tab eklenir: her namespace için PSA etiketlerini (`enforce`, `warn`, `audit`) ve seviyelerini (`privileged`, `baseline`, `restricted`) listeler.
- [x] PSA etiketi atanmamış namespace'ler "Uyumsuz" veya "Tanımlanmamış" olarak işaretlenir.
- [x] Her namespace için mevcut pod'ların seçilen profille uyumluluğu (uyumlu pod sayısı / toplam pod sayısı) gösterilir.

---

## [Öncelik: Yüksek] 5. NetworkPolicy Kapsam Analizi

**Kategori:** Güvenlik
**Mevcut durum:**
- `network.html:180-204` "Network Policies" tab'ı mevcut ancak yalnızca mevcut policy'leri listeler.
- Hangi namespace'lerde hiç NetworkPolicy tanımlanmadığını, hangi pod'ların hiçbir policy tarafından korunmadığını göstermez.
- Cluster genelinde "NetworkPolicy kapsam oranı" gibi bir metrik yok.

**Sorun:** NetworkPolicy olmayan namespace'ler varsayılan olarak tüm trafiğe açıktır; bu, lateral movement için büyük bir risk oluşturur. Kullanıcı bu riskin farkında olmuyor.

**Kabul kriterleri:**
- [x] Network ekranında veya ayrı bir güvenlik kontrol sayfasında, tüm namespace'ler için NetworkPolicy varlık durumu gösterilir (var/yok).
- [x] NetworkPolicy bulunmayan namespace'ler kırmızı uyarı ile işaretlenir.
- [x] "Korumasız pod" sayısı gösterilir: hiçbir NetworkPolicy'nin `podSelector`'ına uymayan pod'lar listelenir.
- [x] Cluster geneli kapsam oranı (NetworkPolicy olan namespace sayısı / toplam namespace sayısı * 100) hesaplanır ve gösterilir.

---

## [Öncelik: Orta] 6. Tekrarlanan Yardımcı Fonksiyonlar (JS Kod Tekrarı)

**Kategori:** Teknik Borç
**Mevcut durum:**
- `showToast()` fonksiyonu en az 5 farklı template'te ayrı ayrı tanımlanmış: `access_control.html:85`, `network.html:979-997`, `storage.html:197-208`, `config.html:886-924`, ve `base.html:759-771`.
- `escapeHtml()` fonksiyonu en az 4 farklı template'te tekrarlanıyor: `access_control.html:84`, `network.html:999-1004`, `storage.html:280-282`, `privileged_containers.html:291-295`.
- `timeAgo()` fonksiyonu en az 3 farklı template'te tekrarlanıyor: `access_control.html:83`, `network.html:1091-1101`, `storage.html:186-195`.
- `openConfirmModal()` / confirm deseni en az 4 farklı template'te farklı implementasyonlarla tekrarlanıyor.

**Sorun:** Bir hata düzeltmesi veya davranış değişikliği yapıldığında tüm kopyalar ayrı ayrı güncellenmeli; bu, tutarsızlıklara ve regresyonlara yol açar.

**Kabul kriterleri:**
- [x] `showToast()`, `escapeHtml()`, `timeAgo()` ve `openConfirmModal()` fonksiyonları tek bir paylaşılan JS dosyasına (`src/web/static/common.js` veya benzeri) taşınır.
- [x] Tüm template'ler bu paylaşılan dosyayı `<script src=...>` ile yükler ve yerel kopyalar kaldırılır.
- [x] Fonksiyon imzaları ve davranışları tüm template'lerde tutarlı hale gelir (örneğin toast süresi, toast renkleri).

---

## [Öncelik: Orta] 7. exec_events.html Ekranının Modernizasyonu

**Kategori:** UX
**Mevcut durum:**
- `exec_events.html` (44 satır) tüm sayfalar arasında en basit ve en az bakım görmüş olanıdır.
- Loading state yok -- "Yükleniyor..." statik metin olarak yazılmış, spinner animasyonu yok (satır 18).
- Hata durumunda "Hata oluştu." tek satır metin (satır 40), hata detayı gösterilmiyor.
- Filtreleme, arama, pagination yok.
- Inline `<style>` bloğu diğer sayfalardan çok farklı bir görsel dile sahip (satır 7-13, düz CSS, `base.html` kartı kullanılmıyor).
- `base.html` layout'undaki card, shadow, gradient başlık gibi ortak görsel öğeleri kullanılmıyor.

**Sorun:** Diğer sayfalardaki modern UX ile karşılaştırıldığında bu ekran çok basit ve tutarsız kalır. Exec olayları güvenlik açısından kritik olmasına rağmen kullanıcıya kötü bir deneyim sunuyor.

**Kabul kriterleri:**
- [x] Sayfa, diğer sayfalardaki görsel dile uygun hale getirilir (card yapılarını, gradient başlık, badge'ler kullanır).
- [x] Veri yüklenirken spinner animasyonu gösterilir.
- [x] Hata durumunda, HTTP durum kodu ve hata mesajı içeren bir alert kutusu gösterilir.
- [x] Namespace bazlı filtreleme eklenir.
- [x] Olay sayısı 50'den fazla olduğunda pagination uygulanır.

---

## [Öncelik: Orta] 8. YAML Linter Ekranının Geliştirilmesi

**Kategori:** UX
**Mevcut durum:**
- `yaml_linter.html` (34 satır) son derece minimal: bir textarea, bir buton ve sonuç div'i.
- Dosya yükleme (file upload) desteği yok.
- Lint sonucu yalnızca "YAML geçerli!" veya ham hata metni gösteriyor; satır numarası, hata pozisyonu gibi detaylar yok.
- Kubernetes best practice kontrolü (örneğin `latest` tag kullanımı, kaynak limit eksikliği) yapılmıyor -- yalnızca YAML syntax kontrolü.

**Sorun:** YAML linter, diğer sayfaların zenginliğine kıyasla çok kısıtlı bir işlevsellik sunuyor. Kullanıcının hatayı bulması için satır numarası bilgisi sunulmuyor.

**Kabul kriterleri:**
- [x] Dosya sürükle-bırak veya dosya seçici ile `.yaml`/`.yml` dosyası yükleme desteği eklenir.
- [x] Lint hatalarında satır numarası ve kolon pozisyonu gösterilir.
- [x] Başarılı lint sonucunda "geçerli Kubernetes manifesti" kontrolü yapılır (apiVersion, kind alanlarının varlığı).
- [x] Hata olan satır textarea'da vurgulanır veya satır numarasına scroll yapılır.

---

## [Öncelik: Orta] 9. Export / Rapor Alma Özelliğinin Tamamlanması

**Kategori:** Operasyonel
**Mevcut durum:**
- `privileged_containers.html:307-333` CSV export işlevselliği mevcut (`exportTable()` fonksiyonu).
- `vulnerabilities.html:375-377` "Rapor İndir" butonu tıklandığında `alert("yakında eklenecek")` gösteriyor -- işlevsiz.
- Diğer ekranlarda (workloads, nodes, access_control, network, storage) hiçbir export/indirme butonu yok.
- PDF rapor oluşturma özelliği hiçbir ekranda yok.

**Sorun:** Kullanıcı, güvenlik denetimi veya uyumluluk raporlaması için verileri dışarı aktaramıyor. Yalnızca bir ekranda kısmen çalışan bir CSV export var.

**Kabul kriterleri:**
- [x] En az 5 ekranda (privileged_containers, vulnerabilities, access_control, workloads, nodes) CSV export butonu çalışan şekilde eklenir.
- [x] `vulnerabilities.html`'deki "Rapor İndir" butonu gerçek bir CSV dosyası indirir.
- [x] Tüm export dosyalarında başlık satırı (header row) ve UTF-8 BOM bulunur (Türkçe karakter desteği).

---

## [Öncelik: Orta] 10. Kubeconfig Çoklu Kullanıcı / Çoklu Sekme Tutarsızlığı

**Kategori:** Teknik Borç
**Mevcut durum:**
- `app.py:229-384` (CLAUDE.md'den) aktif kubeconfig hem Flask `session`'da (tarayıcı oturumu başına) hem de süreç-genel `KUBECONFIG_ACTIVE_GLOBAL` değişkeninde tutuluyor.
- `configuration.html:97` ile `activateCfg()` çağırıldığında `/kubeconfigs/activate` endpoint'i çağrılır ve bu, `session` + global değişkeni günceller.
- Aynı tarayıcıda iki farklı sekmede iki farklı cluster seçildiğinde, ikinci sekmenin aktivasyonu birinci sekmenin bağlam bilgisini de değiştirir (global değişken tek).
- Arka plan cache thread'leri (workload stats, pods summary, metrics sampler) global değişkeni okuduğu için, bir kullanıcının cluster değiştirmesi diğer tüm oturumları etkiler.

**Sorun:** Birden fazla kullanıcı veya aynı kullanıcının birden fazla sekmesi farklı cluster'larla çalışırken veri tutarsızlıkları yaşanır. Kullanıcı Cluster-A'ya bakarken Cluster-B verisi görebilir.

**Kabul kriterleri:**
- [x] Aktif kubeconfig'in hangi cluster'a ait olduğu her sayfanın üst çubuğunda görünür şekilde gösterilir (base.html'deki `activeContextBadge` şu an yalnızca health check ile dolduruluyor; her sayfa yüklendiğinde anında güncellenir).
- [x] Kubeconfig değiştiğinde, o anda açık olan sayfalardaki verinin eski cluster'a ait olabileceği konusunda kullanıcıya uyarı gösterilir veya sayfa otomatik yenilenir.
- [x] Dokümantasyona (CLAUDE.md veya README) çoklu kullanıcı/çoklu sekme sınırlılığı açıkça belgelenir.

---

## [Öncelik: Orta] 11. Cache Yenileme Durumunun Kullanıcıya Gösterilmesi

**Kategori:** UX
**Mevcut durum:**
- Arka plan cache thread'leri (`workload_stats_cache_refresher`, `pods_summary_cache_refresher`, `_metrics_sampler_loop`) belirli aralıklarla veriyi günceller.
- Kullanıcı sayfayı yüklerken verinin ne kadar eski olduğunu bilmez; "son güncelleme zamanı" gösterimi yok.
- Cache yenilemesi başarısız olursa (örneğin cluster bağlantısı koptuysa), eski veri sessizce sunulmaya devam eder.

**Sorun:** Kullanıcı, gördüğü verinin güncelliği hakkında bilgi sahibi değildir. Bayat veriyle karar alabilir.

**Kabul kriterleri:**
- [x] Cache destekli sayfalarda (workloads, nodes, pods) "Son güncelleme: X dakika önce" zaman damgası gösterilir.
- [x] Cache verisi 5 dakikadan eskiyse, sarı bir uyarı banner'ı gösterilir.
- [x] Cache yenileme hatası durumunda kullanıcıya "Veri güncellenemedi, gösterilen veri eski olabilir" mesajı iletilir.

---

## [Öncelik: Orta] 12. Güvenlik: Secret Değerlerinin UI'da Açık Gösterimi

**Kategori:** Güvenlik
**Mevcut durum:**
- `config.html:582-629` Secrets tab'ında secret değerleri decode edilmiş şekilde gösteriliyor (`showSecret` fonksiyonu ile modal'da).
- `configmap_secrets.html:397-400` ConfigMap içerisindeki şüpheli değerler (şifre, token) önizleme olarak tabloda gösteriliyor.
- Secret değerlerini görmek için ek bir yetki kontrolü veya onay adımı yok.

**Sorun:** Hassas veriler (şifreler, tokenlar, sertifika anahtarları) ekranda açık olarak görünür. Ekran paylaşımı veya omuz sörfü riski oluşturur.

**Kabul kriterleri:**
- [x] Secret değerleri varsayılan olarak maskelenmiş gösterilir (örneğin `*********`).
- [x] Değeri görmek için kullanıcı açık bir "Göster" butonuna tıklar; 30 saniye sonra değer otomatik olarak tekrar maskelenir.
- [x] ConfigMap suspect tablosundaki değer önizlemesi de maskelenmiş gösterilir; tam değeri görmek için tıklanması gerekir.

---

## [Öncelik: Orta] 13. Harbor Trivy Ekranında Kimlik Bilgisi Güvenliği

**Kategori:** Güvenlik
**Mevcut durum:**
- `harbor_trivy.html:11-14` Harbor kullanıcı adı ve şifresi düz metin input alanlarına giriliyor.
- `harbor_trivy.html:119` bu kimlik bilgileri JSON body içinde plaintext olarak backend'e POST ediliyor.
- Kimlik bilgileri tarayıcı geçmişinde veya network loglarında görünebilir.
- Oturum boyunca kimlik bilgileri saklanmıyor; kullanıcı her seferinde yeniden girmek zorunda.

**Sorun:** Kimlik bilgileri güvenli bir şekilde iletilmiyor ve saklanmıyor. Hassas credential'lar tarayıcı geliştirici araçları ile görülebilir.

**Kabul kriterleri:**
- [x] Şifre alanı `autocomplete="off"` ve `autocomplete="new-password"` niteliklerine sahip olur.
- [x] Backend, kimlik bilgilerini istek loglarında kayıt etmez (mevcut loglama kontrol edilir).
- [x] Harbor URL ve kullanıcı adı server-side session'da veya encrypted cookie'de saklanır, böylece kullanıcı her seferinde yeniden girmek zorunda kalmaz. Şifre asla client-side saklanmaz.

---

## [Öncelik: Düşük] 14. Mobil/Responsive Deneyim Eksiklikleri

**Kategori:** UX
**Mevcut durum:**
- `base.html:252-287` temel responsive breakpoint'ler tanımlanmış (sidebar mobilde gizleniyor, overlay var).
- Ancak `workloads.html` içerisindeki tab navigasyonu (satır 562-606, 8 adet tab butonu) dar ekranlarda taşma yapıyor.
- `config.html` tab navigasyonu da 10 adet tab butonu içeriyor (satır 476-530) ve dar ekranlarda taşacak şekilde tasarlanmış.
- `network.html:374-384` yalnızca filtre kontrolleri için mobil stil var; card grid'ler için yoktur.
- Tablo bazlı sayfalar (`privileged_containers.html`, `access_control.html`) `table-responsive` sınıfını kullanıyor ancak hücre genişlikleri sabit (`table-layout: fixed` ile ayarlanmış, örneğin `workloads.html:467-488`).

**Sorun:** Masaüstü uygulaması olmasına rağmen, tablet ve dar pencere kullanımında görsel taşmalar ve kullanılabilirlik sorunları oluşur.

**Kabul kriterleri:**
- [x] 768px genişlik altında tüm tab navigasyonları yatay scroll veya dropdown menüsüne dönüşür.
- [x] Tüm card grid'ler 576px altında tek sütuna düşerek tam genişlikte gösterilir.
- [x] Tüm tablo sayfalarında yatay scroll mevcut ve sabit sütun başlığı korunur.

---

## [Öncelik: Düşük] 15. Audit Trail (Değişiklik Geçmişi) Özelliği

**Kategori:** Operasyonel
**Mevcut durum:**
- Uygulama üzerinden Kubernetes kaynakları değiştirilebiliyor (YAML düzenle, scale, sil): `k8s_explorer.html:154-170` (YAML PATCH), `workloads.html` (scale deployment/statefulset), `access_control.html:79-80` (sil), `storage.html:251-278` (YAML kaydet, sil), `network.html:761-776` (sil), `config.html:1207-1281` (ConfigMap güncelle).
- Bu değişikliklerin hiçbiri uygulama tarafında kayıt altına alınmıyor. Kim, ne zaman, hangi kaynağı, nasıl değiştirdi bilgisi tutulmuyor.
- Kubernetes audit log'ları için bir görüntüleyici yok.

**Sorun:** Uyumluluk ve güvenlik denetimi için değişiklik geçmişi gereklidir. Bir sorun yaşandığında kimin hangi değişikliği yaptığının iz sürülememesi operasyonel riski artırır.

**Kabul kriterleri:**
- [x] Uygulama üzerinden yapılan her mutasyon işlemi (YAML güncelleme, silme, scale, ConfigMap düzenleme) en azından sunucu loguna kayıt edilir (tarih, kullanıcı/session, kaynak türü, kaynak adı, namespace, işlem türü).
- [x] UI'da bir "Son Değişiklikler" veya "Aktivite Geçmişi" görünümü eklenir; son 100 işlem listelenir.

---

## [Öncelik: Düşük] 16. Monolitik app.py Dosyasının Bölünmesi İçin Yol Haritası

**Kategori:** Teknik Borç
**Mevcut durum:**
- `src/web/app.py` ~5.474 satır ve 119 route içeriyor.
- Blueprint kullanılmıyor; tüm route'lar, iş mantığı, I18N sözlüğü, cache yönetimi ve yardımcı fonksiyonlar tek dosyada.
- Dosyanın açılması, aranması ve gezinilmesi IDE'lerde bile yavaşlıyor.
- Yeni bir özellik eklemek için dosyanın hangi bölümüne eklenmesi gerektiği belirsiz.

**Sorun:** Geliştirme hızı ve bakım kolaylığı azalıyor. Paralel geliştirme yapıldığında merge conflict olasılığı çok yüksek.

**Kabul kriterleri:**
- [x] En az aşağıdaki 5 alan için Flask Blueprint oluşturulur: (1) kubeconfig yönetimi, (2) workload route'ları, (3) güvenlik kontrol route'ları, (4) config/configuration route'ları, (5) k8s-explorer JSON API'leri.
- [x] I18N sözlüğü ayrı bir dosyaya (`src/web/i18n.py` veya benzeri) taşınır.
- [x] Cache yönetimi (background thread'ler, cache dict'leri) ayrı bir modüle taşınır.
- [x] Her Blueprint dosyası 1000 satırdan küçük olur.
- [x] Bölme sonrası uygulama hatasız başlar ve tüm mevcut route'lar çalışmaya devam eder.

---

## [Öncelik: Düşük] 17. Git Geçmişindeki Eski Rancher API Token'larının Temizlik Hijyeni

**Kategori:** Güvenlik
**Mevcut durum:**
- `.gitignore` dosyası bu oturumda oluşturuldu (`__pycache__/`, `kubeconfigs/`, `.DS_Store`, `node_modules/`, `dist/`, `build/`, `.env` vb. içeriyor).
- `kubeconfigs/mbs-dev`, `.DS_Store` ve 12 adet `.pyc` dosyası `git rm --cached` ile git takibinden çıkarıldı, commit'lendi ve `origin/main`'e push edildi.
- Kullanıcı, `kubeconfigs/mbs-dev` dosyasındaki iki Rancher API token'ının (`kubeconfig-user-dqghn96rqm:...` ve eski `kubeconfig-user-dqghngbpcj:...`, server: `https://rancher.sanstech.dev/k8s/clusters/c-m-f5dtndj9`) **artık geçersiz olduğunu doğruladı** (2026-07-05) — acil iptal ihtiyacı ortadan kalktı.
- Kalan tek konu: bu token değerleri hâlâ git geçmişinde (eski commit'lerde) ve GitHub'da metin olarak duruyor; `git rm --cached` bunları yalnızca gelecekteki commit'lerden çıkardı, geçmişten silmedi. Token'lar geçersiz olduğu için bu artık aktif bir risk değil, sadece bir temizlik/hijyen konusu.

**Sorun:** Geçersiz token'lar güvenlik açısından acil değil, ancak git geçmişinde credential-benzeri veri bırakmak kötü bir pratik ve gelecekte kafa karışıklığına (örn. "bu hâlâ geçerli mi?" sorusuna) yol açabilir.

**Kabul kriterleri:**
- [x] (Opsiyonel, düşük öncelik) `git filter-repo --path kubeconfigs/mbs-dev --invert-paths` (veya BFG Repo-Cleaner) ile geçersiz token değerleri git geçmişinden temizlenir ve tüm branch/tag'ler force-push edilir.
  - `main` dalı `git filter-repo` ile temizlenip force-push edildi (2026-07-20): eski SHA `7a09b0c` → yeni SHA `78f5a6d`. `kubeconfigs/mbs-dev` artık `main`'in hiçbir commit'inde yok (doğrulama: `git log --all --full-history -- kubeconfigs/` main üzerinde boş sonuç döndürüyor).
  - **Bilinçli istisna:** o sırada `v1.0.0-rc5` tag'i üzerinde canlı bir GitHub Actions release job'u çalıştığı için (`run 29734369408`), kullanıcı talebiyle bu tag rewrite/force-push kapsamı dışında bırakıldı — GitHub'da hâlâ eski (token içeren) commit'e (`7a09b0c`) işaret ediyor. Bu tag ileride ayrıca temizlenebilir (aynı `git filter-repo` + tek tag için hedefli force-push).
  - Ayrıca yerel-sadece (origin'e hiç push edilmemiş) `newfeature` dalı da eski geçmişi içeriyordu; sadece yerel bir referans olduğu ve zaten PR #1 ile `main`'e merge edilmiş olduğu için silindi.
  - **Bilinen kalıntı:** GitHub, merge edilmiş PR'ların (#1) commit/diff geçmişini kendi tarafında ayrıca önbelleğe alabiliyor; force-push sonrası bile PR #1'in sayfası eski commit içeriğini gösterebilir. Bu git seviyesinde düzeltilemez (GitHub destek talebi veya repo yeniden oluşturma gerektirir) — token zaten geçersiz olduğu için aktif risk taşımıyor.
- [x] Gelecekte benzer kazaların önüne geçmek için pre-commit secret scanner (gitleaks veya trufflehog) eklenir ve CI pipeline'ına entegre edilir.
  - Araç: `gitleaks v8.30.1` (resmi pre-commit hook + GitHub Actions action desteği).
  - `.pre-commit-config.yaml` (`gitleaks/gitleaks` hook, `rev: v8.30.1`) repo köküne eklendi.
  - `.gitleaks.toml` (allowlist: `backlog.md`, `docs/specs/`, `yaml/` ve konfigürasyon dosyalarının kendisi) repo köküne eklendi.
  - `.github/workflows/security-scan.yml` (her push + PR'da tetiklenen, ubuntu-latest, `gitleaks/gitleaks-action@v2`) eklendi — `release.yml`'den tamamen bağımsız.
  - `gitleaks detect --source . --config .gitleaks.toml -v` taraması 148 commit + tüm çalışma ağacında sıfır bulgu (exit code 0) döndürdü (2026-07-20).
  - README.md'ye pre-commit kurulum talimatı (Türkçe) eklendi.
