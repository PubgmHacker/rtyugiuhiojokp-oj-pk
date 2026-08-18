#!/usr/bin/env bash
#
# Сборка iOS-приложения Симп.
#
#   ./tools/ios-build.sh            — синхронизация + сборка под симулятор (проверка)
#   ./tools/ios-build.sh run        — то же и запуск на запущенном симуляторе
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
BUNDLE_ID="com.simp.dating"
# Свой каталог сборки вместо DerivedData со случайным суффиксом: путь до
# готового .app должен быть предсказуем, иначе ни проверить бандл, ни поставить
# приложение на симулятор без ручного поиска нельзя.
DD="$ROOT/build/dd"
SIM_APP="$DD/Build/Products/Debug-iphonesimulator/App.app"

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
  # npm run build, а не npx vite build: скрипт prebuild подтягивает
  # юридические страницы из landing/ в public/, а они едут внутрь .ipa —
  # ревью App Store открывает privacy.html и terms.html прямо в приложении.
  npm run build

  echo "→ Синхронизация с нативным проектом"
  npx cap sync ios
}

# Xcode копирует web/ios/App/App/public в .app как ссылку на папку, и при
# инкрементальной сборке этот шаг пропускается: содержимое файлов изменилось, а
# сама папка — нет. В приложение уезжает прошлый бандл. Отладка такого — часы:
# исходники правильные, тесты зелёные, а на экране старое поведение.
# Имена переменных здесь латиницей: bash не принимает не-ASCII идентификаторы —
# присваивание молча превращается в попытку выполнить команду.
verify_bundle() {
  local app="$1" want have
  if [ ! -f "$app/public/index.html" ]; then
    echo "✗ В $app нет public/index.html — Xcode не скопировал веб-бандл" >&2
    return 1
  fi
  want="$(shasum -a 256 "$WEB/dist/index.html" | cut -d' ' -f1)"
  have="$(shasum -a 256 "$app/public/index.html" | cut -d' ' -f1)"
  [ "$want" = "$have" ]
}

# Пересборка тут не помогает — шаг копирования всё равно считается выполненным.
# Восстанавливаем из web/ios/App/App/public: это ровно то, что положил cap sync
# минуту назад, а не догадка о содержимом.
refresh_bundle() {
  local app="$1"
  echo "→ В .app устаревший веб-бандл, обновляю из ios/App/App/public"
  rm -rf "$app/public"
  cp -R "$WEB/ios/App/App/public" "$app/public"
  cp "$WEB/ios/App/App/capacitor.config.json" "$app/capacitor.config.json"
  if ! verify_bundle "$app"; then
    echo "✗ Бандл в .app всё равно не совпал с web/dist — сборка не годится" >&2
    exit 1
  fi
  echo "✓ Веб-бандл в .app совпадает с web/dist"
}

build_simulator() {
  echo "→ Сборка под симулятор (без подписи)"
  cd "$IOS_APP"
  xcodebuild \
    -scheme App \
    -project App.xcodeproj \
    -sdk iphonesimulator \
    -destination 'generic/platform=iOS Simulator' \
    -configuration Debug \
    -derivedDataPath "$DD" \
    CODE_SIGNING_ALLOWED=NO \
    build | tail -5
  if verify_bundle "$SIM_APP"; then
    echo "✓ Веб-бандл в .app совпадает с web/dist"
  else
    refresh_bundle "$SIM_APP"
  fi
  echo "✓ Сборка прошла: $SIM_APP"
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
    build_simulator
    ;;

  run)
    pick_node
    sync_web
    build_simulator

    # Загруженное устройство берём как есть: человек мог выбрать модель сам.
    # Если не загружено ни одного — поднимаем последний iPhone из установленных.
    DEVICE="$(xcrun simctl list devices booted -j |
      /usr/bin/python3 -c 'import json,sys
данные = json.load(sys.stdin)["devices"]
устройства = [у for группа in данные.values() for у in группа]
print(устройства[0]["udid"] if устройства else "")')"

    if [ -z "$DEVICE" ]; then
      DEVICE="$(xcrun simctl list devices available -j |
        /usr/bin/python3 -c 'import json,sys
данные = json.load(sys.stdin)["devices"]
телефоны = [у for группа in данные.values() for у in группа if у["name"].startswith("iPhone")]
print(телефоны[-1]["udid"] if телефоны else "")')"
      [ -z "$DEVICE" ] && { echo "✗ Нет доступных симуляторов iPhone" >&2; exit 1; }
      echo "→ Запускаю симулятор $DEVICE"
      xcrun simctl boot "$DEVICE"
      open -a Simulator
      xcrun simctl bootstatus "$DEVICE" -b
    fi

    # Переустановка, а не install поверх: старый .app остаётся в контейнере
    # целиком, и файлы, которых в новой сборке уже нет, продолжают отдаваться
    xcrun simctl uninstall "$DEVICE" "$BUNDLE_ID" >/dev/null 2>&1 || true
    echo "→ Установка на $DEVICE"
    xcrun simctl install "$DEVICE" "$SIM_APP"
    xcrun simctl launch "$DEVICE" "$BUNDLE_ID"
    open -a Simulator

    SHOT="$ROOT/build/ios-run.png"
    sleep 6
    xcrun simctl io "$DEVICE" screenshot "$SHOT" >/dev/null 2>&1 &&
      echo "✓ Первый экран: $SHOT"
    echo "  Логи мини-аппа:  xcrun simctl launch --console-pty $DEVICE $BUNDLE_ID"
    ;;

  archive)
    pick_node
    sync_web

    : "${DEVELOPMENT_TEAM:?Задайте DEVELOPMENT_TEAM — Team ID из Apple Developer Portal}"

    OUT="$ROOT/build/ios"
    mkdir -p "$OUT"

    echo "→ Создание архива для App Store"
    cd "$IOS_APP"
    # clean обязателен: подписанный .app руками не починить (подпись слетит), а
    # инкрементальная сборка умеет не перекопировать папку public — в App Store
    # уехал бы прошлый веб-бандл, и заметили бы это уже на живом устройстве
    xcodebuild \
      -scheme App \
      -project App.xcodeproj \
      -sdk iphoneos \
      -configuration Release \
      clean >/dev/null
    xcodebuild \
      -scheme App \
      -project App.xcodeproj \
      -sdk iphoneos \
      -configuration Release \
      -archivePath "$OUT/Simp.xcarchive" \
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
      -archivePath "$OUT/Simp.xcarchive" \
      -exportOptionsPlist "$OUT/ExportOptions.plist" \
      -exportPath "$OUT"

    echo "✓ Готово: $OUT"
    echo "  Загрузить в App Store Connect:"
    echo "    xcrun altool --upload-app -f \"$OUT/App.ipa\" -t ios \\"
    echo "      --apiKey <KEY_ID> --apiIssuer <ISSUER_ID>"
    ;;

  *)
    echo "Использование: $0 [simulator|run|archive|open]" >&2
    exit 1
    ;;
esac
