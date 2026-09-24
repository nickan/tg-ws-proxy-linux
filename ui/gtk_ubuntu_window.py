import ctypes
import os
import socket
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Dict, Optional


def register_bundled_fonts():
    """Регистрирует упакованные шрифты Cantarell и Source Code Pro в Fontconfig."""
    fonts_dir = os.path.join(os.path.dirname(__file__), "fonts")
    if not os.path.isdir(fonts_dir):
        return
    for libname in ("libfontconfig.so.1", "libfontconfig.so.2", "libfontconfig.so"):
        try:
            fc = ctypes.CDLL(libname)
            fc.FcInit()
            fc.FcConfigAppFontAddDir.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
            fc.FcConfigAppFontAddDir.restype = ctypes.c_bool
            fc.FcConfigAppFontAddDir(None, fonts_dir.encode("utf-8"))
            for f in os.listdir(fonts_dir):
                if f.endswith((".otf", ".ttf")):
                    fc.FcConfigAppFontAddFile(None, os.path.join(fonts_dir, f).encode("utf-8"))
            break
        except Exception:
            pass


register_bundled_fonts()

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gdk, GLib, Pango, GdkPixbuf

import pyperclip

from proxy import __version__
from utils.tray_common import APP_NAME, LOG_FILE

IPC_SOCK_PATH = os.path.expanduser("~/.config/TgWsProxy/ipc.sock")


def send_ipc_show() -> bool:
    """Отправляет сигнал уже работающему приложению развернуть окно."""
    if not os.path.exists(IPC_SOCK_PATH):
        return False
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(1.0)
        s.connect(IPC_SOCK_PATH)
        s.sendall(b"SHOW\n")
        s.close()
        return True
    except Exception:
        try:
            os.remove(IPC_SOCK_PATH)
        except Exception:
            pass
        return False


UBUNTU_CSS = b"""
window.background {
    background-color: #2C2C2C;
    color: #FFFFFF;
    font-family: Cantarell, "Ubuntu", sans-serif;
}

headerbar {
    background-color: #242424;
    border-bottom: 1px solid #1E1E1E;
    color: #FFFFFF;
}

.ubuntu-card {
    background-color: #383838;
    border: 1px solid #464646;
    border-radius: 10px;
    padding: 16px;
    margin-bottom: 12px;
}

.card-title {
    font-size: 14pt;
    font-weight: bold;
    color: #FFFFFF;
    margin-bottom: 8px;
}

.card-subtitle {
    font-size: 10.5pt;
    color: #AEA79F;
    margin-bottom: 12px;
}

#btn_orange, button#btn_orange, .btn-orange {
    background-image: none;
    background-color: #E95420;
    color: #FFFFFF;
    font-weight: bold;
    font-size: 11.5pt;
    border-radius: 8px;
    padding: 10px 18px;
    border: 0;
    box-shadow: 0 2px 4px rgba(0,0,0,0.3);
}

#btn_orange:hover, button#btn_orange:hover, .btn-orange:hover {
    background-image: none;
    background-color: #F06535;
    color: #FFFFFF;
}

#btn_orange:active, button#btn_orange:active, .btn-orange:active {
    background-image: none;
    background-color: #D84A1B;
    color: #FFFFFF;
}

button.btn-secondary {
    background-image: none;
    background-color: #484848;
    color: #FFFFFF;
    font-size: 10.5pt;
    border-radius: 8px;
    padding: 8px 16px;
    border: 1px solid #5A5A5A;
}

button.btn-secondary:hover {
    background-image: none;
    background-color: #565656;
    color: #FFFFFF;
}

#btn_exit, button#btn_exit, .btn-danger {
    background-image: none;
    background-color: #DF382C;
    color: #FFFFFF;
    font-weight: bold;
    border-radius: 6px;
    padding: 6px 14px;
    border: 0;
}

#btn_exit:hover, button#btn_exit:hover, .btn-danger:hover {
    background-image: none;
    background-color: #E84D42;
    color: #FFFFFF;
}

.status-badge-running {
    color: #38B44A;
    font-weight: bold;
    font-size: 11.5pt;
}

.status-badge-stopped {
    color: #DF382C;
    font-weight: bold;
    font-size: 11.5pt;
}

.param-key {
    color: #AEA79F;
    font-size: 10.5pt;
}

.param-val {
    color: #FFFFFF;
    font-size: 10.5pt;
    font-weight: 500;
}

textview.terminal-view,
textview.terminal-view text {
    background-color: #383838;
    color: #F0F0F0;
    font-family: "Source Code Pro", "Ubuntu Mono", monospace;
    font-size: 10pt;
}

scrolledwindow.terminal-scroller {
    background-color: #383838;
    border: 1px solid #484848;
    border-radius: 8px;
}

notebook tab {
    font-size: 10.5pt;
    font-weight: bold;
    padding: 8px 16px;
}

notebook tab:checked {
    border-bottom: 3px solid #E95420;
    color: #FFFFFF;
}
"""


class GtkUbuntuWindow:
    def __init__(
        self,
        config: Dict[str, Any],
        on_start_proxy: Callable[[], None],
        on_stop_proxy: Callable[[], None],
        on_restart_proxy: Callable[[], None],
        on_exit_app: Callable[[], None],
        is_proxy_running: Callable[[], bool],
        get_proxy_url: Callable[[], str],
        on_save_config: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        self.config = config
        self.on_start_proxy = on_start_proxy
        self.on_stop_proxy = on_stop_proxy
        self.on_restart_proxy = on_restart_proxy
        self.on_exit_app = on_exit_app
        self.is_proxy_running = is_proxy_running
        self.get_proxy_url = get_proxy_url
        self.on_save_config = on_save_config

        self._running = True
        self._log_pos = 0

        # Инициализация стилей GTK CSS
        self._setup_styles()

        # Создаем главное окно Gtk
        self.win = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        self.win.set_title("TG WS Proxy")
        self.win.set_default_size(600, 680)
        self.win.set_position(Gtk.WindowPosition.CENTER)

        # Установка иконки
        try:
            icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "icon.ico")
            if os.path.exists(icon_path):
                self.win.set_icon_from_file(icon_path)
        except Exception:
            pass

        # Настраиваем HeaderBar в стиле GNOME/Ubuntu
        self.header = Gtk.HeaderBar()
        self.header.set_show_close_button(True)
        self.header.set_title("TG WS Proxy")
        self.header.set_subtitle(f"v{__version__} • MTProto WebSocket")
        self.win.set_titlebar(self.header)

        # Кнопка полного выхода
        btn_exit = Gtk.Button(label="Выход")
        btn_exit.set_name("btn_exit")
        btn_exit.get_style_context().add_class("btn-danger")
        btn_exit.connect("clicked", self._on_exit_clicked)
        self.header.pack_end(btn_exit)

        # Индикатор статуса в заголовке
        self.hdr_status_label = Gtk.Label()
        self.header.pack_start(self.hdr_status_label)

        # Основной контейнер с вкладками
        self.notebook = Gtk.Notebook()
        self.win.add(self.notebook)

        # 1. Вкладка "Обзор"
        self._build_overview_tab()

        # 2. Вкладка "Настройки"
        self._build_settings_tab()

        # 3. Вкладка "Журнал (Логи)"
        self._build_logs_tab()

        # 4. Вкладка "О программе"
        self._build_about_tab()

        # Обработка закрытия окна (сворачивание)
        self.win.connect("delete-event", self._on_delete_event)

        # Запуск фонового IPC сервера
        self._setup_ipc_server()

        # Таймеры периодического обновления
        GLib.timeout_add(1000, self._periodic_update)
        GLib.timeout_add(1200, self._poll_logs)

        # Показываем все элементы
        self.win.show_all()
        self._update_status_ui()
        self._poll_logs()

    def _setup_styles(self):
        screen = Gdk.Screen.get_default()
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(UBUNTU_CSS)
        if screen:
            Gtk.StyleContext.add_provider_for_screen(
                screen,
                css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_USER,
            )

    def _build_overview_tab(self):
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        vbox.set_border_width(18)
        scroller.add(vbox)

        # --- Карточка 1: Состояние службы ---
        c1 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        c1.get_style_context().add_class("ubuntu-card")

        lbl1 = Gtk.Label(label="Состояние службы MTProto")
        lbl1.set_xalign(0)
        lbl1.get_style_context().add_class("card-title")
        c1.pack_start(lbl1, False, False, 0)

        hb_stat = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        lbl_st_desc = Gtk.Label(label="Статус прокси:")
        lbl_st_desc.set_xalign(0)
        lbl_st_desc.get_style_context().add_class("param-key")
        self.lbl_status_main = Gtk.Label(label="Подключено (Активен)")
        self.lbl_status_main.set_xalign(0)
        self.lbl_status_main.get_style_context().add_class("status-badge-running")
        hb_stat.pack_start(lbl_st_desc, False, False, 0)
        hb_stat.pack_start(self.lbl_status_main, False, False, 0)
        c1.pack_start(hb_stat, False, False, 0)

        self.btn_toggle_proxy = Gtk.Button(label="Остановить прокси")
        self.btn_toggle_proxy.get_style_context().add_class("btn-secondary")
        self.btn_toggle_proxy.connect("clicked", self._on_toggle_proxy)
        c1.pack_start(self.btn_toggle_proxy, False, False, 4)

        vbox.pack_start(c1, False, False, 0)

        # --- Карточка 2: Подключение к Telegram ---
        c2 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        c2.get_style_context().add_class("ubuntu-card")

        lbl2 = Gtk.Label(label="Подключение к Telegram")
        lbl2.set_xalign(0)
        lbl2.get_style_context().add_class("card-title")
        c2.pack_start(lbl2, False, False, 0)

        sub2 = Gtk.Label(label="Нажмите для мгновенного добавления и активации прокси в Telegram")
        sub2.set_xalign(0)
        sub2.get_style_context().add_class("card-subtitle")
        c2.pack_start(sub2, False, False, 0)

        btn_open_tg = Gtk.Button(label="Применить в Telegram")
        btn_open_tg.set_name("btn_orange")
        btn_open_tg.get_style_context().add_class("btn-orange")
        btn_open_tg.connect("clicked", self._on_open_telegram)
        c2.pack_start(btn_open_tg, False, False, 4)

        btn_copy = Gtk.Button(label="Скопировать ссылку прокси")
        btn_copy.get_style_context().add_class("btn-secondary")
        btn_copy.connect("clicked", self._on_copy_link)
        c2.pack_start(btn_copy, False, False, 0)

        vbox.pack_start(c2, False, False, 0)

        # --- Карточка 3: Параметры туннеля ---
        c3 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        c3.get_style_context().add_class("ubuntu-card")

        lbl3 = Gtk.Label(label="Параметры туннеля")
        lbl3.set_xalign(0)
        lbl3.get_style_context().add_class("card-title")
        c3.pack_start(lbl3, False, False, 0)

        grid = Gtk.Grid()
        grid.set_column_spacing(16)
        grid.set_row_spacing(8)

        def add_row(row_idx, key, val, copy_val=None):
            k = Gtk.Label(label=key)
            k.set_xalign(0)
            k.get_style_context().add_class("param-key")
            grid.attach(k, 0, row_idx, 1, 1)

            v = Gtk.Label(label=val)
            v.set_xalign(0)
            v.get_style_context().add_class("param-val")
            grid.attach(v, 1, row_idx, 1, 1)

            if copy_val:
                b = Gtk.Button(label="Копировать")
                b.get_style_context().add_class("btn-secondary")
                b.connect("clicked", lambda w: pyperclip.copy(copy_val))
                grid.attach(b, 2, row_idx, 1, 1)

        port = self.config.get("port", 1080)
        host = self.config.get("host", "127.0.0.1")
        secret = self.config.get("secret", "")
        sec_short = f"{secret[:8]}...{secret[-4:]}" if len(secret) > 16 else secret

        add_row(0, "Локальный адрес:", f"{host}:{port}")
        add_row(1, "Секрет MTProto:", sec_short, secret)
        add_row(2, "Защита Cloudflare:", "Включена (Auto WebSocket)")
        add_row(3, "Обход ТСПУ:", "Активен (TLS Маскировка)")

        c3.pack_start(grid, False, False, 0)
        vbox.pack_start(c3, False, False, 0)

        tab_label = Gtk.Label(label="Обзор")
        self.notebook.append_page(scroller, tab_label)

    def _build_settings_tab(self):
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        vbox.set_border_width(18)
        scroller.add(vbox)

        c = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        c.get_style_context().add_class("ubuntu-card")

        lbl = Gtk.Label(label="Параметры соединения")
        lbl.set_xalign(0)
        lbl.get_style_context().add_class("card-title")
        c.pack_start(lbl, False, False, 0)

        # Host
        lbl_h = Gtk.Label(label="Хост прослушивания:")
        lbl_h.set_xalign(0)
        c.pack_start(lbl_h, False, False, 0)
        self.entry_host = Gtk.Entry()
        self.entry_host.set_text(str(self.config.get("host", "127.0.0.1")))
        c.pack_start(self.entry_host, False, False, 0)

        # Port
        lbl_p = Gtk.Label(label="Локальный порт:")
        lbl_p.set_xalign(0)
        c.pack_start(lbl_p, False, False, 0)
        self.entry_port = Gtk.Entry()
        self.entry_port.set_text(str(self.config.get("port", "1080")))
        c.pack_start(self.entry_port, False, False, 0)

        # Secret
        lbl_s = Gtk.Label(label="Секрет MTProto:")
        lbl_s.set_xalign(0)
        c.pack_start(lbl_s, False, False, 0)
        self.entry_secret = Gtk.Entry()
        self.entry_secret.set_text(str(self.config.get("secret", "")))
        c.pack_start(self.entry_secret, False, False, 0)

        btn_save = Gtk.Button(label="Сохранить настройки")
        btn_save.set_name("btn_orange")
        btn_save.get_style_context().add_class("btn-orange")
        btn_save.connect("clicked", self._on_save_settings)
        c.pack_start(btn_save, False, False, 6)

        vbox.pack_start(c, False, False, 0)

        tab_label = Gtk.Label(label="Настройки")
        self.notebook.append_page(scroller, tab_label)

    def _build_logs_tab(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        vbox.set_border_width(14)

        # Кнопки управления логами
        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_clear = Gtk.Button(label="Очистить журнал")
        btn_clear.get_style_context().add_class("btn-secondary")
        btn_clear.connect("clicked", self._on_clear_logs)
        hb.pack_start(btn_clear, False, False, 0)

        btn_copy = Gtk.Button(label="Скопировать логи")
        btn_copy.get_style_context().add_class("btn-secondary")
        btn_copy.connect("clicked", self._on_copy_logs)
        hb.pack_start(btn_copy, False, False, 0)

        vbox.pack_start(hb, False, False, 0)

        # Терминал логов (серый как инпуты)
        self.log_scroller = Gtk.ScrolledWindow()
        self.log_scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.log_scroller.get_style_context().add_class("terminal-scroller")
        self.log_scroller.set_min_content_height(420)
        self.log_scroller.set_min_content_width(520)

        self.log_view = Gtk.TextView()
        self.log_view.set_editable(False)
        self.log_view.set_cursor_visible(False)
        self.log_view.set_wrap_mode(Gtk.WrapMode.CHAR)
        self.log_view.set_left_margin(12)
        self.log_view.set_right_margin(12)
        self.log_view.set_top_margin(12)
        self.log_view.set_bottom_margin(12)
        self.log_view.get_style_context().add_class("terminal-view")

        self.log_buffer = self.log_view.get_buffer()
        self.log_scroller.add(self.log_view)
        vbox.pack_start(self.log_scroller, True, True, 0)

        tab_label = Gtk.Label(label="Журнал")
        self.notebook.append_page(vbox, tab_label)

    def _build_about_tab(self):
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        vbox.set_border_width(18)
        scroller.add(vbox)

        # Карточка 1: О программе и авторство
        c1 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        c1.get_style_context().add_class("ubuntu-card")

        lbl = Gtk.Label(label="TG WS Proxy for Linux")
        lbl.set_xalign(0)
        lbl.get_style_context().add_class("card-title")
        c1.pack_start(lbl, False, False, 0)

        sub = Gtk.Label(
            label=f"Версия ядра: {__version__}\n"
                  f"Разработка Linux-версии: Евгений Копылов (@nickan)\n"
                  f"Базовый проект: tg-ws-proxy-android от @amurcanov"
        )
        sub.set_xalign(0)
        sub.get_style_context().add_class("param-key")
        c1.pack_start(sub, False, False, 0)

        lbl_desc = Gtk.Label(
            label="Данная программа разработана для комфортной работы Telegram Desktop в Linux. "
                  "Создана на базе мобильного ядра tg-ws-proxy-android (автор amurcanov) с нативным "
                  "интерфейсом GTK3 в стиле Ubuntu, поддержкой системных шрифтов и автообходом цензуры."
        )
        lbl_desc.set_xalign(0)
        lbl_desc.set_line_wrap(True)
        c1.pack_start(lbl_desc, False, False, 4)

        hb_links = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        btn_nickan = Gtk.Button(label="GitHub автора Linux-версии (@nickan)")
        btn_nickan.get_style_context().add_class("btn-secondary")
        btn_nickan.connect("clicked", lambda w: subprocess.Popen(["xdg-open", "https://github.com/nickan"]))
        hb_links.pack_start(btn_nickan, False, False, 0)

        btn_orig = Gtk.Button(label="Базовый репозиторий (@amurcanov)")
        btn_orig.get_style_context().add_class("btn-secondary")
        btn_orig.connect("clicked", lambda w: subprocess.Popen(["xdg-open", "https://github.com/amurcanov/tg-ws-proxy-android"]))
        hb_links.pack_start(btn_orig, False, False, 0)

        c1.pack_start(hb_links, False, False, 4)
        vbox.pack_start(c1, False, False, 0)

        # Карточка 2: Ускоритель для других сервисов
        c_accel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        c_accel.get_style_context().add_class("ubuntu-card")

        lbl_accel = Gtk.Label(label="Ускорение других сервисов")
        lbl_accel.set_xalign(0)
        lbl_accel.get_style_context().add_class("card-title")
        c_accel.pack_start(lbl_accel, False, False, 0)

        lbl_accel_desc = Gtk.Label(
            label="Оптимизация скорости и надежный скоростной доступ для всех остальных "
                  "онлайн-сервисов, сайтов и приложений через Telegram-бота:"
        )
        lbl_accel_desc.set_xalign(0)
        lbl_accel_desc.set_line_wrap(True)
        c_accel.pack_start(lbl_accel_desc, False, False, 2)

        btn_bot = Gtk.Button(label="Ускоритель для других сервисов (@nncore_bot)")
        btn_bot.set_name("btn_orange")
        btn_bot.get_style_context().add_class("btn-orange")
        btn_bot.connect("clicked", lambda w: subprocess.Popen(["xdg-open", "https://t.me/nncore_bot"]))
        c_accel.pack_start(btn_bot, False, False, 4)

        vbox.pack_start(c_accel, False, False, 0)

        # Карточка 2: Совместимость с версиями Linux
        c2 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        c2.get_style_context().add_class("ubuntu-card")

        lbl_compat = Gtk.Label(label="Поддерживаемые версии Linux")
        lbl_compat.set_xalign(0)
        lbl_compat.get_style_context().add_class("card-title")
        c2.pack_start(lbl_compat, False, False, 0)

        compat_text = (
            "• Архитектура: x86_64 (64-bit)\n"
            "• Совместимость glibc: 2.17+ (работает даже на старых системах)\n"
            "• Протестировано и поддерживается:\n"
            "   — Ubuntu: 18.04 LTS, 20.04 LTS, 22.04 LTS, 24.04 LTS и новее\n"
            "   — Debian: 10 (Buster), 11 (Bullseye), 12 (Bookworm)\n"
            "   — Linux Mint: 19.x, 20.x, 21.x, 22.x\n"
            "   — openSUSE: Leap 15.x, Tumbleweed\n"
            "   — Fedora: 34-41+\n"
            "   — Arch Linux, Manjaro, EndeavourOS\n"
            "   — Отечественные ОС: Astra Linux, РЕД ОС, Альт Линукс"
        )
        lbl_compat_body = Gtk.Label(label=compat_text)
        lbl_compat_body.set_xalign(0)
        lbl_compat_body.get_style_context().add_class("param-key")
        c2.pack_start(lbl_compat_body, False, False, 0)

        vbox.pack_start(c2, False, False, 0)

        tab_label = Gtk.Label(label="О программе")
        self.notebook.append_page(scroller, tab_label)

    def _on_toggle_proxy(self, widget):
        if self.is_proxy_running():
            self.on_stop_proxy()
        else:
            self.on_start_proxy()
        self._update_status_ui()

    def _on_open_telegram(self, widget):
        url = self.get_proxy_url()
        try:
            pyperclip.copy(url)
        except Exception:
            pass
        subprocess.Popen(["xdg-open", url])

    def _on_copy_link(self, widget):
        url = self.get_proxy_url()
        try:
            pyperclip.copy(url)
            self._show_message("Ссылка скопирована", "Ссылка на подключение MTProto скопирована в буфер обмена!")
        except Exception as e:
            self._show_message("Ошибка", str(e))

    def _on_save_settings(self, widget):
        h = self.entry_host.get_text().strip()
        p_str = self.entry_port.get_text().strip()
        s = self.entry_secret.get_text().strip()

        try:
            p = int(p_str)
            if not (1 <= p <= 65535):
                raise ValueError()
        except ValueError:
            self._show_message("Ошибка", "Порт должен быть числом от 1 до 65535")
            return

        self.config["host"] = h
        self.config["port"] = p
        self.config["secret"] = s

        if self.on_save_config:
            self.on_save_config(self.config)

        self._show_message("Успех", "Настройки успешно сохранены. Перезапуск прокси...")
        self.on_restart_proxy()

    def _on_clear_logs(self, widget):
        self.log_buffer.set_text("", 0)

    def _on_copy_logs(self, widget):
        start = self.log_buffer.get_start_iter()
        end = self.log_buffer.get_end_iter()
        text = self.log_buffer.get_text(start, end, True)
        pyperclip.copy(text)
        self._show_message("Успешно", "Журнал логов скопирован в буфер обмена!")

    def _show_message(self, title: str, text: str):
        dialog = Gtk.MessageDialog(
            transient_for=self.win,
            flags=0,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text=title,
        )
        dialog.format_secondary_text(text)
        dialog.run()
        dialog.destroy()

    def _periodic_update(self) -> bool:
        if not self._running:
            return False
        self._update_status_ui()
        return True

    def _update_status_ui(self):
        running = self.is_proxy_running()
        if running:
            self.hdr_status_label.set_markup("<span color='#38B44A'>● Подключено</span>")
            self.lbl_status_main.set_text("Подключено (Активен)")
            self.lbl_status_main.get_style_context().remove_class("status-badge-stopped")
            self.lbl_status_main.get_style_context().add_class("status-badge-running")
            self.btn_toggle_proxy.set_label("Остановить прокси")
        else:
            self.hdr_status_label.set_markup("<span color='#DF382C'>● Остановлено</span>")
            self.lbl_status_main.set_text("Остановлено")
            self.lbl_status_main.get_style_context().remove_class("status-badge-running")
            self.lbl_status_main.get_style_context().add_class("status-badge-stopped")
            self.btn_toggle_proxy.set_label("Запустить прокси")

    def _poll_logs(self) -> bool:
        if not self._running:
            return False
        try:
            log_path = str(LOG_FILE)
            if os.path.exists(log_path):
                size = os.path.getsize(log_path)
                if self._log_pos == 0 and size > 30000:
                    self._log_pos = max(0, size - 30000)
                elif size < self._log_pos:
                    self._log_pos = 0

                if size > self._log_pos:
                    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                        f.seek(self._log_pos)
                        new_content = f.read()
                        self._log_pos = f.tell()
                        if new_content:
                            end_iter = self.log_buffer.get_end_iter()
                            self.log_buffer.insert(end_iter, new_content, -1)
                            if hasattr(self, "log_scroller"):
                                adj = self.log_scroller.get_vadjustment()
                                GLib.idle_add(lambda: adj.set_value(adj.get_upper() - adj.get_page_size()))
        except Exception as e:
            print(f"Log poll error: {e}")
        return True

    def _on_delete_event(self, widget, event):
        # При нажатии на крестик окно сворачивается в трей
        self.win.hide()
        return True

    def _on_exit_clicked(self, widget):
        self._running = False
        self.win.destroy()
        if self.on_exit_app:
            self.on_exit_app()
        Gtk.main_quit()

    def restore_window(self):
        GLib.idle_add(self._restore_idle)

    def _restore_idle(self):
        self.win.show_all()
        self.win.deiconify()
        self.win.present()

    def _setup_ipc_server(self):
        def _ipc_worker():
            try:
                if os.path.exists(IPC_SOCK_PATH):
                    os.remove(IPC_SOCK_PATH)
                os.makedirs(os.path.dirname(IPC_SOCK_PATH), exist_ok=True)
                server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                server.bind(IPC_SOCK_PATH)
                server.listen(5)
                while self._running:
                    server.settimeout(1.0)
                    try:
                        conn, _ = server.accept()
                        data = conn.recv(64)
                        if b"SHOW" in data:
                            self.restore_window()
                        elif b"TAB" in data:
                            try:
                                parts = data.strip().split()
                                if len(parts) >= 2:
                                    idx = int(parts[1])
                                    GLib.idle_add(self.notebook.set_current_page, idx)
                            except Exception:
                                pass
                        conn.close()
                    except socket.timeout:
                        continue
                    except Exception:
                        break
            except Exception:
                pass

        threading.Thread(target=_ipc_worker, daemon=True, name="gtk-ipc-worker").start()

    def run(self):
        Gtk.main()
