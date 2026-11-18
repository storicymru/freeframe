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

# The panel inside Final Cut Pro: a workflow extension, carried inside the app.
# It is built straight with the compiler; its entry point is the system's own
# extension main, and Final Cut asks for the view controller by name.
APPEX="$APP/Contents/PlugIns/Adborth.appex"
mkdir -p "$APPEX/Contents/MacOS" "$APPEX/Contents/Resources"
# Final Cut talks to an extension through classes in its ProExtension framework,
# which the extension has to carry. It is copied from the Final Cut installed
# on this Mac at build time, so Apple's code is never in the repository.
FCP_FRAMEWORK=""
for fcp in "/Applications/Final Cut Pro.app" "/Applications/Final Cut Pro Creator Studio.app"; do
  [ -d "$fcp/Contents/Frameworks/ProExtension.framework" ] && { FCP_FRAMEWORK="$fcp/Contents/Frameworks"; break; }
done
[ -n "$FCP_FRAMEWORK" ] || { echo "Final Cut Pro is not installed: its ProExtension framework is needed to build the panel."; exit 1; }
mkdir -p "$APPEX/Contents/Frameworks"
cp -R "$FCP_FRAMEWORK/ProExtension.framework" "$APPEX/Contents/Frameworks/"
swiftc -O -module-name AdborthPanel -parse-as-library -application-extension \
  Panel/PanelViewController.swift Panel/Markers.swift -o "$APPEX/Contents/MacOS/AdborthPanel" \
  -F "$APPEX/Contents/Frameworks" -framework ProExtension \
  -Xlinker -rpath -Xlinker @executable_path/../Frameworks \
  -Xlinker -e -Xlinker _NSExtensionMain
cp Panel/Info.plist "$APPEX/Contents/Info.plist"
cp "$APP/Contents/Resources/Adborth.icns" "$APPEX/Contents/Resources/Adborth.icns"

# Signed for this Mac only (no Apple developer account needed). The panel is
# signed first, with its sandbox: macOS will not load an extension without one.
codesign --force --sign - "$APPEX/Contents/Frameworks/ProExtension.framework"
codesign --force --sign - --entitlements Panel/Panel.entitlements "$APPEX"
codesign --force --sign - "$APP"
echo "Built $APP"

if [ "${1:-}" = "install" ]; then
  rm -rf /Applications/Adborth.app
  cp -R "$APP" /Applications/Adborth.app
  /System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f /Applications/Adborth.app
  pluginkit -a /Applications/Adborth.app/Contents/PlugIns/Adborth.appex
  echo "Installed /Applications/Adborth.app (restart Final Cut Pro to see the panel under Window > Extensions)"
fi
