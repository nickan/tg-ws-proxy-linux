# -*- coding: utf-8 -*-

import os
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable, Dict, Optional

from PIL import Image, ImageTk
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


# Фирменная палитра Ubuntu Yaru Dark
UBUNTU_COLORS = {
    "window_bg": "#2C2C2C",          # Основной фон окна GNOME/Ubuntu
    "header_bg": "#242424",          # GNOME HeaderBar
    "card_bg": "#383838",            # Карточка Adwaita/Yaru
    "card_border": "#464646",        # Контур карточки
    "text_title": "#FFFFFF",         # Белый заголовок
    "text_body": "#F5F5F5",          # Основной текст
    "text_muted": "#AEA79F",         # Ubuntu Warm Grey
    "orange": "#E95420",             # Фирменный Ubuntu Orange
    "orange_hover": "#F06535",
    "orange_active": "#D84A1B",
    "green": "#38B44A",              # Ubuntu Green
    "red": "#DF382C",                # Ubuntu Red
    "btn_bg": "#484848",             # Второстепенная кнопка
    "btn_hover": "#565656",
    "terminal_bg": "#300A24",        # Легендарный цвет терминала Ubuntu (Aubergine)
    "terminal_fg": "#4AF626",        # Яркий зеленый моноширинный текст
    "tab_inactive_bg": "#343434",
    "tab_inactive_fg": "#AEA79F",
    "tab_active_bg": "#E95420",
    "tab_active_fg": "#FFFFFF",
}

def get_system_font_info():
    family = "Cantarell"
    size = 11
    mono_family = "Source Code Pro"
    mono_size = 10
    try:
        out = subprocess.check_output(
            ["gsettings", "get", "org.gnome.desktop.interface", "font-name"],
            text=True, stderr=subprocess.DEVNULL
        ).strip().strip("'\"")
        parts = out.rsplit(" ", 1)
        if len(parts) == 2 and parts[1].isdigit():
            family = parts[0]
            size = int(parts[1])
        elif out:
            family = out
    except Exception:
        pass
    try:
        out_mono = subprocess.check_output(
            ["gsettings", "get", "org.gnome.desktop.interface", "monospace-font-name"],
            text=True, stderr=subprocess.DEVNULL
        ).strip().strip("'\"")
        parts_mono = out_mono.rsplit(" ", 1)
        if len(parts_mono) == 2 and parts_mono[1].isdigit():
            mono_family = parts_mono[0]
            mono_size = int(parts_mono[1])
        elif out_mono:
            mono_family = out_mono
    except Exception:
        pass
    return family, size, mono_family, mono_size


SYS_FAMILY, SYS_SIZE, MONO_FAMILY, MONO_SIZE = get_system_font_info()
FONT_FAMILY = SYS_FAMILY
FONT_NORMAL = (SYS_FAMILY, SYS_SIZE)
FONT_BOLD = (SYS_FAMILY, SYS_SIZE, "bold")
FONT_TITLE = (SYS_FAMILY, SYS_SIZE + 2, "bold")
FONT_HEADER = (SYS_FAMILY, SYS_SIZE + 4, "bold")
FONT_SMALL = (SYS_FAMILY, max(8, SYS_SIZE - 2))
FONT_MONO = (MONO_FAMILY, MONO_SIZE)


class UbuntuAppWindow:
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
        self.current_page = "overview"

        # Создаем нативное окно в стиле Ubuntu
        self.root = tk.Tk()
        self.root.title("TG WS Proxy")
        self.root.geometry("640x660")
        self.root.minsize(580, 580)
        self.root.configure(bg=UBUNTU_COLORS["window_bg"])

        # Установка иконки
        try:
            icon_ico = os.path.join(os.path.dirname(os.path.dirname(__file__)), "icon.ico")
            if os.path.exists(icon_ico):
                img = Image.open(icon_ico).resize((48, 48), Image.Resampling.LANCZOS)
                self.icon_photo = ImageTk.PhotoImage(img)
                self.root.iconphoto(False, self.icon_photo)
        except Exception:
            pass

        self._setup_ipc_server()
        self._build_ui()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close_requested)
        self.root.after(1000, self._periodic_update)
        self.root.after(1200, self._poll_logs)

        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        self.root.update_idletasks()

    def _setup_ipc_server(self):
        try:
            os.makedirs(os.path.dirname(IPC_SOCK_PATH), exist_ok=True)
            if os.path.exists(IPC_SOCK_PATH):
                try:
                    os.remove(IPC_SOCK_PATH)
                except Exception:
                    pass

            self.ipc_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.ipc_sock.bind(IPC_SOCK_PATH)
            self.ipc_sock.listen(5)
            self.ipc_sock.setblocking(False)

            def _ipc_worker():
                while self._running:
                    try:
                        conn, _ = self.ipc_sock.accept()
                        data = conn.recv(1024)
                        if b"SHOW" in data:
                            self.root.after(0, self.restore_window)
                        conn.close()
                    except (BlockingIOError, socket.error):
                        time.sleep(0.2)
                    except Exception:
                        break

            threading.Thread(target=_ipc_worker, daemon=True).start()
        except Exception as e:
            print(f"[IPC Server] Error: {e}", file=sys.stderr)

    def restore_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def on_close_requested(self):
        minimize = self.config.get("minimize_to_tray_on_close", True)
        if minimize:
            self.root.withdraw()
        else:
            self.exit_app()

    def exit_app(self):
        self._running = False
        try:
            if os.path.exists(IPC_SOCK_PATH):
                os.remove(IPC_SOCK_PATH)
        except Exception:
            pass
        try:
            self.on_stop_proxy()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass
        os._exit(0)

    # ========================== ПОСТРОЕНИЕ UI ==========================
    def _build_ui(self):
        c = UBUNTU_COLORS

        # 1. GNOME HeaderBar (верхняя панель окна Ubuntu)
        self.header_bar = tk.Frame(self.root, bg=c["header_bg"], height=52)
        self.header_bar.pack(side="top", fill="x")
        self.header_bar.pack_propagate(False)

        # Логотип и заголовок слева
        title_frame = tk.Frame(self.header_bar, bg=c["header_bg"])
        title_frame.pack(side="left", padx=16, fill="y")

        lbl_logo = tk.Label(
            title_frame,
            text="●",
            font=(FONT_FAMILY, 14, "bold"),
            fg=c["orange"],
            bg=c["header_bg"],
        )
        lbl_logo.pack(side="left", padx=(0, 6))

        lbl_app_name = tk.Label(
            title_frame,
            text="TG WS Proxy",
            font=(FONT_FAMILY, 13, "bold"),
            fg=c["text_title"],
            bg=c["header_bg"],
        )
        lbl_app_name.pack(side="left")

        # Статус-бейдж в HeaderBar
        self.lbl_header_status = tk.Label(
            self.header_bar,
            text="● Подключено" if self.is_proxy_running() else "○ Остановлено",
            font=(FONT_FAMILY, 11, "bold"),
            fg=c["green"] if self.is_proxy_running() else c["text_muted"],
            bg=c["header_bg"],
        )
        self.lbl_header_status.pack(side="left", padx=14)

        # Кнопка выхода в HeaderBar
        btn_header_exit = tk.Button(
            self.header_bar,
            text="Выход",
            font=(FONT_FAMILY, 10),
            fg=c["text_title"],
            bg=c["btn_bg"],
            activebackground=c["red"],
            activeforeground="#FFFFFF",
            relief="flat",
            bd=0,
            padx=12,
            pady=4,
            cursor="hand2",
            command=self.exit_app,
        )
        btn_header_exit.pack(side="right", padx=16, pady=10)

        # 2. View Switcher (Переключатель вкладок GNOME / Ubuntu)
        self.tab_bar = tk.Frame(self.root, bg=c["window_bg"], height=46)
        self.tab_bar.pack(side="top", fill="x", padx=16, pady=(12, 6))

        self.tab_buttons = {}
        tabs = [
            ("overview", "Обзор"),
            ("settings", "Настройки"),
            ("logs", "Журнал"),
            ("about", "О программе"),
        ]

        # Контейнер по центру для пилюль вкладок
        switcher_frame = tk.Frame(self.tab_bar, bg=c["tab_inactive_bg"], bd=1, relief="solid")
        switcher_frame.pack(anchor="center")

        for page_id, title in tabs:
            btn = tk.Button(
                switcher_frame,
                text=title,
                font=(FONT_FAMILY, 10, "bold"),
                fg=c["tab_inactive_fg"],
                bg=c["tab_inactive_bg"],
                activebackground=c["orange"],
                activeforeground="#FFFFFF",
                relief="flat",
                bd=0,
                padx=16,
                pady=6,
                cursor="hand2",
                command=lambda pid=page_id: self.switch_page(pid),
            )
            btn.pack(side="left")
            self.tab_buttons[page_id] = btn

        # 3. Основная контентная область
        self.content_frame = tk.Frame(self.root, bg=c["window_bg"])
        self.content_frame.pack(fill="both", expand=True, padx=16, pady=(6, 16))

        # Страницы
        self.page_overview = tk.Frame(self.content_frame, bg=c["window_bg"])
        self.page_settings = tk.Frame(self.content_frame, bg=c["window_bg"])
        self.page_logs = tk.Frame(self.content_frame, bg=c["window_bg"])
        self.page_about = tk.Frame(self.content_frame, bg=c["window_bg"])

        self._build_overview_page()
        self._build_settings_page()
        self._build_logs_page()
        self._build_about_page()

        self.switch_page("overview")

    # ========================== КАРТОЧКА ADWAITA/YARU ==========================
    def _create_adwaita_card(self, parent, title: str):
        c = UBUNTU_COLORS
        card = tk.Frame(parent, bg=c["card_bg"], bd=1, relief="solid")
        card.pack(fill="x", pady=6)

        header = tk.Frame(card, bg=c["card_bg"])
        header.pack(fill="x", padx=16, pady=(12, 6))

        lbl_title = tk.Label(
            header,
            text=title,
            font=(FONT_FAMILY, 11, "bold"),
            fg=c["text_title"],
            bg=c["card_bg"],
        )
        lbl_title.pack(side="left")
        return card

    # ========================== СТРАНИЦА ОБЗОР ==========================
    def _build_overview_page(self):
        c = UBUNTU_COLORS

        # 1. Карточка статуса соединения
        card_status = self._create_adwaita_card(self.page_overview, "Состояние службы MTProto")

        body_status = tk.Frame(card_status, bg=c["card_bg"])
        body_status.pack(fill="x", padx=16, pady=(0, 14))

        status_row = tk.Frame(body_status, bg=c["card_bg"])
        status_row.pack(fill="x", pady=4)

        lbl_prefix = tk.Label(
            status_row,
            text="Статус прокси:",
            font=(FONT_FAMILY, 11),
            fg=c["text_muted"],
            bg=c["card_bg"],
        )
        lbl_prefix.pack(side="left")

        self.lbl_status_badge = tk.Label(
            status_row,
            text="Подключено (Активен)" if self.is_proxy_running() else "Остановлено",
            font=(FONT_FAMILY, 11, "bold"),
            fg=c["green"] if self.is_proxy_running() else c["red"],
            bg=c["card_bg"],
        )
        self.lbl_status_badge.pack(side="left", padx=8)

        # Переключатель Запустить / Остановить
        self.btn_toggle = tk.Button(
            body_status,
            text="Остановить прокси" if self.is_proxy_running() else "Запустить прокси",
            font=(FONT_FAMILY, 10, "bold"),
            fg=c["text_title"],
            bg=c["btn_bg"],
            activebackground=c["btn_hover"],
            relief="flat",
            bd=0,
            pady=8,
            cursor="hand2",
            command=self._on_toggle_proxy,
        )
        self.btn_toggle.pack(fill="x", pady=(10, 4))

        # 2. Карточка подключения Telegram
        card_tg = self._create_adwaita_card(self.page_overview, "Подключение к Telegram")

        body_tg = tk.Frame(card_tg, bg=c["card_bg"])
        body_tg.pack(fill="x", padx=16, pady=(0, 16))

        desc_tg = tk.Label(
            body_tg,
            text="Нажмите для мгновенного добавления и активации прокси в клиенте Telegram:",
            font=(FONT_FAMILY, 10),
            fg=c["text_muted"],
            bg=c["card_bg"],
            anchor="w",
        )
        desc_tg.pack(fill="x", pady=(0, 10))

        # Большая фирменная кнопка Ubuntu Orange
        self.btn_apply_tg = tk.Button(
            body_tg,
            text="🚀  Применить в Telegram",
            font=(FONT_FAMILY, 12, "bold"),
            fg=c["orange_text"] if "orange_text" in c else "#FFFFFF",
            bg=c["orange"],
            activebackground=c["orange_hover"],
            activeforeground="#FFFFFF",
            relief="flat",
            bd=0,
            pady=10,
            cursor="hand2",
            command=self._on_apply_telegram,
        )
        self.btn_apply_tg.pack(fill="x", pady=(0, 8))

        # Второстепенная кнопка копирования
        self.btn_copy = tk.Button(
            body_tg,
            text="📋  Скопировать ссылку прокси",
            font=(FONT_FAMILY, 10),
            fg=c["text_title"],
            bg=c["btn_bg"],
            activebackground=c["btn_hover"],
            activeforeground="#FFFFFF",
            relief="flat",
            bd=0,
            pady=8,
            cursor="hand2",
            command=self._on_copy_link,
        )
        self.btn_copy.pack(fill="x")

        # 3. Карточка сетевых параметров
        card_net = self._create_adwaita_card(self.page_overview, "Параметры туннеля")

        body_net = tk.Frame(card_net, bg=c["card_bg"])
        body_net.pack(fill="x", padx=16, pady=(0, 14))

        def _make_param_row(label: str, val: str):
            r = tk.Frame(body_net, bg=c["card_bg"])
            r.pack(fill="x", pady=3)
            tk.Label(r, text=label, font=(FONT_FAMILY, 10), fg=c["text_muted"], bg=c["card_bg"], width=20, anchor="w").pack(side="left")
            vl = tk.Label(r, text=val, font=(FONT_FAMILY, 10, "bold"), fg=c["text_body"], bg=c["card_bg"], anchor="w")
            vl.pack(side="left")
            return vl

        self.lbl_net_host = _make_param_row("Локальный адрес:", f"{self.config.get('host', '127.0.0.1')}:{self.config.get('port', 1080)}")
        self.lbl_net_sec = _make_param_row("Секрет MTProto:", f"{str(self.config.get('secret', ''))[:16]}...")
        _make_param_row("Защита Cloudflare:", "Включена (Auto WebSocket)")
        _make_param_row("Обход ТСПУ / РКН:", "Активен (TLS Маскировка)")

    # ========================== СТРАНИЦА НАСТРОЙКИ ==========================
    def _build_settings_page(self):
        c = UBUNTU_COLORS

        card = self._create_adwaita_card(self.page_settings, "Конфигурация прокси")
        body = tk.Frame(card, bg=c["card_bg"])
        body.pack(fill="x", padx=16, pady=(0, 14))

        def _make_input(label: str, initial: str, width: int = 14):
            r = tk.Frame(body, bg=c["card_bg"])
            r.pack(fill="x", pady=5)
            tk.Label(r, text=label, font=(FONT_FAMILY, 10), fg=c["text_muted"], bg=c["card_bg"], width=22, anchor="w").pack(side="left")
            e = tk.Entry(r, font=(FONT_FAMILY, 10), bg="#222222", fg="#FFFFFF", insertbackground="#FFFFFF", bd=1, relief="solid", width=width)
            e.insert(0, initial)
            e.pack(side="left")
            return e, r

        self.entry_port, _ = _make_input("Порт прокси:", str(self.config.get("port", 1080)), width=10)
        self.entry_host, _ = _make_input("Хост прослушивания:", str(self.config.get("host", "127.0.0.1")), width=18)

        # Секрет с кнопкой создания
        self.entry_secret, sec_row = _make_input("Секрет MTProto:", str(self.config.get("secret", "")), width=28)
        btn_gen = tk.Button(
            sec_row,
            text="Создать",
            font=(FONT_FAMILY, 9),
            fg="#FFFFFF",
            bg=c["btn_bg"],
            activebackground=c["btn_hover"],
            relief="flat",
            bd=0,
            padx=8,
            pady=2,
            command=self._generate_secret,
        )
        btn_gen.pack(side="left", padx=8)

        # Поведение трея
        card_tray = self._create_adwaita_card(self.page_settings, "Системный трей")
        body_tray = tk.Frame(card_tray, bg=c["card_bg"])
        body_tray.pack(fill="x", padx=16, pady=(0, 14))

        self.var_min_tray = tk.BooleanVar(value=self.config.get("minimize_to_tray_on_close", True))
        chk = tk.Checkbutton(
            body_tray,
            text="Сворачивать в системный трей при закрытии крестиком",
            font=(FONT_FAMILY, 10),
            variable=self.var_min_tray,
            fg=c["text_body"],
            bg=c["card_bg"],
            activebackground=c["card_bg"],
            activeforeground=c["text_body"],
            selectcolor="#222222",
            bd=0,
            command=self._on_tray_setting_changed,
        )
        chk.pack(anchor="w", pady=4)

        # Кнопка сохранения настроек
        btn_save = tk.Button(
            self.page_settings,
            text="💾  Сохранить и перезапустить службу",
            font=(FONT_FAMILY, 11, "bold"),
            fg="#FFFFFF",
            bg=c["orange"],
            activebackground=c["orange_hover"],
            relief="flat",
            bd=0,
            pady=10,
            cursor="hand2",
            command=self._save_settings,
        )
        btn_save.pack(fill="x", pady=(12, 0))

    # ========================== СТРАНИЦА ЖУРНАЛ (ЛОГИ) ==========================
    def _build_logs_page(self):
        c = UBUNTU_COLORS

        # Верхняя панель действий журнала
        bar = tk.Frame(self.page_logs, bg=c["window_bg"])
        bar.pack(fill="x", pady=(0, 8))

        btn_cp = tk.Button(
            bar,
            text="📋 Скопировать всё",
            font=(FONT_FAMILY, 9),
            fg="#FFFFFF",
            bg=c["btn_bg"],
            activebackground=c["btn_hover"],
            relief="flat",
            bd=0,
            padx=10,
            pady=4,
            command=self._on_copy_all_logs,
        )
        btn_cp.pack(side="left", padx=(0, 6))

        btn_cl = tk.Button(
            bar,
            text="🗑️ Очистить",
            font=(FONT_FAMILY, 9),
            fg="#FFFFFF",
            bg=c["btn_bg"],
            activebackground=c["btn_hover"],
            relief="flat",
            bd=0,
            padx=10,
            pady=4,
            command=self._on_clear_logs,
        )
        btn_cl.pack(side="left")

        # Терминал логов в легендарном стиле Ubuntu Terminal Aubergine
        term_frame = tk.Frame(self.page_logs, bg=c["terminal_bg"], bd=1, relief="solid")
        term_frame.pack(fill="both", expand=True)

        scrollbar = tk.Scrollbar(term_frame)
        scrollbar.pack(side="right", fill="y")

        self.txt_terminal = tk.Text(
            term_frame,
            wrap="word",
            bg=c["terminal_bg"],
            fg=c["terminal_fg"],
            insertbackground="#FFFFFF",
            font=FONT_MONO,
            yscrollcommand=scrollbar.set,
            bd=0,
            padx=10,
            pady=8,
        )
        self.txt_terminal.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.txt_terminal.yview)

    # ========================== СТРАНИЦА О ПРОГРАММЕ ==========================
    def _build_about_page(self):
        c = UBUNTU_COLORS
        card = self._create_adwaita_card(self.page_about, "О приложении")

        body = tk.Frame(card, bg=c["card_bg"])
        body.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        tk.Label(body, text="TG WS Proxy для Linux", font=(FONT_FAMILY, 14, "bold"), fg=c["text_title"], bg=c["card_bg"]).pack(anchor="w", pady=4)
        tk.Label(body, text=f"Версия ядра: {__version__}", font=(FONT_FAMILY, 10), fg=c["orange"], bg=c["card_bg"]).pack(anchor="w", pady=2)
        tk.Label(body, text="Дизайн: Ubuntu Yaru / GNOME Dark", font=(FONT_FAMILY, 10), fg=c["text_muted"], bg=c["card_bg"]).pack(anchor="w", pady=2)

        desc = (
            "\nПрокси-клиент с защитой трафика MTProto через Cloudflare WebSocket.\n"
            "Позволяет обойти любые ограничения и блокировки ТСПУ без замедлений.\n\n"
            "Собрано в полностью автономный пакет AppImage для любых версий Linux."
        )
        tk.Label(body, text=desc, font=(FONT_FAMILY, 10), fg=c["text_body"], bg=c["card_bg"], justify="left", wraplength=520).pack(anchor="w", pady=6)

    # ========================== ПЕРЕКЛЮЧЕНИЕ СТРАНИЦ ==========================
    def switch_page(self, page_id: str):
        self.current_page = page_id
        c = UBUNTU_COLORS

        # Обновляем вид кнопок-вкладок (активная оранжевая или выделенная)
        for pid, btn in self.tab_buttons.items():
            if pid == page_id:
                btn.configure(bg=c["tab_active_bg"], fg=c["tab_active_fg"])
            else:
                btn.configure(bg=c["tab_inactive_bg"], fg=c["tab_inactive_fg"])

        # Прячем все страницы
        for p in [self.page_overview, self.page_settings, self.page_logs, self.page_about]:
            p.pack_forget()

        # Показываем выбранную
        if page_id == "overview":
            self.page_overview.pack(fill="both", expand=True)
        elif page_id == "settings":
            self.page_settings.pack(fill="both", expand=True)
        elif page_id == "logs":
            self.page_logs.pack(fill="both", expand=True)
        elif page_id == "about":
            self.page_about.pack(fill="both", expand=True)

    # ========================== ОБРАБОТЧИКИ ==========================
    def _on_toggle_proxy(self):
        if self.is_proxy_running():
            self.on_stop_proxy()
        else:
            self.on_start_proxy()
        self._update_status_views()

    def _update_status_views(self):
        c = UBUNTU_COLORS
        running = self.is_proxy_running()

        if running:
            self.lbl_header_status.config(text="● Подключено", fg=c["green"])
            self.lbl_status_badge.config(text="Подключено (Активен)", fg=c["green"])
            self.btn_toggle.config(text="Остановить прокси")
        else:
            self.lbl_header_status.config(text="○ Остановлено", fg=c["text_muted"])
            self.lbl_status_badge.config(text="Остановлено", fg=c["red"])
            self.btn_toggle.config(text="Запустить прокси")

    def _on_apply_telegram(self):
        url = self.get_proxy_url()
        try:
            pyperclip.copy(url)
        except Exception:
            pass
        try:
            subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            messagebox.showinfo("Telegram Proxy", f"Ссылка скопирована в буфер обмена:\n{url}")

    def _on_copy_link(self):
        url = self.get_proxy_url()
        try:
            pyperclip.copy(url)
            self.btn_copy.config(text="✓ Ссылка скопирована!")
            self.root.after(2000, lambda: self.btn_copy.config(text="📋  Скопировать ссылку прокси"))
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось скопировать: {e}")

    def _generate_secret(self):
        new_sec = os.urandom(16).hex()
        self.entry_secret.delete(0, "end")
        self.entry_secret.insert(0, new_sec)

    def _on_tray_setting_changed(self):
        self.config["minimize_to_tray_on_close"] = self.var_min_tray.get()
        if self.on_save_config:
            self.on_save_config(self.config)

    def _save_settings(self):
        try:
            port = int(self.entry_port.get().strip())
            self.config["port"] = port
        except ValueError:
            messagebox.showerror("Ошибка", "Порт должен быть числом!")
            return

        self.config["host"] = self.entry_host.get().strip() or "127.0.0.1"
        self.config["secret"] = self.entry_secret.get().strip()
        self.config["minimize_to_tray_on_close"] = self.var_min_tray.get()

        if self.on_save_config:
            self.on_save_config(self.config)

        self.lbl_net_host.config(text=f"{self.config['host']}:{self.config['port']}")
        self.lbl_net_sec.config(text=f"{str(self.config['secret'])[:16]}...")

        self.on_restart_proxy()
        self._update_status_views()
        messagebox.showinfo("Настройки", "Параметры сохранены, служба перезапущена.")

    def _on_copy_all_logs(self):
        try:
            txt = self.txt_terminal.get("1.0", "end")
            pyperclip.copy(txt)
            messagebox.showinfo("Журнал", "Журнал событий скопирован в буфер обмена!")
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))

    def _on_clear_logs(self):
        self.txt_terminal.delete("1.0", "end")
        self._log_pos = 0

    def _periodic_update(self):
        if not self._running:
            return
        self._update_status_views()
        if self._running:
            self.root.after(1000, self._periodic_update)

    def _poll_logs(self):
        if not self._running:
            return
        try:
            if os.path.exists(LOG_FILE):
                size = os.path.getsize(LOG_FILE)
                if size > self._log_pos:
                    with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
                        f.seek(self._log_pos)
                        new_text = f.read()
                        self._log_pos = f.tell()

                    if new_text and hasattr(self, "txt_terminal"):
                        self.txt_terminal.insert("end", new_text)
                        self.txt_terminal.see("end")
        except Exception:
            pass

        if self._running:
            self.root.after(1500, self._poll_logs)

    def run(self):
        self.root.mainloop()
