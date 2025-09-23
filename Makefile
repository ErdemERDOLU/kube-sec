## =============================
## Kube-Sec Makefile
## Versiyon yönetimi + geliştirme yardımcı hedefler
## =============================

PYTHON ?= python3
VERSION_FILE ?= VERSION
APP_NAME ?= Kube-Sec

.PHONY: install upgrade run clean version-show set-version bump-patch bump-minor bump-major version-sync build-macos tag push-tag \
	build-macos-arm build-macos-intel build-macos-universal sign notarize dmg release-macos

install:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.txt

upgrade:
	$(PYTHON) -m pip install --upgrade -r requirements.txt

run:
	$(PYTHON) src/main.py

clean:
	find . -type f -name '*.pyc' -delete
	find . -type d -name '__pycache__' -exec rm -rf {} +

version-show:
	@test -f $(VERSION_FILE) || echo '0.0.0' > $(VERSION_FILE)
	@echo Current version: $$(cat $(VERSION_FILE))

set-version:
	@if [ -z "$(VERSION)" ]; then echo "HATA: VERSION değişkeni verilmeli. Örn: make set-version VERSION=1.2.3"; exit 1; fi
	@echo "$(VERSION)" > $(VERSION_FILE)
	@$(MAKE) version-sync
	@echo "Yeni versiyon: $(VERSION)"

bump-patch:
	@$(PYTHON) -c "import pathlib;vf=pathlib.Path('$(VERSION_FILE)');cur=(vf.read_text().strip() if vf.exists() else '0.0.0');maj,minn,pat=(cur.split('.')+['0','0','0'])[:3];pat=str(int(pat)+1);new='.'.join([maj,minn,pat]);vf.write_text(new+'\n');print('Patch ->',new)"
	@$(MAKE) version-sync

bump-minor:
	@$(PYTHON) -c "import pathlib;vf=pathlib.Path('$(VERSION_FILE)');cur=(vf.read_text().strip() if vf.exists() else '0.0.0');maj,minn,pat=(cur.split('.')+['0','0','0'])[:3];minn=str(int(minn)+1);pat='0';new='.'.join([maj,minn,pat]);vf.write_text(new+'\n');print('Minor ->',new)"
	@$(MAKE) version-sync

bump-major:
	@$(PYTHON) -c "import pathlib;vf=pathlib.Path('$(VERSION_FILE)');cur=(vf.read_text().strip() if vf.exists() else '0.0.0');maj,minn,pat=(cur.split('.')+['0','0','0'])[:3];maj=str(int(maj)+1);minn='0';pat='0';new='.'.join([maj,minn,pat]);vf.write_text(new+'\n');print('Major ->',new)"
	@$(MAKE) version-sync

version-sync:
	@v=$$(cat $(VERSION_FILE)); \
	echo "__version__ = '$$v'" > src/version.py; \
	echo "Synced version $$v -> src/version.py"; \
	if [ "$${GIT_AUTO_COMMIT:-0}" = "1" ]; then \
	  git add $(VERSION_FILE) src/version.py && git commit -m "chore: version $$v" || true; \
	fi

build-macos: version-sync
	@v=$$(cat $(VERSION_FILE)); \
	APP_VERSION="$$v" bash build_macos_app.sh
	@echo "MacOS app build tamamlandı (version $$(cat $(VERSION_FILE)))"

build-macos-arm: version-sync
	@v=$$(cat $(VERSION_FILE)); \
	BUILD_ARCH=arm64 APP_VERSION="$$v" bash build_macos_app.sh

build-macos-intel: version-sync
	@v=$$(cat $(VERSION_FILE)); \
	BUILD_ARCH=x86_64 APP_VERSION="$$v" bash build_macos_app.sh

# Not: universal2 tek makinede garanti değil. Genelde her mimari ayrı build alınıp lipo ile birleştirilir.
build-macos-universal: version-sync
	@v=$$(cat $(VERSION_FILE)); \
	BUILD_ARCH=universal2 APP_VERSION="$$v" bash build_macos_app.sh || echo "universal2 desteklenmiyor olabilir" >&2

sign:
	@if [ -z "$$SIGN_IDENTITY" ]; then echo "SIGN_IDENTITY gerekli. Örn: make sign SIGN_IDENTITY='Developer ID Application: Ad Soyad (TEAMID)'"; exit 1; fi
	@v=$$(cat $(VERSION_FILE)); \
	SIGN_IDENTITY="$$SIGN_IDENTITY" APP_VERSION="$$v" bash build_macos_app.sh

notarize:
	@if [ -z "$$NOTARY_APPLE_ID" ] || [ -z "$$NOTARY_TEAM_ID" ] || [ -z "$$NOTARY_PASSWORD" ]; then \
	  echo "NOTARY_* env değişkenleri gerekli."; exit 1; fi
	@v=$$(cat $(VERSION_FILE)); \
	NOTARIZE=1 APP_VERSION="$$v" bash build_macos_app.sh

dmg:
	@v=$$(cat $(VERSION_FILE)); \
	CREATE_DMG=1 APP_VERSION="$$v" bash build_macos_app.sh

# Hepsi bir arada: imzala + notarize + DMG
release-macos: version-sync
	@if [ -z "$$SIGN_IDENTITY" ]; then echo "SIGN_IDENTITY gerekli. Örn: make release-macos SIGN_IDENTITY='Developer ID Application: Ad Soyad (TEAMID)' NOTARY_APPLE_ID='id@apple.com' NOTARY_TEAM_ID='TEAMID' NOTARY_PASSWORD='app-specific-password'"; exit 1; fi
	@if [ -z "$$NOTARY_APPLE_ID" ] || [ -z "$$NOTARY_TEAM_ID" ] || [ -z "$$NOTARY_PASSWORD" ]; then \
	  echo "NOTARY_* env değişkenleri gerekli."; exit 1; fi
	@v=$$(cat $(VERSION_FILE)); \
	SIGN_IDENTITY="$$SIGN_IDENTITY" NOTARIZE=1 CREATE_DMG=1 APP_VERSION="$$v" bash build_macos_app.sh

tag:
	@if [ ! -f $(VERSION_FILE) ]; then echo "Önce versiyon dosyası yok"; exit 1; fi
	@v=$$(cat $(VERSION_FILE)); \
	git tag -a v$$v -m "Release $$v"; \
	echo "Oluşturulan tag: v$$v"

push-tag:
	@v=$$(cat $(VERSION_FILE)); \
	git push origin v$$v

