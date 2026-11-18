#!/bin/bash
# Builds Adborth.app into ./build. Pass "install" to also copy it to /Applications.
set -euo pipefail
cd "$(dirname "$0")"

swift build -c release
APP=build/Adborth.app
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp .build/release/Adborth "$APP/Contents/MacOS/Adborth"
cp Info.plist "$APP/Contents/Info.plist"
cp Resources/mark.png "$APP/Contents/Resources/mark.png"

# The icon: the Adborth mark on navy, at every size macOS asks for.
ICONSET=build/Adborth.iconset
rm -rf "$ICONSET"; mkdir -p "$ICONSET"
for size in 16 32 128 256 512; do
  sips -z $size $size ../web/public/brand/adborth-icon.png --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
  double=$((size * 2)); [ $double -gt 512 ] && double=512
  sips -z $double $double ../web/public/brand/adborth-icon.png --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/Adborth.icns"
rm -rf "$ICONSET"

# Signed for this Mac only (no Apple developer account needed).
codesign --force --sign - "$APP"
echo "Built $APP"

if [ "${1:-}" = "install" ]; then
  rm -rf /Applications/Adborth.app
  cp -R "$APP" /Applications/Adborth.app
  /System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f /Applications/Adborth.app
  echo "Installed /Applications/Adborth.app"
fi
