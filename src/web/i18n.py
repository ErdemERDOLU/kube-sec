"""i18n.py — Çeviri sözlüğü ve yardımcı fonksiyon.

Import zinciri:  kubeconfig_manager  <-  background.py  <-  blueprint'ler  <-  app.py
Bu modül Flask'a bağımlı değildir; sadece saf Python dict ve fonksiyon içerir.
"""

# --- Simple i18n setup ---
I18N = {
    'nav.home': {'tr': 'Ana Sayfa', 'en': 'Home'},
    'nav.security': {'tr': 'Güvenlik', 'en': 'Security'},
    'nav.mesh': {'tr': 'Mesh Görselleştirme', 'en': 'Mesh Visualization'},
    'nav.vulns': {'tr': 'Zafiyetler', 'en': 'Vulnerabilities'},
    'nav.exec': {'tr': 'Pod Exec Olayları', 'en': 'Pod Exec Events'},
    'nav.priv': {'tr': 'Privileged/Root/RBAC', 'en': 'Privileged/Root/RBAC'},
    'nav.cmsecrets': {'tr': 'ConfigMap Gizli Bilgi', 'en': 'ConfigMap Secret Data'},
    'nav.yamllint': {'tr': 'YAML Linter', 'en': 'YAML Linter'},
    'nav.trivyoperator': {'tr': 'Trivy Operator Raporları', 'en': 'Trivy Operator Reports'},
    'nav.explorer': {'tr': 'Kubernetes Explorer', 'en': 'Kubernetes Explorer'},
    'nav.nodes': {'tr': "Node's", 'en': 'Nodes'},
    'nav.workloads': {'tr': 'Workloads', 'en': 'Workloads'},
    'nav.config': {'tr': 'Config', 'en': 'Config'},
    'nav.network': {'tr': 'Network', 'en': 'Network'},
    'nav.storage': {'tr': 'Storage', 'en': 'Storage'},
    'nav.access': {'tr': 'Access Control', 'en': 'Access Control'},
    'nav.configuration': {'tr': 'Configuration', 'en': 'Configuration'},
    'theme.toggle': {'tr': 'Tema Değiştir', 'en': 'Toggle Theme'},
    'footer.created': {'tr': 'Oluşturan', 'en': 'Created by'},
    'footer.app': {'tr': 'Kubernetes Security Checker', 'en': 'Kubernetes Security Checker'},
    'brand': {'tr': 'Kube-Sec', 'en': 'Kube-Sec'},
    'loading': {'tr': 'Yükleniyor...', 'en': 'Loading...'},
    'label.namespace': {'tr': 'Namespace:', 'en': 'Namespace:'},
    # Home page
    'home.page_title': {'tr': 'Ana Sayfa - Kubernetes Security Checker', 'en': 'Home - Kubernetes Security Checker'},
    'home.hero.title': {'tr': 'Kubernetes Security Checker', 'en': 'Kubernetes Security Checker'},
    'home.hero.lead': {
        'tr': 'Kubernetes ortamlarınızda güvenlik açıklarını tespit edin, ayrıcalıklı container kullanımlarını analiz edin ve cluster güvenliğinizi artırın.',
        'en': 'Detect security issues in your Kubernetes environments, analyze privileged container usage, and improve your cluster security.'
    },
    'home.hero.btn.mesh': {'tr': 'Mesh Görselleştirme', 'en': 'Visualize Mesh'},
    'home.hero.btn.scan': {'tr': 'Zafiyetleri Tara', 'en': 'Scan Vulnerabilities'},
    # Features
    'home.feat.security.title': {'tr': 'Güvenlik Analizi', 'en': 'Security Analysis'},
    'home.feat.security.text': {
        'tr': "Kubernetes cluster'ınızdaki güvenlik açıklarını, ayrıcalıklı container'ları ve RBAC risklerini detaylı olarak analiz edin.",
        'en': 'Analyze security issues in your Kubernetes cluster, privileged containers, and RBAC risks in detail.'
    },
    'home.feat.security.cta': {'tr': 'Analiz Et', 'en': 'Analyze'},

    'home.feat.mesh.title': {'tr': 'Network Mesh', 'en': 'Network Mesh'},
    'home.feat.mesh.text': {
        'tr': 'Pod iletişimlerini, service bağlantılarını ve network topolojisini interaktif grafiklerle görselleştirin.',
        'en': 'Visualize pod communications, service connections, and network topology with interactive graphs.'
    },
    'home.feat.mesh.cta': {'tr': 'Görselleştir', 'en': 'Visualize'},

    'home.feat.explorer.title': {'tr': 'Kubernetes Explorer', 'en': 'Kubernetes Explorer'},
    'home.feat.explorer.text': {
        'tr': 'Cluster kaynaklarınızı keşfedin, YAML dosyalarını düzenleyin ve pod loglarını gerçek zamanlı takip edin.',
        'en': 'Explore cluster resources, edit YAML files, and follow pod logs in real time.'
    },
    'home.feat.explorer.cta': {'tr': 'Keşfet', 'en': 'Explore'},

    'home.feat.workloads.title': {'tr': 'Workload Yönetimi', 'en': 'Workload Management'},
    'home.feat.workloads.text': {
        'tr': "Deployment'ları, DaemonSet'leri ve Pod'ları merkezi bir arayüzden yönetin ve durumlarını izleyin.",
        'en': 'Manage Deployments, DaemonSets, and Pods from a central interface and monitor their status.'
    },
    'home.feat.workloads.cta': {'tr': 'Yönet', 'en': 'Manage'},

    'home.feat.nodes.title': {'tr': 'Node Monitoring', 'en': 'Node Monitoring'},
    'home.feat.nodes.text': {
        'tr': "Kubernetes node'larınızın kaynak kullanımını, durumunu ve performans metriklerini izleyin.",
        'en': 'Monitor resource usage, status, and performance metrics of your Kubernetes nodes.'
    },
    'home.feat.nodes.cta': {'tr': 'İzle', 'en': 'Monitor'},

    'home.feat.linter.title': {'tr': 'YAML Linter', 'en': 'YAML Linter'},
    'home.feat.linter.text': {
        'tr': 'Kubernetes YAML dosyalarınızı doğrulayın, syntax hatalarını tespit edin ve best practice önerilerini alın.',
        'en': 'Validate your Kubernetes YAML files, detect syntax errors, and get best practice recommendations.'
    },
    'home.feat.linter.cta': {'tr': 'Doğrula', 'en': 'Validate'},

    # About section
    'home.about.title': {'tr': 'Uygulama Hakkında', 'en': 'About the Application'},
    'home.about.lead': {
        'tr': 'Bu uygulama, Kubernetes ortamlarında güvenlik açıklarını, ayrıcalıklı container kullanımlarını, root kullanıcı risklerini, RBAC (Role-Based Access Control) riskli rolleri ve pod exec olaylarını merkezi bir web arayüzünde görselleştirmek için geliştirilmiştir.',
        'en': 'This application is built to visualize security issues in Kubernetes environments, privileged container usage, root user risks, risky RBAC roles, and pod exec events in a central web interface.'
    },
    'home.about.goal': {
        'tr': 'Amacımız: Kubernetes yöneticilerinin ve DevOps ekiplerinin, cluster güvenliğini kolayca analiz edebilmesi ve riskli alanları hızlıca tespit edebilmesidir. Ağ topolojisi, pod iletişimi ve güvenlik zafiyetleri tek ekranda sunulur.',
        'en': 'Our goal: Enable Kubernetes admins and DevOps teams to easily analyze cluster security and quickly identify risky areas. Network topology, pod communication, and security vulnerabilities are presented on a single screen.'
    },
    'home.about.footer': {
        'tr': 'One Plus Mon ekibi olarak, bulut ve konteyner güvenliği alanında açık kaynak çözümler üretmekteyiz.',
        'en': 'As the One Plus Mon team, we produce open-source solutions in cloud and container security.'
    },
    'home.oss.title': {'tr': 'Açık Kaynak', 'en': 'Open Source'},
    'home.oss.desc': {
        'tr': 'Topluluk katkısı ile geliştirilen güvenli Kubernetes altyapıları için.',
        'en': 'For secure Kubernetes infrastructures developed with community contributions.'
    },
    # PSS / PSA analysis page — flat key names matching pod_security_standards.html template
    'nav.pss': {'tr': 'Pod Security Standards', 'en': 'Pod Security Standards'},
    'pss.title': {'tr': 'Pod Security Standards (PSA) Analizi', 'en': 'Pod Security Standards (PSA) Analysis'},
    'pss.subtitle': {
        'tr': "Namespace'lerin PSA etiketlerini ve pod uyumluluk durumunu görüntüleyin.",
        'en': 'View PSA labels and pod compliance status for each namespace.'
    },
    'pss.no_label': {'tr': 'Tanımlanmamış', 'en': 'Undefined'},
    'pss.compliant': {'tr': 'Uyumlu', 'en': 'Compliant'},
    'pss.noncompliant': {'tr': 'Uyumsuz', 'en': 'Non-compliant'},
    'pss.profile.privileged': {'tr': 'Privileged', 'en': 'Privileged'},
    'pss.profile.baseline': {'tr': 'Baseline', 'en': 'Baseline'},
    'pss.profile.restricted': {'tr': 'Restricted', 'en': 'Restricted'},
    'pss.disclaimer': {
        'tr': "Bu analiz MVP kural setiyle (9 kural) yapılmıştır; tam profil uyumluluğu için Kubernetes'in kendi PSA controller'ına başvurun.",
        'en': "This analysis is performed with an MVP rule set (9 rules); for full profile compliance refer to Kubernetes' own PSA controller."
    },
    'pss.loading': {'tr': 'PSA verileri yükleniyor...', 'en': 'Loading PSA data...'},
    'pss.error': {'tr': 'PSA verileri yüklenemedi.', 'en': 'Failed to load PSA data.'},
    # Özet kartlar
    'pss.psa_defined_ns': {'tr': 'PSA Etiketli NS', 'en': 'PSA Labeled NS'},
    'pss.noncompliant_pods_total': {'tr': 'Toplam Uyumsuz Pod', 'en': 'Total Non-compliant Pods'},
    'pss.unlabeled_ns': {'tr': 'Etiketsiz NS', 'en': 'Unlabeled NS'},
    # Tablo başlığı ve araç çubuğu
    'pss.table_title': {'tr': 'Namespace PSA Durumu', 'en': 'Namespace PSA Status'},
    'pss.hide_system_ns': {'tr': 'Sistem namespace\'lerini gizle', 'en': 'Hide system namespaces'},
    'pss.export_csv': {'tr': 'CSV Dışa Aktar', 'en': 'Export CSV'},
    'pss.refresh': {'tr': 'Yenile', 'en': 'Refresh'},
    # Tablo sütun başlıkları
    'pss.namespace': {'tr': 'Namespace', 'en': 'Namespace'},
    'pss.enforce': {'tr': 'Enforce Profili', 'en': 'Enforce Profile'},
    'pss.warn': {'tr': 'Warn Profili', 'en': 'Warn Profile'},
    'pss.audit': {'tr': 'Audit Profili', 'en': 'Audit Profile'},
    'pss.compliance_ratio': {'tr': 'Uyumluluk Oranı', 'en': 'Compliance Rate'},
    'pss.detail': {'tr': 'Detay', 'en': 'Detail'},
    # Filtre / sayfalama
    'pss.all': {'tr': 'Tümü', 'en': 'All'},
    'pss.pagination_label': {'tr': 'Sayfa', 'en': 'Page'},
    # Detay modalı
    'pss.detail_title': {'tr': 'Pod Uyumluluk Detayı', 'en': 'Pod Compliance Detail'},
    'pss.modal_close': {'tr': 'Kapat', 'en': 'Close'},
    'pss.loading_detail': {'tr': 'Detay yükleniyor...', 'en': 'Loading detail...'},
    'pss.not_computed': {'tr': 'Hesaplanmadı', 'en': 'Not computed'},
    'pss.no_violations': {'tr': 'İhlal yok', 'en': 'No violations'},
    'pss.detail_error': {'tr': 'Detay yüklenemedi.', 'en': 'Failed to load detail.'},
    # Boş durum mesajı
    'pss.no_psa_msg': {
        'tr': "Bu cluster'da PSA etiketi tanımlı namespace bulunamadı.",
        'en': 'No namespace with PSA labels found in this cluster.'
    },
    # Frontend hardcoded string temizliği için eklenen 7 ek flat key
    'pss.loading_generic': {'tr': 'Veriler yükleniyor...', 'en': 'Loading data...'},
    'pss.no_namespaces_found': {'tr': 'Hiç namespace bulunamadı.', 'en': 'No namespaces found.'},
    'pss.noncompliant_detected': {'tr': 'uyumsuz pod tespit edildi.', 'en': 'noncompliant pods detected.'},
    'pss.violations_label': {'tr': 'İhlaller', 'en': 'Violations'},
    'pss.preparing_analysis': {
        'tr': 'Analiz hazırlanıyor, lütfen birkaç saniye sonra yenileyin...',
        'en': 'Analysis is being prepared, please refresh in a few seconds...'
    },
    'pss.namespaces_loaded': {'tr': 'namespace yüklendi.', 'en': 'namespaces loaded.'},
    'pss.api_error_prefix': {'tr': 'API hatası: ', 'en': 'API error: '},
    # NetworkPolicy Kapsam Analizi
    'netpol.tab_title': {'tr': 'NetworkPolicy Kapsam', 'en': 'NetworkPolicy Coverage'},
    'netpol.coverage_title': {'tr': 'NetworkPolicy Kapsam Analizi', 'en': 'NetworkPolicy Coverage Analysis'},
    'netpol.coverage_subtitle': {'tr': "Namespace ve pod bazında NetworkPolicy kapsam durumunu görüntüleyin.", 'en': 'View NetworkPolicy coverage status by namespace and pod.'},
    'netpol.loading': {'tr': 'Kapsam verileri yükleniyor...', 'en': 'Loading coverage data...'},
    'netpol.error': {'tr': 'Kapsam verileri yüklenemedi.', 'en': 'Failed to load coverage data.'},
    'netpol.ns_coverage_pct': {'tr': 'Namespace Kapsam Oranı', 'en': 'Namespace Coverage Rate'},
    'netpol.pod_coverage_pct': {'tr': 'Pod Kapsam Oranı', 'en': 'Pod Coverage Rate'},
    'netpol.total_ns': {'tr': 'Toplam Namespace', 'en': 'Total Namespaces'},
    'netpol.covered_ns': {'tr': 'Korunan Namespace', 'en': 'Protected Namespaces'},
    'netpol.uncovered_ns': {'tr': 'Korumasız Namespace', 'en': 'Unprotected Namespaces'},
    'netpol.total_pods': {'tr': 'Toplam Pod', 'en': 'Total Pods'},
    'netpol.covered_pods': {'tr': 'Korunan Pod', 'en': 'Protected Pods'},
    'netpol.uncovered_pods': {'tr': 'Korumasız Pod', 'en': 'Unprotected Pods'},
    'netpol.ns_table_title': {'tr': 'Namespace NetworkPolicy Durumu', 'en': 'Namespace NetworkPolicy Status'},
    'netpol.col_namespace': {'tr': 'Namespace', 'en': 'Namespace'},
    'netpol.col_policy_count': {'tr': 'Policy Sayısı', 'en': 'Policy Count'},
    'netpol.col_total_pods': {'tr': 'Toplam Pod', 'en': 'Total Pods'},
    'netpol.col_covered_pods': {'tr': 'Korunan Pod', 'en': 'Protected Pods'},
    'netpol.col_uncovered_pods': {'tr': 'Korumasız Pod', 'en': 'Unprotected Pods'},
    'netpol.col_status': {'tr': 'Durum', 'en': 'Status'},
    'netpol.status_protected': {'tr': 'Korumalı', 'en': 'Protected'},
    'netpol.status_partial': {'tr': 'Kısmi Koruma', 'en': 'Partial'},
    'netpol.status_unprotected': {'tr': 'Korumasız', 'en': 'Unprotected'},
    'netpol.no_data': {'tr': 'Veri bulunamadı.', 'en': 'No data found.'},
    'netpol.hide_system_ns': {'tr': "Sistem namespace'lerini gizle", 'en': 'Hide system namespaces'},
    'netpol.refresh': {'tr': 'Yenile', 'en': 'Refresh'},
    'netpol.export_csv': {'tr': 'CSV Dışa Aktar', 'en': 'Export CSV'},
    'netpol.search_placeholder': {'tr': 'Namespace ara...', 'en': 'Search namespaces...'},
    'netpol.pod_detail_title': {'tr': 'Korumasız Pod Listesi', 'en': 'Unprotected Pod List'},
    'netpol.col_pod_name': {'tr': 'Pod Adı', 'en': 'Pod Name'},
    'netpol.col_pod_labels': {'tr': "Label'lar", 'en': 'Labels'},
    'netpol.modal_close': {'tr': 'Kapat', 'en': 'Close'},
    'netpol.preparing': {'tr': 'Analiz hazırlanıyor, lütfen birkaç saniye sonra yenileyin...', 'en': 'Analysis is being prepared, please refresh in a few seconds...'},
    'netpol.disclaimer': {
        'tr': 'Bu analiz matchLabels ve matchExpressions destekler; ancak podSelector dışındaki gelişmiş seçim mekanizmaları (örneği CRD tabanlı uzantılar) kapsam dışındadır.',
        'en': 'This analysis supports matchLabels and matchExpressions; however, advanced selection mechanisms beyond podSelector (e.g., CRD-based extensions) are out of scope.',
    },
    'error.cluster_checking': {'tr': 'Kubernetes baglantisi kontrol ediliyor', 'en': 'Checking Kubernetes connection'},
    'error.cluster_checking_msg': {'tr': "Cluster'a henuz baglanilamadi, kontrol devam ediyor...", 'en': 'Could not connect to cluster yet, checking...'},
    'error.retry': {'tr': 'Tekrar Dene', 'en': 'Retry'},
    'error.fetch_failed': {'tr': 'Veri alinamadi', 'en': 'Failed to fetch data'},
    'error.http_detail': {'tr': 'HTTP {status} hatasi', 'en': 'HTTP {status} error'},
    'cache.last_update': {'tr': 'Son guncelleme', 'en': 'Last updated'},
    'cache.ago': {'tr': 'once', 'en': 'ago'},
    'cache.seconds': {'tr': 'saniye', 'en': 'seconds'},
    'cache.minutes': {'tr': 'dakika', 'en': 'minutes'},
    'cache.stale_warning': {'tr': 'Gosterilen veri 5 dakikadan eski olabilir.', 'en': 'Displayed data may be older than 5 minutes.'},
    'cache.error_prefix': {'tr': 'Veri guncellenemedi', 'en': 'Data update failed'},
    'cache.error_stale_data': {'tr': 'gosterilen veri eski olabilir.', 'en': 'displayed data may be outdated.'},
    'cache.just_now': {'tr': 'az once', 'en': 'just now'},
    'cache.live_data': {'tr': 'Canli veri', 'en': 'Live data'},
    # YAML Linter
    'yaml_linter.empty_content': {'tr': 'YAML içeriği boş', 'en': 'YAML content is empty'},
}


def translate(key: str, lang: str) -> str:
    try:
        d = I18N.get(key)
        if not d:
            return key
        return d.get(lang) or d.get('tr') or key
    except Exception:
        return key
