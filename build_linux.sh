#!/bin/bash
set -e

# Определение рабочей директории
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "===================================================="
echo "    TG WS Proxy - Сборка универсального AppImage     "
echo "    (Совместимо со всеми версиями Linux, glibc 2.17+) "
echo "===================================================="

BUILD_DIR="$SCRIPT_DIR/build_appimage"
CACHE_DIR="$BUILD_DIR/cache"
APPDIR="$BUILD_DIR/TgWsProxy.AppDir"
DIST_DIR="$SCRIPT_DIR/dist"

mkdir -p "$CACHE_DIR" "$DIST_DIR"

PYTHON_TAR="$CACHE_DIR/cpython-3.11.16-x86_64.tar.gz"
APPIMAGE_TOOL="$CACHE_DIR/appimagetool-x86_64.AppImage"
EXTRACTED_TOOL="$BUILD_DIR/appimagetool-extracted"

PYTHON_URL="https://github.com/astral-sh/python-build-standalone/releases/download/20260901/cpython-3.11.16%2B20260901-x86_64-unknown-linux-gnu-install_only.tar.gz"
APPIMAGE_TOOL_URL="https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"

# 1. Проверка и скачивание Standalone Python
if [ ! -f "$PYTHON_TAR" ]; then
    echo "--- Скачивание переносимого Python 3.11 (glibc 2.17 / manylinux2014) ---"
    curl -fL -o "$PYTHON_TAR" "$PYTHON_URL"
fi

# 2. Проверка и скачивание appimagetool
if [ ! -f "$APPIMAGE_TOOL" ]; then
    echo "--- Скачивание appimagetool ---"
    curl -fL -o "$APPIMAGE_TOOL" "$APPIMAGE_TOOL_URL"
    chmod +x "$APPIMAGE_TOOL"
fi

if [ ! -d "$EXTRACTED_TOOL" ]; then
    echo "--- Подготовка appimagetool ---"
    (cd "$BUILD_DIR" && "$APPIMAGE_TOOL" --appimage-extract && rm -rf appimagetool-extracted && mv squashfs-root appimagetool-extracted)
fi

# 3. Подготовка структуры AppDir
echo "--- Формирование AppDir ---"
mkdir -p "$APPDIR/usr"

if [ ! -f "$APPDIR/usr/bin/python3" ]; then
    echo "--- Распаковка Python в AppDir ---"
    tar -xzf "$PYTHON_TAR" -C "$APPDIR"
    cp -rn "$APPDIR/python/"* "$APPDIR/usr/"
    rm -rf "$APPDIR/python"
fi

rm -rf "$APPDIR/usr/share/tg-ws-proxy"
mkdir -p "$APPDIR/usr/share/tg-ws-proxy"

PY_BIN="$APPDIR/usr/bin/python3"
SITE_PACKAGES="$APPDIR/usr/lib/python3.11/site-packages"

# 4. Установка зависимостей (manylinux2014 для максимальной совместимости)
if [ ! -d "$SITE_PACKAGES/pystray" ] || [ ! -d "$SITE_PACKAGES/PIL" ]; then
    echo "--- Установка зависимостей с максимальной совместимостью ---"
    "$PY_BIN" -m pip install --no-cache-dir --upgrade pip
    "$PY_BIN" -m pip install --no-cache-dir \
        --only-binary=:all: \
        --platform manylinux2014_x86_64 \
        --target "$SITE_PACKAGES" \
        --upgrade \
        "cryptography==46.0.5" \
        "Pillow==11.1.0" \
        "customtkinter==5.2.2" \
        "darkdetect==0.8.0" \
        "packaging>=24.0"

    "$PY_BIN" -m pip install --no-cache-dir \
        --target "$SITE_PACKAGES" \
        --upgrade \
        "pystray==0.19.5" \
        "pyperclip>=1.9.0" \
        "certifi>=2026.1.1" \
        "psutil>=5.9.8" \
        "python-xlib>=0.33" \
        "six>=1.16.0"
else
    echo "--- Зависимости уже готовы в AppDir, пропускаем повторную загрузку ---"
fi

# 5. Копирование кода TG WS Proxy
echo "--- Копирование исходных файлов приложения ---"
cp -r "$SCRIPT_DIR/proxy" "$APPDIR/usr/share/tg-ws-proxy/"
cp -r "$SCRIPT_DIR/ui" "$APPDIR/usr/share/tg-ws-proxy/"
cp -r "$SCRIPT_DIR/utils" "$APPDIR/usr/share/tg-ws-proxy/"
cp "$SCRIPT_DIR/linux.py" "$APPDIR/usr/share/tg-ws-proxy/"
cp "$SCRIPT_DIR/icon.ico" "$APPDIR/usr/share/tg-ws-proxy/"

# 6. Конвертация и размещение иконки
echo "--- Создание иконки ---"
"$PY_BIN" -c "
from PIL import Image
im = Image.open('$SCRIPT_DIR/icon.ico')
im.save('$APPDIR/tg-ws-proxy.png', format='PNG')
im.save('$APPDIR/.DirIcon', format='PNG')
"

# 7. Desktop-файл
echo "--- Создание .desktop файла ---"
cat > "$APPDIR/tg-ws-proxy.desktop" << 'EOF'
[Desktop Entry]
Type=Application
Name=TG WS Proxy
GenericName=Telegram Proxy
Comment=Telegram Desktop WebSocket Bridge Proxy
Exec=AppRun %u
Icon=tg-ws-proxy
Categories=Network;WebBrowser;Utility;
Terminal=false
StartupWMClass=tg-ws-proxy
EOF

# 8. Создание AppRun точки входа
echo "--- Создание скрипта AppRun ---"
cat > "$APPDIR/AppRun" << 'EOF'
#!/bin/bash
set -e

# Определение пути AppDir
HERE="$(dirname "$(readlink -f "$0")")"

# Настройка Python и путей поиска модулей
export PYTHONHOME="$HERE/usr"
export PYTHONPATH="$HERE/usr/share/tg-ws-proxy:$HERE/usr/lib/python3.11/site-packages"

# Подключение системного PyGObject (GTK3) для любых версий Linux (Ubuntu, Debian, Fedora, openSUSE, Arch)
for p in /usr/lib/python3*/dist-packages /usr/lib64/python3*/site-packages /usr/local/lib/python3*/dist-packages /usr/lib/python3*/site-packages; do
    if [ -d "$p" ]; then
        export PYTHONPATH="$PYTHONPATH:$p"
    fi
done

for g in /usr/lib64/girepository-1.0 /usr/lib/girepository-1.0 /usr/lib/x86_64-linux-gnu/girepository-1.0; do
    if [ -d "$g" ]; then
        export GI_TYPELIB_PATH="$GI_TYPELIB_PATH:$g"
    fi
done

export PATH="$HERE/usr/bin:$PATH"

# Tcl/Tk библиотеки для GUI
if [ -d "$HERE/usr/lib/tcl9.0" ]; then
    export TCL_LIBRARY="$HERE/usr/lib/tcl9.0"
fi
if [ -d "$HERE/usr/lib/tk9.0" ]; then
    export TK_LIBRARY="$HERE/usr/lib/tk9.0"
fi

# Библиотеки
export LD_LIBRARY_PATH="$HERE/usr/lib:$HERE/usr/lib/python3.11/site-packages/cryptography.libs:$HERE/usr/lib/python3.11/site-packages/pillow.libs:$LD_LIBRARY_PATH"

# Сертификаты TLS (certifi) для надежной работы на любых старых дистрибутивах Linux
CA_PATH="$HERE/usr/lib/python3.11/site-packages/certifi/cacert.pem"
if [ -f "$CA_PATH" ]; then
    export SSL_CERT_FILE="$CA_PATH"
    export REQUESTS_CA_BUNDLE="$CA_PATH"
fi

# Поддержка CLI-режима (--cli или --no-gui)
for arg in "$@"; do
    if [ "$arg" = "--cli" ] || [ "$arg" = "--no-gui" ]; then
        exec "$HERE/usr/bin/python3" "$HERE/usr/share/tg-ws-proxy/proxy/tg_ws_proxy.py" "$@"
    fi
done

# По умолчанию запуск приложения с GUI и треем
exec "$HERE/usr/bin/python3" "$HERE/usr/share/tg-ws-proxy/linux.py" "$@"
EOF

chmod +x "$APPDIR/AppRun"

# 9. Сборка AppImage
echo "--- Упаковка AppImage через appimagetool ---"
OUTPUT_APPIMAGE="$DIST_DIR/TgWsProxy-x86_64.AppImage"
rm -f "$OUTPUT_APPIMAGE"

(cd "$BUILD_DIR" && ARCH=x86_64 "$EXTRACTED_TOOL/AppRun" --runtime-file "cache/runtime-x86_64" "TgWsProxy.AppDir" "$OUTPUT_APPIMAGE")
chmod +x "$OUTPUT_APPIMAGE"

echo ""
echo "===================================================="
echo "    СБОРКА УСПЕШНО ЗАВЕРШЕНА!                        "
echo "    AppImage файл создан:                           "
echo "    $OUTPUT_APPIMAGE"
echo "===================================================="
