import os
import sys
import socket
import secrets
import subprocess
import threading
import time
from typing import Callable, Dict, Any, Optional

import customtkinter as ctk
from PIL import Image, ImageTk
import pyperclip

from proxy import __version__
from utils.tray_common import LOG_FILE, APP_NAME, save_config

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

# Точная палитра из скриншотов amurcanov/tg-ws-proxy-android (Indigo Light)
PALETTE_LIGHT = {
    "bg": "#EDEBF6",              # Мягкий лавандовый фон экрана
    "card": "#FFFFFF",            # Белая плашка-карточка
    "card_border": "#E4E0F0",     # Тонкая рамка карточки
    "text_title": "#241F48",      # Заголовки (темно-индиго)
    "text_body": "#352F5C",       # Основной текст
    "text_muted": "#8A84A6",      # Второстепенный текст
    "btn_primary": "#C5C0F6",     # Лавандовая акцентная кнопка «Применить в Telegram»
    "btn_primary_hover": "#B4ADF2",
    "btn_primary_text": "#2B2556",
    "chip_active_bg": "#4A4474",  # Активный чипс (темно-фиолетовый)
    "chip_active_text": "#FFFFFF",
    "chip_inactive_bg": "#EAE7F6",# Неактивный чипс
    "chip_inactive_text": "#4A4474",
    "nav_bar_bg": "#FFFFFF",      # Нижняя панель навигации
    "nav_bar_border": "#E2DEEF",
    "nav_pill_active": "#C7C2F8", # Закругленная капсула активной вкладки
    "nav_text_active": "#262052",
    "nav_text_inactive": "#8C86A8",
    "input_bg": "#FAF9FE",        # Фон полей ввода
    "input_border": "#DFDBEE",
    "switch_active": "#655D9A",
    "log_bg": "#191824",          # Темное окно логов как на 3-м скриншоте
    "log_text": "#75E29E",
    "status_connected": "#2D7F4B",
    "status_disconnected": "#8A84A6",
}

# Темная палитра для ночного режима
PALETTE_DARK = {
    "bg": "#14131B",
    "card": "#1E1C27",
    "card_border": "#2D2A3C",
    "text_title": "#EDEBF6",
    "text_body": "#D2CEE5",
    "text_muted": "#8882A3",
    "btn_primary": "#554E84",
    "btn_primary_hover": "#655D9A",
    "btn_primary_text": "#FFFFFF",
    "chip_active_bg": "#B8B3F2",
    "chip_active_text": "#1A1829",
    "chip_inactive_bg": "#2A2738",
    "chip_inactive_text": "#B8B3F2",
    "nav_bar_bg": "#1E1C27",
    "nav_bar_border": "#2D2A3C",
    "nav_pill_active": "#4D4677",
    "nav_text_active": "#FFFFFF",
    "nav_text_inactive": "#8882A3",
    "input_bg": "#252233",
    "input_border": "#3B374F",
    "switch_active": "#A8A2EB",
    "log_bg": "#111018",
    "log_text": "#75E29E",
    "status_connected": "#5BD682",
    "status_disconnected": "#8882A3",
}


class AndroidStyleAppWindow:
    def __init__(
        self,
        config: Dict[str, Any],
        is_running_fn: Callable[[], bool],
        start_proxy_fn: Callable[[], None],
        stop_proxy_fn: Callable[[], None],
        restart_proxy_fn: Callable[[], None],
        icon_path: Optional[str] = None,
        on_minimize_to_tray: Optional[Callable[[], None]] = None,
    ):
        self.config = config
        self.is_running_fn = is_running_fn
        self.start_proxy_fn = start_proxy_fn
        self.stop_proxy_fn = stop_proxy_fn
        self.restart_proxy_fn = restart_proxy_fn
        self.icon_path = icon_path
        self.on_minimize_to_tray = on_minimize_to_tray

        self.root: Optional[ctk.CTk] = None
        self.is_dark_mode = False
        self.c = PALETTE_LIGHT
        self.current_tab = 0  # 0: Прокси, 1: Настройки, 2: Логи, 3: Инфо

        self.logo_blue_img: Optional[ctk.CTkImage] = None
        self.logo_gray_img: Optional[ctk.CTkImage] = None

        self._log_filter = "ALL"
        self._raw_logs = []

    def build_and_run(self):
        ctk.set_appearance_mode("light")
        self.root = ctk.CTk()
        self.root.title("TG WS Proxy")
        self.root.geometry("440x720")
        self.root.minsize(420, 680)
        self.root.configure(fg_color=self.c["bg"])

        self.root.protocol("WM_DELETE_WINDOW", self.hide_or_minimize)

        # Загрузка иконок
        self._load_assets()

        self._build_screen()
        self._start_status_loop()
        self._start_log_stream()
        self._start_ipc_server()

        self.root.mainloop()

    def show(self):
        if self.root:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()

    def hide_or_minimize(self):
        # Если тумблер сворачивания в трей выключен — закрываем полностью
        minimize_to_tray = getattr(self, "switch_auto", None)
        if minimize_to_tray is not None and not minimize_to_tray.get():
            self.exit_app()
            return

        if self.on_minimize_to_tray:
            self.on_minimize_to_tray()
        if self.root:
            self.root.withdraw()

    def exit_app(self):
        """Полное и гарантированное завершение приложения и всех процессов."""
        try:
            self.stop_proxy_fn()
        except Exception:
            pass
        try:
            if os.path.exists(IPC_SOCK_PATH):
                os.remove(IPC_SOCK_PATH)
        except Exception:
            pass
        if self.root:
            try:
                self.root.destroy()
            except Exception:
                pass
        time.sleep(0.1)
        os._exit(0)

    def _start_ipc_server(self):
        def _srv():
            try:
                if os.path.exists(IPC_SOCK_PATH):
                    try:
                        os.remove(IPC_SOCK_PATH)
                    except Exception:
                        pass
                os.makedirs(os.path.dirname(IPC_SOCK_PATH), exist_ok=True)
                server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                server.bind(IPC_SOCK_PATH)
                server.listen(5)
                while True:
                    conn, _ = server.accept()
                    data = conn.recv(1024)
                    conn.close()
                    if b"SHOW" in data and self.root:
                        self.root.after(0, self.show)
            except Exception:
                pass

        threading.Thread(target=_srv, daemon=True, name="ipc-server").start()

    def _load_assets(self):
        assets_dir = os.path.dirname(__file__)
        blue_path = os.path.join(assets_dir, "telegram_logo.png")
        gray_path = os.path.join(assets_dir, "telegram_logo_gray.png")

        if os.path.exists(blue_path):
            img_b = Image.open(blue_path).resize((136, 136), Image.Resampling.LANCZOS)
            self.logo_blue_img = ctk.CTkImage(light_image=img_b, dark_image=img_b, size=(136, 136))
        if os.path.exists(gray_path):
            img_g = Image.open(gray_path).resize((136, 136), Image.Resampling.LANCZOS)
            self.logo_gray_img = ctk.CTkImage(light_image=img_g, dark_image=img_g, size=(136, 136))

    def _build_screen(self):
        # 1. Верхний заголовок экрана (как на скриншотах: "Запуск", "Настройки", "Лог событий")
        self.top_header_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        self.top_header_frame.pack(fill="x", padx=24, pady=(20, 10))

        self.lbl_screen_title = ctk.CTkLabel(
            self.top_header_frame,
            text="Запуск",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=self.c["text_title"],
        )
        self.lbl_screen_title.pack(side="left")

        # Правые кнопки в шапке (для логов: Очистить и Скопировать; для темы: Палитра)
        self.header_actions_frame = ctk.CTkFrame(self.top_header_frame, fg_color="transparent")
        self.header_actions_frame.pack(side="right")

        self.btn_clear_logs = ctk.CTkButton(
            self.header_actions_frame,
            text="🗑",
            width=36,
            height=32,
            corner_radius=10,
            fg_color="transparent",
            hover_color=self.c["card_border"],
            text_color=self.c["text_body"],
            font=ctk.CTkFont(size=16),
            command=self._clear_logs,
        )

        self.btn_copy_logs_top = ctk.CTkButton(
            self.header_actions_frame,
            text="📋",
            width=36,
            height=32,
            corner_radius=10,
            fg_color="transparent",
            hover_color=self.c["card_border"],
            text_color=self.c["text_body"],
            font=ctk.CTkFont(size=16),
            command=self._copy_all_logs,
        )

        self.btn_theme_toggle = ctk.CTkButton(
            self.header_actions_frame,
            text="🎨",
            width=36,
            height=32,
            corner_radius=10,
            fg_color="transparent",
            hover_color=self.c["card_border"],
            text_color=self.c["text_body"],
            font=ctk.CTkFont(size=16),
            command=self._toggle_theme,
        )
        self.btn_theme_toggle.pack(side="right")

        # 2. Центральный контейнер страниц
        self.content_container = ctk.CTkFrame(self.root, fg_color="transparent")
        self.content_container.pack(fill="both", expand=True, padx=20, pady=(0, 10))

        # Создаем экраны
        self.frame_launch = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.frame_settings = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.frame_logs = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.frame_info = ctk.CTkFrame(self.content_container, fg_color="transparent")

        self._build_launch_page()
        self._build_settings_page()
        self._build_logs_page()
        self._build_info_page()

        # 3. Плавающая нижняя панель навигации (Floating Bottom Bar в стиле Android)
        self._build_bottom_nav_bar()

        # Показываем первую страницу
        self._switch_tab(0)

    # =========================================================================
    # Экран 1: Запуск (Точно как 1-й скриншот)
    # =========================================================================
    def _build_launch_page(self):
        # Белая большая карточка с закругленными углами 28px
        card = ctk.CTkFrame(
            self.frame_launch,
            fg_color=self.c["card"],
            corner_radius=28,
            border_width=1,
            border_color=self.c["card_border"],
        )
        card.pack(fill="both", expand=True, padx=4, pady=(6, 12))

        # Большой логотип Telegram по центру (кликабельный: переключает прокси)
        self.btn_logo = ctk.CTkButton(
            card,
            text="",
            image=self.logo_blue_img,
            width=140,
            height=140,
            fg_color="transparent",
            hover_color=self.c["card"],
            command=self._toggle_proxy,
        )
        self.btn_logo.pack(pady=(36, 12))

        # Подпись статуса («Подключено» или «Отключено»)
        self.lbl_status = ctk.CTkLabel(
            card,
            text="Подключено",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=self.c["status_connected"],
        )
        self.lbl_status.pack(pady=(0, 22))

        # Кнопка «Применить в Telegram» (широкая, закругленная, нежно-лавандовая)
        self.btn_apply = ctk.CTkButton(
            card,
            text="Применить в Telegram",
            font=ctk.CTkFont(size=15, weight="bold"),
            height=50,
            corner_radius=24,
            fg_color=self.c["btn_primary"],
            hover_color=self.c["btn_primary_hover"],
            text_color=self.c["btn_primary_text"],
            command=self._apply_in_telegram,
        )
        self.btn_apply.pack(fill="x", padx=28, pady=(0, 16))

        # Плашка с параметрами в тонкой рамке: [ CF | Пул х4 | Порт 1443 | v1.10.4 ]
        pill_frame = ctk.CTkFrame(
            card,
            fg_color=self.c["input_bg"],
            corner_radius=16,
            border_width=1,
            border_color=self.c["input_border"],
            height=38,
        )
        pill_frame.pack(fill="x", padx=28, pady=(0, 16))

        self.lbl_cf_pill = ctk.CTkLabel(pill_frame, text="CF", font=ctk.CTkFont(size=12, weight="bold"), text_color=self.c["text_body"])
        self.lbl_cf_pill.pack(side="left", expand=True)

        ctk.CTkLabel(pill_frame, text="|", text_color=self.c["input_border"]).pack(side="left")

        self.lbl_pool_pill = ctk.CTkLabel(pill_frame, text="Пул х4", font=ctk.CTkFont(size=12), text_color=self.c["text_body"])
        self.lbl_pool_pill.pack(side="left", expand=True)

        ctk.CTkLabel(pill_frame, text="|", text_color=self.c["input_border"]).pack(side="left")

        self.lbl_port_pill = ctk.CTkLabel(pill_frame, text="Порт 1443", font=ctk.CTkFont(size=12), text_color=self.c["text_body"])
        self.lbl_port_pill.pack(side="left", expand=True)

        ctk.CTkLabel(pill_frame, text="|", text_color=self.c["input_border"]).pack(side="left")

        self.lbl_ver_pill = ctk.CTkLabel(pill_frame, text=f"v{__version__}", font=ctk.CTkFont(size=12), text_color=self.c["text_body"])
        self.lbl_ver_pill.pack(side="left", expand=True)

        # Закругленное поле со ссылкой + кнопка копирования 📋 внутри
        link_container = ctk.CTkFrame(
            card,
            fg_color=self.c["input_bg"],
            corner_radius=18,
            border_width=1,
            border_color=self.c["input_border"],
            height=46,
        )
        link_container.pack(fill="x", padx=28, pady=(0, 24))

        self.entry_link = ctk.CTkEntry(
            link_container,
            fg_color="transparent",
            border_width=0,
            text_color=self.c["text_muted"],
            font=ctk.CTkFont(size=12),
        )
        self.entry_link.pack(side="left", fill="x", expand=True, padx=(14, 4), pady=6)

        btn_copy = ctk.CTkButton(
            link_container,
            text="📋",
            width=36,
            height=32,
            corner_radius=10,
            fg_color="transparent",
            hover_color=self.c["card_border"],
            text_color=self.c["text_body"],
            font=ctk.CTkFont(size=16),
            command=self._copy_proxy_link,
        )
        btn_copy.pack(side="right", padx=6, pady=4)

        self._refresh_launch_values()

    # =========================================================================
    # Экран 2: Настройки (Точно как 2-й скриншот)
    # =========================================================================
    def _build_settings_page(self):
        card = ctk.CTkScrollableFrame(
            self.frame_settings,
            fg_color=self.c["card"],
            corner_radius=28,
            border_width=1,
            border_color=self.c["card_border"],
        )
        card.pack(fill="both", expand=True, padx=4, pady=(6, 12))

        # Раздел 1: 🌐 Подключение
        head1 = ctk.CTkLabel(card, text="🌐  Подключение", font=ctk.CTkFont(size=15, weight="bold"), text_color=self.c["text_title"])
        head1.pack(anchor="w", padx=20, pady=(16, 6))

        # Поле Порт
        ctk.CTkLabel(card, text="Порт", font=ctk.CTkFont(size=12), text_color=self.c["text_muted"]).pack(anchor="w", padx=20)
        self.cfg_port_entry = ctk.CTkEntry(
            card,
            fg_color=self.c["input_bg"],
            border_color=self.c["input_border"],
            corner_radius=14,
            height=40,
            text_color=self.c["text_body"],
        )
        self.cfg_port_entry.insert(0, str(self.config.get("port", 1443)))
        self.cfg_port_entry.pack(fill="x", padx=20, pady=(2, 10))

        # Кнопка «⚙ Авто (Включён CF)»
        btn_auto_cf = ctk.CTkButton(
            card,
            text="⚙ Авто (Включён CF)",
            font=ctk.CTkFont(size=13),
            height=38,
            corner_radius=14,
            fg_color=self.c["input_bg"],
            hover_color=self.c["input_border"],
            text_color=self.c["text_body"],
            border_width=1,
            border_color=self.c["input_border"],
        )
        btn_auto_cf.pack(fill="x", padx=20, pady=(0, 16))

        # Раздел 2: ❖ Пул WS (кнопки-чипсы 2, 4, 6, 8 как на скриншоте)
        head2 = ctk.CTkLabel(card, text="❖  Пул WS", font=ctk.CTkFont(size=15, weight="bold"), text_color=self.c["text_title"])
        head2.pack(anchor="w", padx=20, pady=(0, 8))

        chips_frame = ctk.CTkFrame(card, fg_color="transparent")
        chips_frame.pack(fill="x", padx=20, pady=(0, 16))

        self.pool_buttons = {}
        for pool_val in [2, 4, 6, 8]:
            btn = ctk.CTkButton(
                chips_frame,
                text=str(pool_val),
                width=55,
                height=36,
                corner_radius=18,
                font=ctk.CTkFont(size=13, weight="bold"),
                command=lambda v=pool_val: self._select_pool_size(v),
            )
            btn.pack(side="left", expand=True, padx=4)
            self.pool_buttons[pool_val] = btn

        self._update_pool_buttons_visual(self.config.get("pool_size", 4))

        # Раздел 3: 🗝 Секретный ключ
        head3 = ctk.CTkLabel(card, text="🗝  Секретный ключ", font=ctk.CTkFont(size=15, weight="bold"), text_color=self.c["text_title"])
        head3.pack(anchor="w", padx=20, pady=(0, 6))

        secret_box = ctk.CTkFrame(card, fg_color=self.c["input_bg"], corner_radius=14, border_width=1, border_color=self.c["input_border"])
        secret_box.pack(fill="x", padx=20, pady=(0, 16))

        self.cfg_secret_entry = ctk.CTkEntry(
            secret_box,
            fg_color="transparent",
            border_width=0,
            text_color=self.c["text_body"],
            font=ctk.CTkFont(size=12),
        )
        self.cfg_secret_entry.insert(0, str(self.config.get("secret", "")))
        self.cfg_secret_entry.pack(side="left", fill="x", expand=True, padx=(12, 4), pady=6)

        btn_regen_secret = ctk.CTkButton(
            secret_box,
            text="⟳",
            width=36,
            height=30,
            corner_radius=8,
            fg_color="transparent",
            hover_color=self.c["input_border"],
            text_color=self.c["text_body"],
            font=ctk.CTkFont(size=16),
            command=self._generate_secret,
        )
        btn_regen_secret.pack(side="right", padx=6, pady=4)

        # Раздел 4: ☁ CloudFlare CDN (тумблер справа)
        cf_row = ctk.CTkFrame(card, fg_color="transparent")
        cf_row.pack(fill="x", padx=20, pady=(0, 14))

        lbl_cf = ctk.CTkLabel(cf_row, text="☁  CloudFlare CDN", font=ctk.CTkFont(size=14, weight="bold"), text_color=self.c["text_title"])
        lbl_cf.pack(side="left")

        self.switch_cf = ctk.CTkSwitch(
            cf_row,
            text="",
            progress_color=self.c["switch_active"],
            command=self._save_settings,
        )
        if self.config.get("fallback_cfproxy", True):
            self.switch_cf.select()
        else:
            self.switch_cf.deselect()
        self.switch_cf.pack(side="right")

        # Раздел 5: ⏻ Сворачивание в трей
        auto_row = ctk.CTkFrame(card, fg_color="transparent")
        auto_row.pack(fill="x", padx=20, pady=(0, 16))

        lbl_auto = ctk.CTkLabel(auto_row, text="⏻  Сворачивать в трей при закрытии", font=ctk.CTkFont(size=14, weight="bold"), text_color=self.c["text_title"])
        lbl_auto.pack(side="left")

        self.switch_auto = ctk.CTkSwitch(
            auto_row,
            text="",
            progress_color=self.c["switch_active"],
            command=self._save_settings,
        )
        self.switch_auto.select()
        self.switch_auto.pack(side="right")

        # Кнопка «Применить настройки»
        btn_apply_settings = ctk.CTkButton(
            card,
            text="Применить настройки",
            font=ctk.CTkFont(size=14, weight="bold"),
            height=44,
            corner_radius=20,
            fg_color=self.c["btn_primary"],
            hover_color=self.c["btn_primary_hover"],
            text_color=self.c["btn_primary_text"],
            command=self._save_and_restart,
        )
        btn_apply_settings.pack(fill="x", padx=20, pady=(0, 10))

        # Кнопка «🛑 Полностью закрыть приложение»
        btn_exit_app = ctk.CTkButton(
            card,
            text="🛑 Полностью закрыть приложение",
            font=ctk.CTkFont(size=14, weight="bold"),
            height=44,
            corner_radius=20,
            fg_color="#D9534F",
            hover_color="#C9302C",
            text_color="#FFFFFF",
            command=self.exit_app,
        )
        btn_exit_app.pack(fill="x", padx=20, pady=(0, 24))

    # =========================================================================
    # Экран 3: Лог событий (Точно как 3-й скриншот)
    # =========================================================================
    def _build_logs_page(self):
        # Панель фильтров: [ INFO ] [ ERROR ] [ ALL ]
        filter_bar = ctk.CTkFrame(self.frame_logs, fg_color="transparent")
        filter_bar.pack(fill="x", padx=8, pady=(0, 10))

        self.chip_info = ctk.CTkButton(
            filter_bar,
            text="INFO",
            width=80,
            height=32,
            corner_radius=16,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda: self._set_log_filter("INFO"),
        )
        self.chip_info.pack(side="left", expand=True, padx=4)

        self.chip_err = ctk.CTkButton(
            filter_bar,
            text="ERROR",
            width=80,
            height=32,
            corner_radius=16,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda: self._set_log_filter("ERROR"),
        )
        self.chip_err.pack(side="left", expand=True, padx=4)

        self.chip_all = ctk.CTkButton(
            filter_bar,
            text="ALL",
            width=80,
            height=32,
            corner_radius=16,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda: self._set_log_filter("ALL"),
        )
        self.chip_all.pack(side="left", expand=True, padx=4)

        self._update_log_filter_chips()

        # Темная карточка с моноширинным текстом логов
        log_card = ctk.CTkFrame(
            self.frame_logs,
            fg_color=self.c["log_bg"],
            corner_radius=24,
            border_width=1,
            border_color=self.c["card_border"],
        )
        log_card.pack(fill="both", expand=True, padx=4, pady=(0, 10))

        self.log_textbox = ctk.CTkTextbox(
            log_card,
            fg_color="transparent",
            text_color=self.c["log_text"],
            font=ctk.CTkFont(family="monospace", size=11),
            corner_radius=20,
        )
        self.log_textbox.pack(fill="both", expand=True, padx=12, pady=12)

    # =========================================================================
    # Экран 4: Информация (Справка)
    # =========================================================================
    def _build_info_page(self):
        card = ctk.CTkScrollableFrame(
            self.frame_info,
            fg_color=self.c["card"],
            corner_radius=28,
            border_width=1,
            border_color=self.c["card_border"],
        )
        card.pack(fill="both", expand=True, padx=4, pady=(6, 12))

        ctk.CTkLabel(card, text="О приложении", font=ctk.CTkFont(size=16, weight="bold"), text_color=self.c["text_title"]).pack(anchor="w", padx=20, pady=(16, 6))

        info_text = (
            f"TG WS Proxy v{__version__}\n"
            "Локальный MTProto прокси с перенаправлением трафика через WebSocket туннели CloudFlare.\n\n"
            "Как работает:\n"
            "1. Приложение поднимает локальный прокси (127.0.0.1:1443).\n"
            "2. Перехватывает подключения Telegram.\n"
            "3. Устанавливает защищенное WSS-соединение к Telegram DC через Cloudflare.\n\n"
            "Авторы:\n"
            "• Движок прокси: Flowseal\n"
            "• Дизайн интерфейса Android: amurcanov\n"
            "• Версия для Linux: Portable AppImage"
        )
        ctk.CTkLabel(card, text=info_text, font=ctk.CTkFont(size=13), text_color=self.c["text_body"], justify="left", wraplength=340).pack(anchor="w", padx=20, pady=(0, 20))

    # =========================================================================
    # Нижняя плавающая панель навигации (Floating Bottom Bar)
    # =========================================================================
    def _build_bottom_nav_bar(self):
        bar_outer = ctk.CTkFrame(self.root, fg_color="transparent")
        bar_outer.pack(fill="x", padx=16, pady=(0, 16))

        # Белая капсула
        self.nav_bar = ctk.CTkFrame(
            bar_outer,
            fg_color=self.c["nav_bar_bg"],
            corner_radius=30,
            border_width=1,
            border_color=self.c["nav_bar_border"],
            height=62,
        )
        self.nav_bar.pack(fill="x")

        # 4 вкладки: [ Прокси ] [ Настройки ] [ Логи ] [ Инфо ]
        tabs_meta = [
            (0, "⏻", "Прокси"),
            (1, "⚙", "Настройки"),
            (2, "⎚", "Логи"),
            (3, "ⓘ", "Инфо"),
        ]

        self.nav_buttons = []
        for idx, icon, label in tabs_meta:
            btn_frame = ctk.CTkButton(
                self.nav_bar,
                text=f"{icon}\n{label}",
                font=ctk.CTkFont(size=11, weight="bold"),
                height=48,
                corner_radius=24,
                fg_color="transparent",
                hover_color=self.c["card_border"],
                text_color=self.c["nav_text_inactive"],
                command=lambda i=idx: self._switch_tab(i),
            )
            btn_frame.pack(side="left", fill="both", expand=True, padx=4, pady=6)
            self.nav_buttons.append(btn_frame)

    def _switch_tab(self, tab_idx: int):
        self.current_tab = tab_idx

        # Скрываем все страницы
        self.frame_launch.pack_forget()
        self.frame_settings.pack_forget()
        self.frame_logs.pack_forget()
        self.frame_info.pack_forget()

        # Обновляем заголовок и кнопки в шапке
        titles = ["Запуск", "Настройки", "Лог событий", "Информация"]
        self.lbl_screen_title.configure(text=titles[tab_idx])

        # Кнопки очистки/копирования логов показываем только на вкладке Логи
        if tab_idx == 2:
            self.btn_clear_logs.pack(side="left", padx=(0, 4))
            self.btn_copy_logs_top.pack(side="left", padx=(0, 4))
        else:
            self.btn_clear_logs.pack_forget()
            self.btn_copy_logs_top.pack_forget()

        # Показываем нужный фрейм
        if tab_idx == 0:
            self.frame_launch.pack(fill="both", expand=True)
            self._refresh_launch_values()
        elif tab_idx == 1:
            self.frame_settings.pack(fill="both", expand=True)
        elif tab_idx == 2:
            self.frame_logs.pack(fill="both", expand=True)
        elif tab_idx == 3:
            self.frame_info.pack(fill="both", expand=True)

        # Обновляем подсветку активной кнопки в нижней панели
        for i, btn in enumerate(self.nav_buttons):
            if i == tab_idx:
                btn.configure(
                    fg_color=self.c["nav_pill_active"],
                    text_color=self.c["nav_text_active"],
                )
            else:
                btn.configure(
                    fg_color="transparent",
                    text_color=self.c["nav_text_inactive"],
                )

    # =========================================================================
    # Логика действий
    # =========================================================================
    def _toggle_proxy(self):
        if self.is_running_fn():
            self.stop_proxy_fn()
        else:
            self.start_proxy_fn()
        self._update_status_display()

    def _apply_in_telegram(self):
        url = self._get_tg_url()
        try:
            subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
        pyperclip.copy(self._get_http_proxy_url())
        self.btn_apply.configure(text="✓ Ссылка скопирована!")
        self.root.after(2000, lambda: self.btn_apply.configure(text="Применить в Telegram"))

    def _copy_proxy_link(self):
        pyperclip.copy(self._get_http_proxy_url())

    def _get_http_proxy_url(self) -> str:
        host = self.config.get("host", "127.0.0.1")
        port = self.config.get("port", 1443)
        secret = self.config.get("secret", "")
        return f"https://t.me/proxy?server={host}&port={port}&secret=dd{secret}"

    def _get_tg_url(self) -> str:
        host = self.config.get("host", "127.0.0.1")
        port = self.config.get("port", 1443)
        secret = self.config.get("secret", "")
        return f"tg://proxy?server={host}&port={port}&secret=dd{secret}"

    def _refresh_launch_values(self):
        port = self.config.get("port", 1443)
        pool = self.config.get("pool_size", 4)
        cf = "CF" if self.config.get("fallback_cfproxy", True) else "Direct"

        self.lbl_cf_pill.configure(text=cf)
        self.lbl_pool_pill.configure(text=f"Пул х{pool}")
        self.lbl_port_pill.configure(text=f"Порт {port}")

        self.entry_link.configure(state="normal")
        self.entry_link.delete(0, "end")
        self.entry_link.insert(0, self._get_http_proxy_url())
        self.entry_link.configure(state="readonly")

    def _select_pool_size(self, val: int):
        self.config["pool_size"] = val
        self._update_pool_buttons_visual(val)
        save_config(self.config)
        self._refresh_launch_values()

    def _update_pool_buttons_visual(self, active_val: int):
        for val, btn in self.pool_buttons.items():
            if val == active_val:
                btn.configure(fg_color=self.c["chip_active_bg"], text_color=self.c["chip_active_text"])
            else:
                btn.configure(fg_color=self.c["chip_inactive_bg"], text_color=self.c["chip_inactive_text"])

    def _generate_secret(self):
        sec = secrets.token_hex(16)
        self.cfg_secret_entry.delete(0, "end")
        self.cfg_secret_entry.insert(0, sec)
        self.config["secret"] = sec
        save_config(self.config)
        self._refresh_launch_values()

    def _save_settings(self):
        try:
            self.config["port"] = int(self.cfg_port_entry.get().strip())
        except Exception:
            pass
        self.config["secret"] = self.cfg_secret_entry.get().strip()
        self.config["fallback_cfproxy"] = bool(self.switch_cf.get())
        save_config(self.config)
        self._refresh_launch_values()

    def _save_and_restart(self):
        self._save_settings()
        self.restart_proxy_fn()
        self._switch_tab(0)

    def _toggle_theme(self):
        self.is_dark_mode = not self.is_dark_mode
        self.c = PALETTE_DARK if self.is_dark_mode else PALETTE_LIGHT
        ctk.set_appearance_mode("dark" if self.is_dark_mode else "light")
        # Перерисовываем цвета
        self.root.configure(fg_color=self.c["bg"])
        self._switch_tab(self.current_tab)

    def _update_status_display(self):
        if not self.root:
            return
        running = self.is_running_fn()
        if running:
            self.lbl_status.configure(text="Подключено", text_color=self.c["status_connected"])
            if self.logo_blue_img:
                self.btn_logo.configure(image=self.logo_blue_img)
            self.btn_apply.configure(state="normal")
        else:
            self.lbl_status.configure(text="Отключено", text_color=self.c["status_disconnected"])
            if self.logo_gray_img:
                self.btn_logo.configure(image=self.logo_gray_img)
            self.btn_apply.configure(state="disabled")

    def _start_status_loop(self):
        def _loop():
            if self.root:
                self._update_status_display()
                self.root.after(1500, self._start_status_loop)
        _loop()

    # =========================================================================
    # Логика логов
    # =========================================================================
    def _set_log_filter(self, flt: str):
        self._log_filter = flt
        self._update_log_filter_chips()
        self._render_filtered_logs()

    def _update_log_filter_chips(self):
        for name, btn in [("INFO", self.chip_info), ("ERROR", self.chip_err), ("ALL", self.chip_all)]:
            if self._log_filter == name:
                btn.configure(fg_color=self.c["chip_active_bg"], text_color=self.c["chip_active_text"])
            else:
                btn.configure(fg_color=self.c["chip_inactive_bg"], text_color=self.c["chip_inactive_text"])

    def _start_log_stream(self):
        def _read():
            last_pos = 0
            while True:
                if self.root:
                    try:
                        if LOG_FILE.exists():
                            with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
                                f.seek(last_pos)
                                lines = f.readlines()
                                last_pos = f.tell()
                                if lines:
                                    self._raw_logs.extend(lines)
                                    if len(self._raw_logs) > 200:
                                        self._raw_logs = self._raw_logs[-200:]
                                    self.root.after(0, self._render_filtered_logs)
                    except Exception:
                        pass
                time.sleep(1.0)

        threading.Thread(target=_read, daemon=True, name="log-tailer").start()

    def _render_filtered_logs(self):
        if not self.root:
            return
        lines = []
        for line in self._raw_logs:
            if self._log_filter == "ERROR" and "ERROR" not in line:
                continue
            if self._log_filter == "INFO" and "INFO" not in line and "ERROR" in line:
                continue
            lines.append(line)

        self.log_textbox.delete("1.0", "end")
        self.log_textbox.insert("end", "".join(lines))
        self.log_textbox.see("end")

    def _clear_logs(self):
        self._raw_logs.clear()
        self.log_textbox.delete("1.0", "end")

    def _copy_all_logs(self):
        content = self.log_textbox.get("1.0", "end")
        pyperclip.copy(content)
