#!/usr/bin/env bash
#
# Сборка iOS-приложения Souldawn.
#
#   ./tools/ios-build.sh            — синхронизация + сборка под симулятор (проверка)
#   ./tools/ios-build.sh archive    — архив для App Store (нужна подпись)
#   ./tools/ios-build.sh open       — открыть проект в Xcode
#
# Требования: Xcode 16+, Node 22+ (Capacitor CLI), CocoaPods не нужен —
# плагины подключены через Swift Package Manager.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEB="$ROOT/web"
IOS_APP="$WEB/ios/App"
MODE="${1:-simulator}"

# Capacitor CLI требует Node >= 22, а в системе основным может быть Node 20
pick_node() {
  local candidates=(
    "/opt/homebrew/opt/node@26/bin"
    "/opt/homebrew/opt/node/bin"
    "/usr/local/opt/node/bin"
  )
  local current
  current="$(node -v 2>/dev/null | sed 's/^v//' | cut -d. -f1 || echo 0)"
  if [ "${current:-0}" -ge 22 ]; then
    return 0
  fi
  for dir in "${candidates[@]}"; do
    if [ -x "$dir/node" ]; then
      local major
      major="$("$dir/node" -v | sed 's/^v//' | cut -d. -f1)"
      if [ "$major" -ge 22 ]; then
        export PATH="$dir:$PATH"
        echo "→ Использую Node $("$dir/node" -v) для Capacitor CLI"
        return 0
      fi
    fi
  done
  echo "✗ Нужен Node >= 22 для Capacitor CLI (сейчас v$current)" >&2
  echo "  Установите: brew install node" >&2
  exit 1
}

sync_web() {
  echo "→ Сборка веб-бандла"
  cd "$WEB"
  npx vite build

  echo "→ Синхронизация с нативным проектом"
  npx cap sync ios
}

case "$MODE" in
  open)
    pick_node
    sync_web
    open "$IOS_APP/App.xcodeproj"
    ;;

  simulator)
    pick_node
    sync_web
    echo "→ Сборка под симулятор (без подписи)"
    cd "$IOS_APP"
    xcodebuild \
      -scheme App \
      -project App.xcodeproj \
      -sdk iphonesimulator \
      -destination 'generic/platform=iOS Simulator' \
      -configuration Debug \
      CODE_SIGNING_ALLOWED=NO \
      build | tail -5
    echo "✓ Сборка прошла"
    ;;

  archive)
    pick_node
    sync_web

    : "${DEVELOPMENT_TEAM:?Задайте DEVELOPMENT_TEAM — Team ID из Apple Developer Portal}"

    OUT="$ROOT/build/ios"
    mkdir -p "$OUT"

    echo "→ Создание архива для App Store"
    cd "$IOS_APP"
    xcodebuild \
      -scheme App \
      -project App.xcodeproj \
      -sdk iphoneos \
      -configuration Release \
      -archivePath "$OUT/Souldawn.xcarchive" \
      DEVELOPMENT_TEAM="$DEVELOPMENT_TEAM" \
      CODE_SIGN_STYLE=Automatic \
      archive

    cat > "$OUT/ExportOptions.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>method</key>
	<string>app-store-connect</string>
	<key>teamID</key>
	<string>$DEVELOPMENT_TEAM</string>
	<key>uploadSymbols</key>
	<true/>
	<key>destination</key>
	<string>export</string>
</dict>
</plist>
PLIST

    echo "→ Экспорт .ipa"
    xcodebuild -exportArchive \
      -archivePath "$OUT/Souldawn.xcarchive" \
      -exportOptionsPlist "$OUT/ExportOptions.plist" \
      -exportPath "$OUT"

    echo "✓ Готово: $OUT"
    echo "  Загрузить в App Store Connect:"
    echo "    xcrun altool --upload-app -f \"$OUT/App.ipa\" -t ios \\"
    echo "      --apiKey <KEY_ID> --apiIssuer <ISSUER_ID>"
    ;;

  *)
    echo "Использование: $0 [simulator|archive|open]" >&2
    exit 1
    ;;
esac
