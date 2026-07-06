# Kube-Sec — Build Kılavuzu

> **Mevcut sürüm:** 1.0.0 | **Son güncelleme:** 2026-07-06

Bu belge, Kube-Sec'in macOS ve Windows için PyInstaller tabanlı masaüstü uygulaması olarak nasıl
derleneceğini, kod imzalanacağını, notarize edileceğini ve dağıtılacağını adım adım açıklar.
Makefile, `build_macos_app.sh`, `build-windows.ps1` ve `build-windows.sh` dosyalarını tek tek
okumak yerine bu belgeyi okuyarak sürece hakimiyet sağlayabilirsiniz.

---

## Hızlı Başlangıç (TL;DR)

### macOS — sade build

```bash
make venv && make install   # Sanal ortamı kur (bir kez)
make build-macos            # Uygulamayı paketle
# Çıktı: dist/Kube-Sec.app
```

### Windows — sade build (gerçek Windows ortamında çalıştırın)

```powershell
make venv && make install   # Sanal ortamı kur (bir kez)
make build-windows          # Uygulamayı paketle
# Çıktı: dist\Kube-Sec\Kube-Sec.exe
```

> **Kritik uyarı:** PyInstaller cross-compile desteği yoktur. Windows `.exe` üretmek için gerçek
> bir Windows ortamı (fiziksel makine, VM veya CI runner) gereklidir. macOS ya da Linux'ta
> `make build-windows` çalıştırmak Windows binary üretmez; platform-native binary üretir.

---

## Bölüm 1: Genel Bakış / Mimari Özeti

### launcher.py — Giriş Noktası

`launcher.py`, hem macOS hem de Windows paketlenmiş uygulamalarının tek giriş noktasıdır.
PyInstaller bu dosyayı `--onedir --windowed` seçenekleriyle paketler. Uygulama başlatıldığında
sırasıyla şunları gerçekleştirir:

1. **sys.path düzeltmesi:** Paketlenmiş ortamda (`sys.frozen = True`) bundle içindeki `src/`
   dizinini Python modül yoluna ekler; `_MEIPASS` altındaki kopyayı da kontrol eder.
2. **Otomatik port bulma:** 8080 numaralı port meşgulse 8081, 8082, ... şeklinde 30'a kadar
   deneyerek boş bir port seçer.
3. **127.0.0.1 bind:** Flask sunucusu yalnızca localhost adresine bağlanır; dış ağa açık değildir.
4. **Otomatik tarayıcı açma:** Paketlenmiş modda varsayılan tarayıcıyı `http://127.0.0.1:<port>`
   adresine yönlendirir. `NO_AUTO_BROWSER=1` ortam değişkeniyle bu davranış devre dışı bırakılabilir.
5. **Native pencere modu:** `USE_PYWEBVIEW=1` ortam değişkeni ile tarayıcı yerine `pywebview`
   tabanlı native pencere açılır. Bu modda Flask ayrı bir daemon thread'de çalışır ve `pywebview`
   ana thread'i bloklar; pencere kapanınca process sonlandırılır.

### İki Platformun Ortak ve Farklı Noktaları

| Özellik | macOS | Windows |
|---------|-------|---------|
| PyInstaller modu | `--onedir --windowed` | `--onedir --windowed` |
| Giriş noktası | `launcher.py` | `launcher.py` |
| Çıktı konumu | `dist/Kube-Sec.app` | `dist\Kube-Sec\Kube-Sec.exe` |
| İkon formatı | `.icns` (`sips` + `iconutil` ile üretilir) | `.ico` (repoda hazır olması beklenir) |
| Kod imzalama | `codesign` (Apple Developer ID sertifikası) | `signtool.exe` (Windows sertifikası) |
| Notarization | `xcrun notarytool` (Apple hesabı gerekli) | Yok |
| Dağıtım paketi | DMG (`hdiutil` ile) | Klasör / zip (opsiyonel) |

### Cross-Compile Kısıtı

**PyInstaller cross-compile desteği yoktur.** Bu kural değişmezdir:

- macOS binary (`dist/Kube-Sec.app`) yalnızca bir Mac'te derlenebilir.
- Windows binary (`dist/Kube-Sec/Kube-Sec.exe`) yalnızca gerçek bir Windows ortamında
  (fiziksel makine, Windows VM veya Windows CI runner) üretilebilir.
- macOS ya da Linux'ta `make build-windows` çalıştırılırsa hata vermez; ancak üretilen binary
  Windows'ta çalışmaz.

---

## Bölüm 2: Ön Koşullar

### Her İki Platform İçin

| Gereksinim | Minimum | Kurulum |
|------------|---------|---------|
| Python | 3.9+ | [python.org](https://python.org) veya `brew install python` (macOS) |
| pip bağımlılıkları | `requirements.txt` | `make venv && make install` |
| PyInstaller | — | `requirements.txt` içinde; yoksa `pip install pyinstaller` |

```bash
# Sanal ortam oluştur ve bağımlılıkları kur (bir kez yeterli)
make venv && make install
```

Manuel kurulum tercih edilirse:

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows'ta: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install pyinstaller            # requirements.txt'te yoksa ayrıca kur
```

### macOS İçin Ek Gereksinimler

Xcode Command Line Tools kurulu olmalıdır. Bu araç paketi `sips`, `iconutil`, `codesign` ve
`xcrun` komutlarını sağlar:

```bash
xcode-select --install
```

### Windows İçin Ek Gereksinim: PowerShell Core (pwsh)

`make build-windows` hedefi `pwsh` (PowerShell Core) kullanır. Kurulum ortama göre değişir;
ayrıntılar için [Bölüm 4a](#4a-powershell-core-pwsh-kurulumu)'ya bakın.

---

## Bölüm 3: macOS Build — Adım Adım

### 3a: Sade Build

```bash
make build-macos
```

Bu komut sırasıyla şunları yapar:

1. `version-sync` çalıştırır — `VERSION` dosyasındaki değeri `src/version.py`'ye yazar.
2. `APP_VERSION` ortam değişkenini `VERSION` dosyasından okuyarak `build_macos_app.sh`'ye geçirir.
3. Betik; ikon kaynağını (önce `APP_ICON` env değişkeni, sonra `public/kube-sec-logo.*`, son olarak
   `public/placeholder-logo.png`) `.icns` formatına dönüştürür (`sips` + `iconutil`).
4. PyInstaller'ı `--onedir --windowed` modunda çalıştırarak paketi oluşturur.
5. `Info.plist` içine `CFBundleShortVersionString`, `CFBundleVersion` ve `LSMinimumSystemVersion`
   değerlerini yazar.

**Çıktı:** `dist/Kube-Sec.app`

> İkon kaynağını özelleştirmek için `APP_ICON` ortam değişkenine PNG/JPG dosya yolunu verin:
> `APP_ICON=public/logo.png make build-macos`

> **İlk açılış uyarısı:** İmzasız uygulamayı macOS engelleyebilir. Geliştirici ortamında çözüm:
> uygulamaya sağ tık > "Aç" seçeneği veya System Settings > Privacy & Security > "Yine de Aç".

### 3b: Mimari Seçenekleri

`BUILD_ARCH` ortam değişkeni hedef mimariyi belirler. Makefile her mimari için ayrı bir hedef
sunar:

| Make Hedefi | BUILD_ARCH | Hedef Platform |
|-------------|------------|----------------|
| `make build-macos` | (boş — makinenin yerel mimarisi) | Derleme yapılan Mac'in mimarisi |
| `make build-macos-arm` | `arm64` | Apple Silicon (M1, M2, M3 ve üstü) |
| `make build-macos-intel` | `x86_64` | Intel Mac |
| `make build-macos-universal` | `universal2` | Her iki mimari (tek binary) |

```bash
make build-macos-arm      # Apple Silicon Mac için
make build-macos-intel    # Intel Mac için
make build-macos-universal  # Universal binary (uyarı aşağıda)
```

Değişkeni doğrudan da ayarlayabilirsiniz:

```bash
BUILD_ARCH=arm64 make build-macos
```

> **universal2 uyarısı:** Makefile'ın kendi yorumunda belirtildiği üzere, `universal2` build tek
> makinede her zaman başarılı olmayabilir. Güvenilir universal binary için her mimari ayrı ayrı
> derlendikten sonra `lipo` aracıyla birleştirilmesi önerilir.

### 3c: Code Signing (Kod İmzalama)

> **Gereksinim:** Apple Developer Program üyeliği ve geçerli bir **"Developer ID Application"**
> sertifikası zorunludur. Bu adım opsiyoneldir; imzasız build çalışır ancak kullanıcılarda
> Gatekeeper güvenlik uyarısı görünür.

**SIGN_IDENTITY değerini nereden bulursunuz?**

**Terminal ile:**
```bash
security find-identity -v -p codesigning
```
Çıktıda `Developer ID Application: Ad Soyad (XXXXXXXXXX)` formatındaki satırı arayın.
Sertifika türünün "Developer ID Application" olduğundan emin olun; "Development" türü
notarization için geçersizdir.

**Keychain Access uygulaması ile:**
Keychain Access'i açın, sertifikanızı bulun ve tam adını kopyalayın.

**Kod imzalama ile build almak:**
```bash
make sign SIGN_IDENTITY='Developer ID Application: <AD-SOYAD> (<TEAM-ID>)'
```

> `SIGN_IDENTITY` değerini tırnak içinde verin. `<AD-SOYAD>` ve `<TEAM-ID>` kısımlarını kendi
> sertifikanızın tam değerleriyle değiştirin.

Bu komut PyInstaller build'i yeniden çalıştırır ve ardından `codesign --force --deep
--options runtime` ile imzalar.

### 3d: Notarization (Apple Onayı)

> **Gereksinimler:**
> - Apple ID (Apple Developer hesabınıza bağlı)
> - Team ID (Apple Developer portal'da görünür)
> - App-Specific Password (Apple Kimliği parolanız değil — aşağıda nasıl üretileceği açıklanmıştır)

**App-Specific Password nasıl üretilir?**

1. [appleid.apple.com](https://appleid.apple.com) adresine gidin.
2. "Sign-In and Security" bölümüne girin.
3. "App-Specific Passwords" seçeneğini bulun.
4. "+" ile yeni parola oluşturun; açıklayıcı bir etiket verin (örn. `kube-sec-notarize`).
5. Oluşan parolayı güvenli bir yerde saklayın — bir daha gösterilmez.

**Notarization komutu:**
```bash
make notarize \
  NOTARY_APPLE_ID='<SENIN-APPLE-ID@EXAMPLE.COM>' \
  NOTARY_TEAM_ID='<SENIN-TEAM-ID>' \
  NOTARY_PASSWORD='<APP-SPECIFIC-PASSWORD>'
```

Bu komut dahili olarak `NOTARIZE=1` ortam değişkenini ayarlayarak `build_macos_app.sh`'yi
çalıştırır. Betik sırasıyla: build, `xcrun notarytool submit --wait` ile Apple sunucularına
gönderme ve `xcrun stapler staple` ile onay damgası uygulama adımlarını gerçekleştirir.

**İleri Düzey — Keychain profili:**
`NOTARY_PASSWORD`'u her seferinde geçirmek yerine şifreli Keychain profilini kullanabilirsiniz:
```bash
xcrun notarytool store-credentials "kube-sec-notary" \
  --apple-id '<SENIN-APPLE-ID@EXAMPLE.COM>' \
  --team-id '<SENIN-TEAM-ID>' \
  --password '<APP-SPECIFIC-PASSWORD>'
```
Profil kaydedildikten sonra `--password` yerine `--keychain-profile "kube-sec-notary"` argümanı
kullanılabilir. Ayrıntılar: `xcrun notarytool --help`.

### 3e: DMG Oluşturma

```bash
make dmg
```

veya `CREATE_DMG` ortam değişkeni ile doğrudan:

```bash
CREATE_DMG=1 APP_VERSION=$(cat VERSION) bash build_macos_app.sh
```

`hdiutil create` komutu kullanılarak `dist/Kube-Sec-<VERSIYON>.dmg` üretilir. DMG içindeki `.app`
Applications klasörüne sürükle-bırak ile kurulur.

### 3f: Hepsi-Bir-Arada (release-macos)

Build + kod imzalama + notarization + DMG işlemlerini tek komutta gerçekleştirmek için:

```bash
make release-macos \
  SIGN_IDENTITY='Developer ID Application: <AD-SOYAD> (<TEAM-ID>)' \
  NOTARY_APPLE_ID='<SENIN-APPLE-ID@EXAMPLE.COM>' \
  NOTARY_TEAM_ID='<SENIN-TEAM-ID>' \
  NOTARY_PASSWORD='<APP-SPECIFIC-PASSWORD>'
```

`<AD-SOYAD>`, `<TEAM-ID>`, `<SENIN-APPLE-ID@EXAMPLE.COM>` ve `<APP-SPECIFIC-PASSWORD>`
kısımlarını kendi bilgilerinizle değiştirin. Komut sırasıyla şunları yapar:

1. `version-sync` — `VERSION` → `src/version.py`
2. PyInstaller build (`build_macos_app.sh`)
3. `codesign --force --deep --options runtime` ile imzalama
4. `xcrun notarytool submit --wait` ile Apple'a gönderme
5. `xcrun stapler staple` ile damgalama
6. `hdiutil create` ile DMG üretimi

---

## Bölüm 4: Windows Build — Adım Adım

### 4a: PowerShell Core (pwsh) Kurulumu

`make build-windows` hedefi `pwsh` (PowerShell Core) gerektirir. Ortama göre kurulum:

#### Native Windows (fiziksel makine veya VM)

PowerShell Core çoğu güncel Windows kurulumunda zaten mevcuttur. Kurulu değilse:
```powershell
winget install Microsoft.PowerShell
```

#### macOS

```bash
brew install powershell --cask
```
Kurulumdan sonra yeni bir terminal oturumu açın; `pwsh --version` ile doğrulayın.

#### WSL / Ubuntu

```bash
DISTRO=$(lsb_release -rs)
wget -q https://packages.microsoft.com/config/ubuntu/${DISTRO}/packages-microsoft-prod.deb
sudo dpkg -i packages-microsoft-prod.deb
sudo apt update
sudo apt install -y powershell
```

Kurulumdan sonra `pwsh --version` ile doğrulayın.

### 4b: Build Komutu

```bash
make build-windows
```

veya doğrudan PowerShell betiğini çalıştırarak:

```powershell
pwsh ./build-windows.ps1
```

`build-windows.ps1` betiği sırasıyla şunları yapar:

1. Python yorumlayıcısını bulur (`python`, `python3`, `py` sırasıyla).
2. `.venv` sanal ortamını oluşturur ve etkinleştirir.
3. `requirements.txt` bağımlılıklarını ve PyInstaller'ı kurar.
4. `VERSION` dosyasından `APP_VERSION` değerini okur.
5. Windows VSVersionInfo şablonunu dinamik olarak üretir.
6. PyInstaller'ı `--onedir --windowed` ile çalıştırır.
7. `icon.ico` varsa ikonu ekler; yoksa uyarı göstererek devam eder.
8. Geçici `build_version_info.txt` dosyasını temizler.

**Çıktı:** `dist\Kube-Sec\Kube-Sec.exe`

### 4c: Cross-Compile Kısıtı

> **Kritik uyarı:** `make build-windows` macOS veya Linux üzerinde çalıştırılırsa
> **Windows `.exe` üretmez**; platform-native binary (macOS veya Linux binary) üretir.
> Bu binary Windows'ta çalışmaz.
>
> Gerçek bir Windows `.exe` üretmek için build'in gerçek bir Windows ortamında (fiziksel
> makine, Windows VM veya GitHub Actions `windows-latest` gibi bir CI runner) çalıştırılması
> zorunludur. PyInstaller cross-compile desteklemez.

### 4d: Opsiyonel Code Signing (Windows)

Windows kod imzalama için geçerli bir Windows kod imzalama sertifikası (PFX dosyası veya
sertifika mağazasındaki bir sertifika) gereklidir. **Sertifika yoksa bu adım otomatik olarak
atlanır; build başarıyla tamamlanır.**

`build-windows.ps1` betiği `SIGN_CERT` (PFX dosya yolu) veya `SIGN_IDENTITY` (sertifika adı)
ortam değişkenlerinden birini kontrol eder; ayarlıysa `signtool.exe` ile imzalama yapar:

```powershell
# PFX dosyası ile imzalama
$env:SIGN_CERT = '<PFX-DOSYA-YOLU>'
pwsh ./build-windows.ps1

# Sertifika mağazasındaki sertifika adı ile imzalama
$env:SIGN_IDENTITY = '<SERTIFIKA-ADI>'
pwsh ./build-windows.ps1
```

`signtool.exe` PATH'te yoksa (Windows SDK kurulu değilse) imzalama otomatik olarak atlanır ve
uyarı mesajı gösterilir.

---

## Bölüm 5: Versiyon Yönetimi

Versiyon bilgisinin tek kaynağı repo kökündeki `VERSION` dosyasıdır (örn. `1.0.0`). Tüm build
hedefleri çalışmadan önce `version-sync` adımını otomatik olarak tetikler; bu adım `APP_VERSION`
değerini `src/version.py`'ye yazar.

### Mevcut Versiyonu Görmek

```bash
make version-show
```

### Versiyon Artırma

```bash
make bump-patch    # 1.0.0 -> 1.0.1  (hata düzeltme)
make bump-minor    # 1.0.0 -> 1.1.0  (yeni özellik)
make bump-major    # 1.0.0 -> 2.0.0  (kırıcı değişiklik)
```

Her `bump-*` hedefi `VERSION` dosyasını günceller ve ardından `version-sync`'i çağırarak
`src/version.py`'yi senkronize eder.

### Belirli Versiyon Atama

```bash
make set-version VERSION=2.1.0
```

### VERSION → src/version.py Senkronizasyonu

```bash
make version-sync
```

`VERSION` dosyasını okuyarak `src/version.py` içine `__version__ = 'x.y.z'` satırını yazar.
`build-macos`, `build-macos-arm`, `build-macos-intel`, `build-macos-universal`, `release-macos`
ve `build-windows` hedefleri bu adımı otomatik çalıştırır; elle çalıştırmak genellikle gerekmez.

### Git Tag ve Push

```bash
make tag        # VERSION değerinden git annotated tag oluşturur (örn. v1.0.0)
make push-tag   # Oluşturulan tag'i origin'e push eder
```

---

## Bölüm 6: Sık Karşılaşılan Hatalar / Sorun Giderme

### "pwsh bulunamadı" veya "command not found: pwsh"

PowerShell Core kurulu değil. Ortamınıza uygun kurulum adımı için [Bölüm 4a](#4a-powershell-core-pwsh-kurulumu)'ya gidin.

**Doğrulama:**
```bash
pwsh --version
```

### "PyInstaller modülü bulunamadı" (ModuleNotFoundError)

```bash
# Sanal ortam etkinken:
pip install pyinstaller

# veya doğrudan venv içinden:
.venv/bin/pip install pyinstaller
```

`make install` yeniden çalıştırılarak `requirements.txt`'teki tüm bağımlılıklar da yenilenebilir.

### "codesign başarısız" veya SIGN_IDENTITY tanınamıyor

1. Keychain'deki sertifikaları listeleyin:
   ```bash
   security find-identity -v -p codesigning
   ```
2. Çıktıda "Developer ID Application" türünde bir sertifika görünmüyorsa:
   - Apple Developer portal'dan sertifikanızı indirin ve Keychain'e çift tıklayarak ekleyin.
   - Sertifikanın türünün "Developer ID Application" olduğundan emin olun; "Development"
     türü dağıtım imzalaması için geçersizdir.
3. `SIGN_IDENTITY` değerini tam olarak kopyalayın (boşluklar ve parantezler dahil):
   ```
   Developer ID Application: Ad Soyad (XXXXXXXXXX)
   ```

### "notarize başarısız" veya Apple tarafından reddedildi

1. `NOTARY_PASSWORD` değerinin Apple ID parolanız değil, appleid.apple.com'dan üretilen
   uygulama özel parolası (App-Specific Password) olduğunu doğrulayın.
2. Sertifika türünün "Developer ID Application" olduğunu kontrol edin; "Development"
   türüyle notarization yapılamaz.
3. Ayrıntılı hata logunu inceleyin:
   ```bash
   xcrun notarytool log <submission-id> \
     --apple-id '<SENIN-APPLE-ID@EXAMPLE.COM>' \
     --team-id '<SENIN-TEAM-ID>' \
     --password '<APP-SPECIFIC-PASSWORD>'
   ```
   `<submission-id>`, notarytool submit komutunun çıktısında görünür.

### Cross-compile: macOS'ta build alındı ama Windows'ta çalışmıyor

PyInstaller cross-compile desteklemez. macOS veya Linux'ta `make build-windows` çalıştırılırsa
üretilen binary Windows'ta çalışmaz. Gerçek Windows `.exe` için Windows ortamı (VM veya CI
runner) zorunludur. Ayrıntılar için [Bölüm 4c](#4c-cross-compile-kısıtı)'ye bakın.

### İkon eklenmedi / uygulama varsayılan ikonla açılıyor

**macOS:** `sips` ve `iconutil` araçlarının kurulu olduğunu doğrulayın:
```bash
which sips iconutil
```
Kurulu değilse `xcode-select --install` ile Xcode Command Line Tools'u yükleyin. Özel bir ikon
kullanmak için `APP_ICON` ortam değişkenini ayarlayın:
```bash
APP_ICON=public/logo.png make build-macos
```

**Windows:** `icon.ico` dosyasının repo kökünde bulunduğundan emin olun. Dosya yoksa
`build-windows.ps1` uyarı göstererek ikonsuz devam eder.

### macOS'ta uygulama ilk açılışta engelleniyor (Gatekeeper)

Apple'ın Gatekeeper mekanizması imzasız veya notarize edilmemiş uygulamaları engeller.

- **Geliştirici ortamı:** Uygulamaya sağ tık > "Aç" seçeneğini seçin.
- **Son kullanıcı:** System Settings > Privacy & Security > "Yine de Aç".
- **Kalıcı çözüm:** `make release-macos` ile kod imzalama ve notarization yapın.

---

## Bölüm 7: Güvenlik Notu

`SIGN_IDENTITY`, `NOTARY_APPLE_ID`, `NOTARY_TEAM_ID`, `NOTARY_PASSWORD`, `SIGN_CERT` gibi
değerler kimlik bilgisi niteliğindedir. Bu değerlerin **kesinlikle koda veya git'e commit
edilmemesi** gerekir.

### Neden Önemli?

- Bir commit'e dahil edilirse Git geçmişinde sonsuza kadar kalır; geçmiş rewriting olmadan
  silinemez.
- Apple kimlik bilgileri ifşa olursa Apple ID'niz üçüncü şahıslarca kötüye kullanılabilir;
  sertifika Apple tarafından iptal edilebilir.
- Windows sertifika PFX dosyası ifşa olursa kötü amaçlı yazılımlar imzalanabilir hale gelir.

### Önerilen Yöntemler

**1. Shell oturumunda geçici export (önerilen — günlük kullanım):**
```bash
export SIGN_IDENTITY='Developer ID Application: <AD-SOYAD> (<TEAM-ID>)'
export NOTARY_APPLE_ID='<SENIN-APPLE-ID@EXAMPLE.COM>'
export NOTARY_TEAM_ID='<SENIN-TEAM-ID>'
export NOTARY_PASSWORD='<APP-SPECIFIC-PASSWORD>'
make release-macos
```
Bu değerler yalnızca terminal oturumu süresince geçerlidir; diske yazılmaz.

**2. macOS Keychain profili (`xcrun notarytool store-credentials`):**
```bash
xcrun notarytool store-credentials "kube-sec-notary" \
  --apple-id '<SENIN-APPLE-ID@EXAMPLE.COM>' \
  --team-id '<SENIN-TEAM-ID>' \
  --password '<APP-SPECIFIC-PASSWORD>'
```
Profil kaydedildikten sonra notarize komutlarında `--password` yerine
`--keychain-profile "kube-sec-notary"` kullanılabilir; parola artık komut satırına yazılmaz.

**3. CI/CD secrets (GitHub Actions veya benzeri):**
GitHub Actions kullanılıyorsa bu değerleri repository Secrets olarak ekleyin
(`Settings > Secrets and variables > Actions`). Workflow dosyasında
`${{ secrets.SIGN_IDENTITY }}` biçiminde erişin.

### .gitignore ile Uyum

Repodaki `.gitignore` dosyası `kubeconfigs/`, `*.pem`, `*.key` gibi hassas dosyaları zaten
dışarıda tutar. Build kimlik bilgileri (`SIGN_IDENTITY`, `NOTARY_PASSWORD` vb.) hiçbir dosyaya
yazılmadığı sürece bu kural yeterlidir. Kolaylık için bu değerleri bir `.env` veya
`.build-secrets` dosyasına kaydetmek isterseniz o dosyayı mutlaka `.gitignore`'a ekleyin.

---

*Bu belge `BUILD.md` konumundadır ve proje kaynak dosyalarından (`Makefile`,
`build_macos_app.sh`, `build-windows.ps1`, `build-windows.sh`, `launcher.py`) türetilmiştir.
Sorun veya güncelleme için repo üzerinden issue veya PR açın.*
