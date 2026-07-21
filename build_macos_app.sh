#!/usr/bin/env bash
set -euo pipefail

APP_NAME="Kube-Sec"
IDENTIFIER="com.example.kubesec"  # İstersen değiştir
PYTHON_BIN="${PYTHON:-python3}"

# Özel ikon belirleme önceliği:
# 1. APP_ICON env (verilmiş yol)
# 2. public/kube-sec-logo.(jpg|png|jpeg)
# 3. public/placeholder-logo.png
APP_ICON_SRC="${APP_ICON:-}"
if [ -z "$APP_ICON_SRC" ]; then
  for cand in public/kube-sec-logo.png public/kube-sec-logo.jpg public/kube-sec-logo.jpeg; do
    if [ -f "$cand" ]; then APP_ICON_SRC="$cand"; break; fi
  done
fi
if [ -z "$APP_ICON_SRC" ]; then
  APP_ICON_SRC="public/placeholder-logo.png"
fi

ICON_ICNS="icon.icns"
APP_VERSION="${APP_VERSION:-$(cat VERSION 2>/dev/null || echo 0.0.0)}"
BUILD_ARCH="${BUILD_ARCH:-}"   # arm64 | x86_64 | universal2 (uygun ortam gerektirir)
MACOSX_DEPLOYMENT_TARGET_DEFAULT="11.0"  # Big Sur ve üstü
export MACOSX_DEPLOYMENT_TARGET="${MACOSX_DEPLOYMENT_TARGET:-$MACOSX_DEPLOYMENT_TARGET_DEFAULT}"

# PyInstaller kontrolü (modül olarak)
if ! "$PYTHON_BIN" -c "import PyInstaller" >/dev/null 2>&1; then
  if [ -x ".venv/bin/python" ] && ".venv/bin/python" -c "import PyInstaller" >/dev/null 2>&1; then
    echo "[INFO] PyInstaller bulunamadı; .venv/bin/python kullanılacak"
    PYTHON_BIN=".venv/bin/python"
  else
    echo "[ERROR] PyInstaller modülü bulunamadı. Önce: $PYTHON_BIN -m pip install pyinstaller (veya .venv kurun)" >&2
    exit 1
  fi
fi

# --- İKON ÜRETİMİ (Tam boyutlu Apple iconset) ---
if [[ -f "$APP_ICON_SRC" ]]; then
  if command -v sips >/dev/null 2>&1 && command -v iconutil >/dev/null 2>&1; then
    echo "[INFO] Ikon dönüştürülüyor (tam set): $APP_ICON_SRC -> $ICON_ICNS"
    rm -rf icon.iconset "$ICON_ICNS"
    mkdir icon.iconset
    WORKPNG="/tmp/kubesec_icon_work.png"
    # Kaynağı PNG'ye çevir
    sips -s format png "$APP_ICON_SRC" --out "$WORKPNG" >/dev/null 2>&1 || cp "$APP_ICON_SRC" "$WORKPNG"
    # Boyutları al
    W=$(sips -g pixelWidth "$WORKPNG" 2>/dev/null | awk '/pixelWidth/ {print $2}')
    H=$(sips -g pixelHeight "$WORKPNG" 2>/dev/null | awk '/pixelHeight/ {print $2}')
    # Kare değilse ortalayarak kare tuval (en büyük kenar) oluştur
    if [[ "$W" != "$H" ]]; then
      BIG=$(( W>H?W:H ))
      # Basit yaklaşım: büyük kenara ölçekle sonra kareye sığdır (merkez kırp)
      sips -z $BIG $BIG "$WORKPNG" --out "$WORKPNG.scaled.png" >/dev/null 2>&1 && mv "$WORKPNG.scaled.png" "$WORKPNG"
    fi
    # En az 1024 değilse 1024'e upscale (kalite etkilenebilir)
    if [[ $W -lt 1024 || $H -lt 1024 ]]; then
      sips -z 1024 1024 "$WORKPNG" --out "$WORKPNG.up.png" >/dev/null 2>&1 && mv "$WORKPNG.up.png" "$WORKPNG"
    fi
    for sz in 16 32 64 128 256 512 1024; do
      base="icon_${sz}x${sz}.png"
      sips -z $sz $sz "$WORKPNG" --out "icon.iconset/$base" >/dev/null 2>&1 || true
      # @2x varyant (Apple bazı boyutlar için bekliyor) 16,32,128,256,512 için üret
      case $sz in 16|32|128|256|512)
        dbl=$((sz*2))
        sips -z $dbl $dbl "$WORKPNG" --out "icon.iconset/icon_${sz}x${sz}@2x.png" >/dev/null 2>&1 || true
      ;;
      esac
    done
    # Apple adlandırması (alias) - kritik değil ama tutarlılık için
    [[ -f icon.iconset/icon_32x32.png ]] && cp icon.iconset/icon_32x32.png icon.iconset/icon_16x16@2x.png 2>/dev/null || true
    [[ -f icon.iconset/icon_64x64.png ]] && cp icon.iconset/icon_64x64.png icon.iconset/icon_32x32@2x.png 2>/dev/null || true
    iconutil -c icns icon.iconset -o "$ICON_ICNS" || echo "[WARN] iconutil icns üretimi başarısız" >&2
    rm -rf icon.iconset "$WORKPNG"*
  else
    echo "[WARN] sips veya iconutil yok; ikon oluşturulamadı (varsayılan ikon)." >&2
  fi
else
  echo "[WARN] Ikon kaynağı bulunamadı: $APP_ICON_SRC" >&2
fi

# Uygulama web arayüzü için logo kopyala (her zaman logo.png olarak)
echo "[INFO] Web logo kopyalanıyor..."
mkdir -p src/web/static/img
if [[ -f "$APP_ICON_SRC" ]]; then
  if command -v sips >/dev/null 2>&1; then
    sips -s format png "$APP_ICON_SRC" --out src/web/static/img/logo.png >/dev/null 2>&1 || cp "$APP_ICON_SRC" src/web/static/img/logo.png
  else
    cp "$APP_ICON_SRC" src/web/static/img/logo.png || true
  fi
else
  # fallback placeholder
  if [[ -f public/placeholder-logo.png ]]; then
    cp public/placeholder-logo.png src/web/static/img/logo.png || true
  fi
fi

echo "[INFO] Temizlik..."
rm -rf build dist "${APP_NAME}.spec"

PYINSTALLER_ARGS=(
  --noconfirm
  --onedir
  --windowed
  --name "${APP_NAME}"
  --osx-bundle-identifier "$IDENTIFIER"
  # UPX ile sikistirma macOS notarizasyonuyla iyi calismiyor (Apple'in kotu amacli
  # yazilim sezgiselligi paketlenmis/sikistirilmis ikili dosyalari daha supheli
  # buluyor ve daha derin/yavas tarayabiliyor); Apple/PyInstaller macOS'ta UPX
  # kullanilmamasini onerir. --noupx acikca devre disi birakir (CI runner'inda
  # zaten upx kurulu degil ama yerel gelistirici makinelerinde olabilir).
  --noupx
  --paths src
  --add-data "src/web/templates:web/templates"
  --add-data "src/web/static:web/static"
  --add-data "src:src"
  --add-data "styles:styles"
  --add-data "yaml:yaml"
)

# --- pywebview / PyObjC dışlama (opsiyonel — yalnızca CI release build için) ---
# EXCLUDE_PYWEBVIEW=1 olduğunda webview ve PyObjC köprüsü bundle'dan çıkarılır;
# bu, Apple notary servisindeki gömülü ikili dosya sayısını (~148) azaltarak
# notarizasyon süresini önemli ölçüde kısaltır. Dışlama sonucunda uygulama
# native pencere yerine varsayılan tarayıcıyı açar — bilinçli özellik geri alımı.
# Varsayılan: boş — set edilmezse mevcut davranış BİREBİR AYNI kalır (regresyon yok).
EXCLUDE_PYWEBVIEW="${EXCLUDE_PYWEBVIEW:-}"
if [[ "${EXCLUDE_PYWEBVIEW}" = "1" ]]; then
  echo "[INFO] EXCLUDE_PYWEBVIEW=1: pywebview ve PyObjC köprüsü bundle'dan dışlanıyor..."
  PYINSTALLER_ARGS+=(
    # pywebview ana modülü
    --exclude-module webview
    # pyobjc-core: Objective-C köprüsü ve araçları
    --exclude-module objc
    --exclude-module PyObjCTools
    # pyobjc-framework-Cocoa: AppKit / Foundation / CoreFoundation
    --exclude-module AppKit
    --exclude-module Foundation
    --exclude-module CoreFoundation
    # pyobjc-framework-WebKit: WKWebView köprüsü
    --exclude-module WebKit
    # pyobjc-framework-Quartz: Quartz + CoreGraphics alt namespace'i
    --exclude-module Quartz
    --exclude-module CoreGraphics
  )
fi

# Mimarî seçimi (destekliyse)
if [[ -n "$BUILD_ARCH" ]]; then
  PYINSTALLER_ARGS+=( --target-arch "$BUILD_ARCH" )
  echo "[INFO] Hedef mimari: $BUILD_ARCH (MACOSX_DEPLOYMENT_TARGET=$MACOSX_DEPLOYMENT_TARGET)"
fi

if [[ -f "$ICON_ICNS" ]]; then
  PYINSTALLER_ARGS+=(--icon "$ICON_ICNS")
else
  echo "[INFO] ICNS bulunamadı; ikon eklenmeden paketlenecek." >&2
fi

echo "[INFO] Paketleniyor..."
"$PYTHON_BIN" -m PyInstaller "${PYINSTALLER_ARGS[@]}" launcher.py

PLIST="dist/${APP_NAME}.app/Contents/Info.plist"
if [ -f "$PLIST" ]; then
  if command -v /usr/libexec/PlistBuddy >/dev/null 2>&1; then
    /usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString ${APP_VERSION}" "$PLIST" 2>/dev/null || \
      /usr/libexec/PlistBuddy -c "Add :CFBundleShortVersionString string ${APP_VERSION}" "$PLIST" || true
    /usr/libexec/PlistBuddy -c "Set :CFBundleVersion ${APP_VERSION}" "$PLIST" 2>/dev/null || \
      /usr/libexec/PlistBuddy -c "Add :CFBundleVersion string ${APP_VERSION}" "$PLIST" || true
    /usr/libexec/PlistBuddy -c "Set :LSMinimumSystemVersion ${MACOSX_DEPLOYMENT_TARGET}" "$PLIST" 2>/dev/null || \
      /usr/libexec/PlistBuddy -c "Add :LSMinimumSystemVersion string ${MACOSX_DEPLOYMENT_TARGET}" "$PLIST" || true
  fi
fi

echo "[INFO] Oluşturuldu: dist/${APP_NAME}.app (version ${APP_VERSION}, icon=$(basename "$APP_ICON_SRC"))"
echo "[NOT] İlk açılışta engellenirse: Sağ tık > Aç"
echo "[İPUCU] Kod imzalama (opsiyonel): codesign --force --deep --sign - dist/${APP_NAME}.app"

# --- Opsiyonel: Kod imzalama ---
if [[ -n "${SIGN_IDENTITY:-}" ]]; then
  echo "[INFO] İçten dışa (inside-out) codesign uygulanıyor: $SIGN_IDENTITY"

  # AC-2 + AC-3: Apple'ın önerdiği inside-out imzalama sırası.
  # --deep İMZALAMADA KULLANILMAZ — her binary tek tek imzalanır (nested code
  # sorunlarını önler, notary servisinin paketi hızlı inceleme yoluna sokmasını sağlar).
  # --timestamp: RFC 3161 güvenli zaman damgası — her imza çağrısına eklenir.

  # Adım 1/3: .app içindeki tüm .so ve .dylib dosyalarını en derinden yüzeye doğru imzala.
  # '/' sayısına göre azalan sıralama → en derin yol önce işlenir (inside-out garantisi).
  # -not -type l: sembolik bağlantılar atlanır, yalnızca gerçek dosyalar imzalanır.
  echo "[INFO] Adım 1/3: Nested .so / .dylib dosyaları imzalanıyor..."
  while IFS= read -r binary; do
    codesign --force --options runtime --timestamp \
      --sign "$SIGN_IDENTITY" "$binary" || \
      echo "[WARN] codesign başarısız (atlanıyor): $binary" >&2
  done < <(
    find "dist/${APP_NAME}.app" -type f \( -name "*.so" -o -name "*.dylib" \) -not -type l | \
    awk -F'/' '{print NF, $0}' | sort -rn | awk '{$1=""; print substr($0,2)}'
  )

  # Adım 2/3: .framework dizinlerindeki gerçek binary'leri en içten dışa doğru imzala.
  # Framework binary konumları öncelik sırasıyla denenir:
  #   <Name>.framework/Versions/Current/<Name>  (klasik macOS framework yapısı)
  #   <Name>.framework/Versions/A/<Name>        (alternatif versiyon dizini)
  #   <Name>.framework/<Name>                   (düz/gömülü framework)
  echo "[INFO] Adım 2/3: .framework binary'leri imzalanıyor..."
  while IFS= read -r fw; do
    fw_name=$(basename "$fw" .framework)
    _fw_signed=0
    for bin_path in \
      "$fw/Versions/Current/$fw_name" \
      "$fw/Versions/A/$fw_name" \
      "$fw/$fw_name"; do
      if [[ -f "$bin_path" && ! -L "$bin_path" ]]; then
        codesign --force --options runtime --timestamp \
          --sign "$SIGN_IDENTITY" "$bin_path" || \
          echo "[WARN] codesign başarısız (atlanıyor): $bin_path" >&2
        _fw_signed=1
        break
      fi
    done
    if [[ $_fw_signed -eq 0 ]]; then
      echo "[INFO] Framework binary bulunamadı (atlanıyor): $fw" >&2
    fi
  done < <(
    find "dist/${APP_NAME}.app" -type d -name "*.framework" | \
    awk -F'/' '{print NF, $0}' | sort -rn | awk '{$1=""; print substr($0,2)}'
  )

  # Adım 3/3: En son üst seviye .app bundle'ının kendisini imzala.
  # (Tüm iç bileşenler imzalandıktan sonra bundle bütünlüğü doğrulanabilir hale gelir.)
  echo "[INFO] Adım 3/3: Ana .app bundle imzalanıyor..."
  codesign --force --options runtime --timestamp \
    --sign "$SIGN_IDENTITY" "dist/${APP_NAME}.app" || {
    echo "[WARN] codesign başarısız (ana bundle)" >&2
  }

  # Doğrulama: --deep ile doğrulama yapmak normaldir; sadece imzalamada kullanmıyoruz.
  codesign --verify --deep --strict --verbose=2 "dist/${APP_NAME}.app" || true
fi

# --- Opsiyonel: Notarize (Apple) ---
# Gerekli env: NOTARIZE=1, NOTARY_APPLE_ID, NOTARY_TEAM_ID, NOTARY_PASSWORD (app-specific pwd veya keychain profile)
if [[ "${NOTARIZE:-0}" = "1" ]]; then
  APP_ZIP="dist/${APP_NAME}-${APP_VERSION}${BUILD_ARCH:+-$BUILD_ARCH}.zip"
  echo "[INFO] Notarize için zip oluşturuluyor: $APP_ZIP"
  (cd dist && ditto -c -k --keepParent "${APP_NAME}.app" "$(basename "$APP_ZIP")")
  if command -v xcrun >/dev/null 2>&1; then
    echo "[INFO] NotaryTool submit başlatılıyor..."
    # NOT: EXCLUDE_PYWEBVIEW boş/0 iken bu paket çok sayıda gömülü ikili dosya
    # içerdiğinden (pywebview/PyObjC köprüsü: Foundation, AppKit, CoreFoundation,
    # WebKit vb.) Apple'ın notarization taraması normalden çok uzun sürebilir.
    # Gözlemlenen süreler: bir başarılı çalıştırma 2s32d sürmüştü; 1.0.0-rc5 ve
    # rc7 denemelerinde ise 3-3.5 saati (10800-12600s) AŞARAK zaman aşımına
    # uğradı (Apple tarafı o an hâlâ "In Progress"taydı) — yani süre 2.5-3.5+
    # saat arasında öngörülemez şekilde değişebiliyor. EXCLUDE_PYWEBVIEW=1 ile
    # (bkz. yukarıdaki blok) bu ~148 gömülü ikili dosyanın büyük kısmı bundle'dan
    # çıkarılır; bu paket çok daha az gömülü ikili dosya içerir ve notarizasyon
    # süresinin kısalması beklenir (henüz gözlemsel doğrulama bekleniyor).
    # --timeout, notarytool'un ne kadar bekleyeceğini sınırlar; Apple tarafındaki
    # işlem --timeout'a ulaşılsa bile ARKA PLANDA DEVAM EDER (bkz. `notarytool
    # submit --help`). Süre aşımında script başarısız SAYILMAZ ama staple
    # atlanır; submission ID ile daha sonra `xcrun notarytool info <id>` veya
    # `xcrun notarytool wait <id>` ile durum kontrol edilip stapling elle yapılabilir.
    # 3s30d seçildi: rc5'in aştığı 3s sınırının üzerinde, ve release.yml'deki
    # 240 dakikalık (4s) job tavanının altında yeterli marj bırakıyor (gözlemlenen
    # bekleme-dışı ek yük yalnızca ~1-2 dakika; bkz. rc5'te toplam 3s1d24sn'nin
    # 3s'lik NOTARY_TIMEOUT'tan sadece 1d24sn fazla olması).
    # NOT: notarytool --timeout yalnızca TEK birim kabul eder (örn. "210m",
    # "1h", "12600") — "3h30m" gibi bileşik biçimler GEÇERSİZDİR, bu yüzden
    # 3 saat 30 dakika dakika cinsinden ("210m") verildi.
    NOTARY_TIMEOUT="${NOTARY_TIMEOUT:-210m}"

    # AC-1: submit çıktısını hem terminale hem geçici dosyaya aktar (tee).
    # Geçici dosya submission ID'yi parse etmek için kullanılır; işlem sonunda silinir.
    _NOTARY_TMP=$(mktemp)
    if xcrun notarytool submit "$APP_ZIP" \
      --apple-id "${NOTARY_APPLE_ID}" \
      --team-id "${NOTARY_TEAM_ID}" \
      --password "${NOTARY_PASSWORD}" \
      --wait --timeout "${NOTARY_TIMEOUT}" 2>&1 | tee "$_NOTARY_TMP"; then
      echo "[INFO] Notarize tamamlandı."
    else
      echo "[WARN] Notarize başarısız veya süre aşımına uğradı (NOTARY_TIMEOUT=${NOTARY_TIMEOUT}). Apple tarafında işlem arka planda devam ediyor olabilir; submission ID'yi loglardan alıp 'xcrun notarytool info <id>' ile kontrol edin." >&2
    fi

    # AC-1.1: Submission ID'yi UUID formatına göre çıktıdan parse et.
    # notarytool submit çıktısında "  id: <uuid>" satırı bulunur; grep -Eo ile ayıklanır.
    _SUBMISSION_ID=$(grep -Eo \
      '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' \
      "$_NOTARY_TMP" 2>/dev/null | head -1 || true)
    rm -f "$_NOTARY_TMP"

    # AC-1.2 + AC-1.4: ID mevcut ise notarytool log çağrısı yap (başarı/hata/timeout fark etmez).
    # AC-1.3: Hata durumunda script FAIL ETMEDİĞİNDEN emin olmak için || ile yakalanır.
    if [[ -n "$_SUBMISSION_ID" ]]; then
      echo "[INFO] Submission ID: ${_SUBMISSION_ID} — Apple teşhis logu alınıyor..."
      xcrun notarytool log "${_SUBMISSION_ID}" \
        --apple-id "${NOTARY_APPLE_ID}" \
        --team-id "${NOTARY_TEAM_ID}" \
        --password "${NOTARY_PASSWORD}" 2>&1 || \
        echo "[WARN] notarytool log alınamadı (atlanıyor; submission ID: ${_SUBMISSION_ID})" >&2
    else
      echo "[WARN] Submission ID çıktıdan tespit edilemedi; notarytool log atlanıyor." >&2
    fi

    echo "[INFO] Staple uygulanıyor..."
    xcrun stapler staple "dist/${APP_NAME}.app" || true
  else
    echo "[WARN] xcrun bulunamadı; notarization atlandı" >&2
  fi
fi

# --- Opsiyonel: DMG oluştur ---
# Kullanıcı raporu: DMG penceresinde yalnızca Kube-Sec.app ikonu görünüyordu,
# standart "sürükle-bırak" kurulum akışındaki /Applications kısayolu yoktu.
# Bu, kullanıcıların uygulamayı nereye sürükleyeceğini bilememesine yol açtı.
# Çözüm: .app'i ve /Applications'a bir sembolik link'i aynı geçici klasöre koyup
# DMG'yi o klasörden üretiyoruz — diğer macOS uygulamalarındaki standart davranış.
if [[ "${CREATE_DMG:-0}" = "1" ]]; then
  DMG_PATH="dist/${APP_NAME}-${APP_VERSION}${BUILD_ARCH:+-$BUILD_ARCH}.dmg"
  echo "[INFO] DMG oluşturuluyor: $DMG_PATH"
  DMG_STAGING="dist/.dmg-staging"
  rm -rf "$DMG_STAGING"
  mkdir -p "$DMG_STAGING"
  cp -R "dist/${APP_NAME}.app" "$DMG_STAGING/"
  ln -s /Applications "$DMG_STAGING/Applications"
  hdiutil create -volname "${APP_NAME}" -srcfolder "$DMG_STAGING" -ov -format UDZO "$DMG_PATH" || \
    echo "[WARN] DMG oluşturulamadı" >&2
  rm -rf "$DMG_STAGING"
fi
