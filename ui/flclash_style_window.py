# -*- coding: utf-8 -*-

import collections
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Dict, Optional

import customtkinter as ctk
from PIL import Image, ImageTk
import pyperclip

from proxy import __version__
from utils.tray_common import APP_NAME, LOG_FILE, save_config
from ui.icons import get_ui_icons

IPC_SOCK_PATH = os.path.expanduser("~/.config/TgWsProxy/ipc.sock")


def send_ipc_show() -> bool:
    """Отправляет команду уже запущенному экземпляру развернуть окно."""
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


# Палитра FlClash Material 3 (глубокие плоские поверхности без пиксельных рамок)
FLCLASH_DARK = {
    "rail_bg": "#18181B",
    "bg": "#1F1F24",
    "card_bg": "#28282E",
    "active_pill": "#36353F",
    "active_pill_text": "#F5F3F7",
    "inactive_rail_text": "#9B97A6",
    "text_primary": "#F2F0F5",
    "text_secondary": "#9E9AA8",
    "accent": "#F1A490",
    "accent_hover": "#E59580",
    "accent_text": "#2A1612",
    "btn_secondary_bg": "#33323B",
    "btn_secondary_hover": "#3F3E48",
    "btn_secondary_text": "#E3E0EA",
    "switch_active": "#D2BCFF",
    "status_online": "#4CAF50",
    "status_offline": "#85818E",
    "graph_line": "#D4BBFF",
    "graph_fill": "#2C263A",
    "graph_grid": "#33323D",
    "timer_pill_bg": "#E9B6A9",
    "timer_pill_text": "#2E1510",
    "input_bg": "#24242A",
    "log_bg": "#141418",
    "log_text": "#75E29E",
}

FLCLASH_LIGHT = {
    "rail_bg": "#F0EDF5",
    "bg": "#F8F6FA",
    "card_bg": "#FFFFFF",
    "active_pill": "#E5DCF4",
    "active_pill_text": "#1E192B",
    "inactive_rail_text": "#7A7582",
    "text_primary": "#1C1B20",
    "text_secondary": "#79747E",
    "accent": "#6750A4",
    "accent_hover": "#563F93",
    "accent_text": "#FFFFFF",
    "btn_secondary_bg": "#EFEBF4",
    "btn_secondary_hover": "#E2DCE9",
    "btn_secondary_text": "#2F2B38",
    "switch_active": "#6750A4",
    "status_online": "#388E3C",
    "status_offline": "#8E8896",
    "graph_line": "#6750A4",
    "graph_fill": "#EFE7F8",
    "graph_grid": "#EAE5F0",
    "timer_pill_bg": "#E8DEF8",
    "timer_pill_text": "#21005D",
    "input_bg": "#F4F1F7",
    "log_bg": "#1A1A20",
    "log_text": "#50FA7B",
}

FONT_FAMILY = "Noto Sans"


class FlClashWindow:
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

        self.current_theme = self.config.get("theme", "dark")
        ctk.set_appearance_mode(self.current_theme)

        self.root = ctk.CTk()
        self.root.title("FlClash — Telegram WS Proxy")
        self.root.geometry("960x640")
        self.root.minsize(860, 580)

        self.icons = get_ui_icons(is_dark=(self.current_theme == "dark"))

        self.speed_history = collections.deque([0.0] * 30, maxlen=30)
        self.start_timestamp: Optional[float] = None
        self.current_page = "dashboard"
        self._running = True
        self._log_pos = 0

        self._setup_ipc_server()
        self._build_ui()
        self._apply_theme()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close_requested)
        self.root.after(1000, self._periodic_stats_update)
        self.root.after(1200, self._poll_logs)

    @property
    def colors(self) -> Dict[str, str]:
        return FLCLASH_DARK if self.current_theme == "dark" else FLCLASH_LIGHT

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
        self.root.destroy()
        os._exit(0)

    # ========================== ПОСТРОЕНИЕ UI ==========================
    def _build_ui(self):
        c = self.colors

        self.main_container = ctk.CTkFrame(self.root, fg_color=c["bg"], corner_radius=0)
        self.main_container.pack(fill="both", expand=True)

        # Navigation Rail (Левая колонка)
        self.nav_rail = ctk.CTkFrame(
            self.main_container,
            fg_color=c["rail_bg"],
            width=100,
            corner_radius=0,
        )
        self.nav_rail.pack(side="left", fill="y")
        self.nav_rail.pack_propagate(False)

        # Логотип (чистая сглаженная векторная иконка молнии)
        self.logo_frame = ctk.CTkFrame(self.nav_rail, fg_color="transparent")
        self.logo_frame.pack(side="top", fill="x", pady=(24, 18))

        self.logo_lbl = ctk.CTkLabel(
            self.logo_frame,
            image=self.icons["logo"],
            text="",
        )
        self.logo_lbl.pack()

        # Кнопки страниц
        self.nav_buttons_frame = ctk.CTkFrame(self.nav_rail, fg_color="transparent")
        self.nav_buttons_frame.pack(side="top", fill="x", expand=True)

        self.nav_items = [
            ("dashboard", "Dashboard"),
            ("proxies", "Proxies"),
            ("logs", "Logs"),
            ("settings", "Settings"),
        ]

        self.nav_widgets = {}
        for page_id, title in self.nav_items:
            item_frame = ctk.CTkFrame(
                self.nav_buttons_frame,
                fg_color="transparent",
                cursor="hand2",
            )
            item_frame.pack(fill="x", pady=4, padx=8)

            # Никаких border_width! Только чистый flat фон с радиусом 8
            pill = ctk.CTkFrame(
                item_frame,
                fg_color="transparent",
                corner_radius=8,
                border_width=0,
                height=52,
            )
            pill.pack(fill="x", padx=2)
            pill.pack_propagate(False)

            icon_lbl = ctk.CTkLabel(
                pill,
                image=self.icons[f"{page_id}_inactive"],
                text="",
            )
            icon_lbl.pack(pady=(6, 0))

            text_lbl = ctk.CTkLabel(
                pill,
                text=title,
                font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
                text_color=c["inactive_rail_text"],
            )
            text_lbl.pack(pady=(2, 4))

            def _bind_click(w, pid=page_id):
                w.bind("<Button-1>", lambda e: self.switch_page(pid))

            _bind_click(item_frame)
            _bind_click(pill)
            _bind_click(icon_lbl)
            _bind_click(text_lbl)

            self.nav_widgets[page_id] = {
                "pill": pill,
                "icon": icon_lbl,
                "text": text_lbl,
            }

        # Нижняя часть левой панели (Тема и Выход)
        self.rail_footer = ctk.CTkFrame(self.nav_rail, fg_color="transparent")
        self.rail_footer.pack(side="bottom", fill="x", pady=(0, 20), padx=10)

        self.theme_btn = ctk.CTkButton(
            self.rail_footer,
            image=self.icons["theme"],
            text="",
            width=46,
            height=36,
            corner_radius=8,
            border_width=0,
            fg_color=c["btn_secondary_bg"],
            hover_color=c["btn_secondary_hover"],
            command=self.toggle_theme,
        )
        self.theme_btn.pack(pady=4)

        self.exit_btn = ctk.CTkButton(
            self.rail_footer,
            image=self.icons["exit"],
            text="",
            width=46,
            height=36,
            corner_radius=8,
            border_width=0,
            fg_color="#362222" if self.current_theme == "dark" else "#FCE4E4",
            hover_color="#482A2A" if self.current_theme == "dark" else "#F8D1D1",
            command=self.exit_app,
        )
        self.exit_btn.pack(pady=4)

        # Контентная область справа
        self.content_area = ctk.CTkFrame(
            self.main_container,
            fg_color=c["bg"],
            corner_radius=0,
        )
        self.content_area.pack(side="right", fill="both", expand=True, padx=24, pady=20)

        # Header
        self.header_frame = ctk.CTkFrame(self.content_area, fg_color="transparent")
        self.header_frame.pack(side="top", fill="x", pady=(0, 16))

        self.page_title_lbl = ctk.CTkLabel(
            self.header_frame,
            text="Dashboard",
            font=ctk.CTkFont(family=FONT_FAMILY, size=24, weight="bold"),
            text_color=c["text_primary"],
        )
        self.page_title_lbl.pack(side="left")

        # Статус-иконка (гладкая векторная галочка или пауза)
        self.status_icon_lbl = ctk.CTkLabel(
            self.header_frame,
            image=self.icons["status_ok"] if self.is_proxy_running() else self.icons["status_off"],
            text="",
        )
        self.status_icon_lbl.pack(side="right", padx=(8, 0))

        # Страницы
        self.pages_container = ctk.CTkFrame(self.content_area, fg_color="transparent")
        self.pages_container.pack(fill="both", expand=True)

        self._build_dashboard_page()
        self._build_proxies_page()
        self._build_logs_page()
        self._build_settings_page()

        self.switch_page("dashboard")

    # ========================== DASHBOARD ==========================
    def _build_dashboard_page(self):
        c = self.colors
        self.page_dashboard = ctk.CTkFrame(self.pages_container, fg_color="transparent")

        self.page_dashboard.grid_columnconfigure(0, weight=3)
        self.page_dashboard.grid_columnconfigure(1, weight=2)
        self.page_dashboard.grid_rowconfigure(0, weight=1)
        self.page_dashboard.grid_rowconfigure(1, weight=1)

        # Карточка 1: Network Speed
        self.card_speed = ctk.CTkFrame(
            self.page_dashboard,
            fg_color=c["card_bg"],
            corner_radius=10,
            border_width=0,  # Убираем пиксельные рамки!
        )
        self.card_speed.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=(0, 10))

        speed_header = ctk.CTkFrame(self.card_speed, fg_color="transparent")
        speed_header.pack(fill="x", padx=16, pady=(14, 8))

        lbl_speed_title = ctk.CTkLabel(
            speed_header,
            text="Network speed",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=c["text_primary"],
        )
        lbl_speed_title.pack(side="left")

        self.lbl_speed_values = ctk.CTkLabel(
            speed_header,
            text="↑ 0.0 KB/s   ↓ 0.0 KB/s",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=c["text_secondary"],
        )
        self.lbl_speed_values.pack(side="right")

        self.speed_canvas = ctk.CTkCanvas(
            self.card_speed,
            bg=c["card_bg"],
            highlightthickness=0,
            bd=0,
        )
        self.speed_canvas.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.speed_canvas.bind("<Configure>", lambda e: self._draw_graph())

        # Карточка 2: Proxy Status & Telegram Button
        self.card_proxy = ctk.CTkFrame(
            self.page_dashboard,
            fg_color=c["card_bg"],
            corner_radius=10,
            border_width=0,
        )
        self.card_proxy.grid(row=0, column=1, sticky="nsew", padx=(10, 0), pady=(0, 10))

        proxy_header = ctk.CTkFrame(self.card_proxy, fg_color="transparent")
        proxy_header.pack(fill="x", padx=16, pady=(14, 6))

        lbl_tg_title = ctk.CTkLabel(
            proxy_header,
            text="Telegram Proxy",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=c["text_primary"],
        )
        lbl_tg_title.pack(side="left")

        self.proxy_switch_var = ctk.StringVar(value="on" if self.is_proxy_running() else "off")
        self.proxy_switch = ctk.CTkSwitch(
            proxy_header,
            text="",
            variable=self.proxy_switch_var,
            onvalue="on",
            offvalue="off",
            command=self._on_switch_toggled,
            progress_color=c["switch_active"],
            width=46,
        )
        self.proxy_switch.pack(side="right")

        self.lbl_proxy_status_desc = ctk.CTkLabel(
            self.card_proxy,
            text="Служба активна и принимает соединения" if self.is_proxy_running() else "Служба остановлена",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=c["status_online"] if self.is_proxy_running() else c["status_offline"],
        )
        self.lbl_proxy_status_desc.pack(anchor="w", padx=16, pady=(0, 14))

        self.btn_open_tg = ctk.CTkButton(
            self.card_proxy,
            text="Подключить в Telegram",
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
            fg_color=c["accent"],
            hover_color=c["accent_hover"],
            text_color=c["accent_text"],
            height=40,
            corner_radius=8,
            border_width=0,
            command=self._on_open_in_telegram,
        )
        self.btn_open_tg.pack(fill="x", padx=16, pady=(4, 6))

        self.btn_copy_link = ctk.CTkButton(
            self.card_proxy,
            text="Скопировать ссылку",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            fg_color=c["btn_secondary_bg"],
            hover_color=c["btn_secondary_hover"],
            text_color=c["btn_secondary_text"],
            height=34,
            corner_radius=8,
            border_width=0,
            command=self._on_copy_link,
        )
        self.btn_copy_link.pack(fill="x", padx=16, pady=(4, 12))

        # Карточка 3: Traffic usage
        self.card_traffic = ctk.CTkFrame(
            self.page_dashboard,
            fg_color=c["card_bg"],
            corner_radius=10,
            border_width=0,
        )
        self.card_traffic.grid(row=1, column=0, sticky="nsew", padx=(0, 10), pady=(10, 0))

        traffic_header = ctk.CTkFrame(self.card_traffic, fg_color="transparent")
        traffic_header.pack(fill="x", padx=16, pady=(14, 8))

        lbl_traffic_title = ctk.CTkLabel(
            traffic_header,
            text="Traffic usage",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=c["text_primary"],
        )
        lbl_traffic_title.pack(side="left")

        traffic_body = ctk.CTkFrame(self.card_traffic, fg_color="transparent")
        traffic_body.pack(fill="both", expand=True, padx=16, pady=(0, 14))

        self.lbl_traffic_up = ctk.CTkLabel(
            traffic_body,
            text="↑ Загрузка (Upload):  0.00 MB",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=c["text_secondary"],
            anchor="w",
        )
        self.lbl_traffic_up.pack(fill="x", pady=3)

        self.lbl_traffic_down = ctk.CTkLabel(
            traffic_body,
            text="↓ Выгрузка (Download):  0.00 MB",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=c["text_secondary"],
            anchor="w",
        )
        self.lbl_traffic_down.pack(fill="x", pady=3)

        lbl_intranet = ctk.CTkLabel(
            traffic_body,
            text=f"Local Endpoint: {self.config.get('host', '127.0.0.1')}:{self.config.get('port', 1080)}",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            text_color=c["text_secondary"],
            anchor="w",
        )
        lbl_intranet.pack(fill="x", pady=(6, 0))

        # Карточка 4: Cloudflare Routing & Timer
        self.card_conn = ctk.CTkFrame(
            self.page_dashboard,
            fg_color=c["card_bg"],
            corner_radius=10,
            border_width=0,
        )
        self.card_conn.grid(row=1, column=1, sticky="nsew", padx=(10, 0), pady=(10, 0))

        conn_header = ctk.CTkFrame(self.card_conn, fg_color="transparent")
        conn_header.pack(fill="x", padx=16, pady=(14, 8))

        lbl_conn_title = ctk.CTkLabel(
            conn_header,
            text="Cloudflare Routing",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=c["text_primary"],
        )
        lbl_conn_title.pack(side="left")

        conn_body = ctk.CTkFrame(self.card_conn, fg_color="transparent")
        conn_body.pack(fill="both", expand=True, padx=16, pady=(0, 14))

        self.lbl_cf_mode = ctk.CTkLabel(
            conn_body,
            text="• Режим: Dynamic Pool (Auto)",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=c["status_online"],
            anchor="w",
        )
        self.lbl_cf_mode.pack(fill="x", pady=2)

        self.lbl_mask_host = ctk.CTkLabel(
            conn_body,
            text="• Mask Host: www.cloudflare.com",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=c["text_secondary"],
            anchor="w",
        )
        self.lbl_mask_host.pack(fill="x", pady=2)

        # Капсула таймера в стиле FlClash
        self.timer_pill = ctk.CTkFrame(
            conn_body,
            fg_color=c["timer_pill_bg"],
            corner_radius=8,
            border_width=0,
            height=30,
        )
        self.timer_pill.pack(side="bottom", anchor="e", pady=(8, 0))

        self.lbl_timer_text = ctk.CTkLabel(
            self.timer_pill,
            text="00:00:00",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=c["timer_pill_text"],
        )
        self.lbl_timer_text.pack(padx=12, pady=4)

    # ========================== PROXIES ==========================
    def _build_proxies_page(self):
        c = self.colors
        self.page_proxies = ctk.CTkFrame(self.pages_container, fg_color="transparent")

        info_frame = ctk.CTkFrame(self.page_proxies, fg_color=c["card_bg"], corner_radius=10, border_width=0)
        info_frame.pack(fill="x", pady=(0, 12))

        lbl_desc = ctk.CTkLabel(
            info_frame,
            text="Маршруты Telegram Data Centers через защищенный Cloudflare туннель:",
            font=ctk.CTkFont(family=FONT_FAMILY, size=13),
            text_color=c["text_secondary"],
        )
        lbl_desc.pack(padx=16, pady=12, anchor="w")

        self.scroll_proxies = ctk.CTkScrollableFrame(
            self.page_proxies,
            fg_color="transparent",
        )
        self.scroll_proxies.pack(fill="both", expand=True)

        dcs = [
            ("DC 1 (Miami, US)", "149.154.175.50", "28 ms"),
            ("DC 2 (Amsterdam, NL)", "149.154.167.51", "34 ms"),
            ("DC 3 (Miami, US)", "149.154.175.100", "29 ms"),
            ("DC 4 (Amsterdam, NL - Главный)", "149.154.167.91", "24 ms"),
            ("DC 5 (Singapore, SG)", "91.108.56.170", "85 ms"),
        ]

        for name, ip, ping in dcs:
            row = ctk.CTkFrame(
                self.scroll_proxies,
                fg_color=c["card_bg"],
                corner_radius=8,
                border_width=0,
                height=52,
            )
            row.pack(fill="x", pady=4)
            row.pack_propagate(False)

            lbl_name = ctk.CTkLabel(
                row,
                text=name,
                font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
                text_color=c["text_primary"],
            )
            lbl_name.pack(side="left", padx=16)

            lbl_ip = ctk.CTkLabel(
                row,
                text=ip,
                font=ctk.CTkFont(family=FONT_FAMILY, size=12),
                text_color=c["text_secondary"],
            )
            lbl_ip.pack(side="left", padx=8)

            badge = ctk.CTkLabel(
                row,
                text=ping,
                fg_color="#243828" if self.current_theme == "dark" else "#E8F5E9",
                text_color="#4CAF50",
                font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
                corner_radius=6,
                width=54,
                height=24,
            )
            badge.pack(side="right", padx=16)

    # ========================== LOGS ==========================
    def _build_logs_page(self):
        c = self.colors
        self.page_logs = ctk.CTkFrame(self.pages_container, fg_color="transparent")

        log_bar = ctk.CTkFrame(self.page_logs, fg_color="transparent")
        log_bar.pack(fill="x", pady=(0, 10))

        btn_copy = ctk.CTkButton(
            log_bar,
            text="Скопировать логи",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            fg_color=c["btn_secondary_bg"],
            hover_color=c["btn_secondary_hover"],
            text_color=c["btn_secondary_text"],
            height=32,
            corner_radius=8,
            border_width=0,
            command=self._on_copy_all_logs,
        )
        btn_copy.pack(side="left", padx=(0, 8))

        btn_clear = ctk.CTkButton(
            log_bar,
            text="Очистить",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            fg_color=c["btn_secondary_bg"],
            hover_color=c["btn_secondary_hover"],
            text_color=c["btn_secondary_text"],
            height=32,
            corner_radius=8,
            border_width=0,
            command=self._on_clear_logs,
        )
        btn_clear.pack(side="left")

        self.log_textbox = ctk.CTkTextbox(
            self.page_logs,
            fg_color=c["log_bg"],
            text_color=c["log_text"],
            font=ctk.CTkFont(family="monospace", size=11),
            corner_radius=8,
            border_width=0,
        )
        self.log_textbox.pack(fill="both", expand=True)

    # ========================== SETTINGS ==========================
    def _build_settings_page(self):
        c = self.colors
        self.page_settings = ctk.CTkScrollableFrame(self.pages_container, fg_color="transparent")

        def _make_setting_card(title: str, subtitle: str, widget_factory):
            card = ctk.CTkFrame(
                self.page_settings,
                fg_color=c["card_bg"],
                corner_radius=8,
                border_width=0,
            )
            card.pack(fill="x", pady=6)

            text_box = ctk.CTkFrame(card, fg_color="transparent")
            text_box.pack(side="left", padx=16, pady=12)

            t_lbl = ctk.CTkLabel(
                text_box,
                text=title,
                font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
                text_color=c["text_primary"],
                anchor="w",
            )
            t_lbl.pack(fill="x")

            s_lbl = ctk.CTkLabel(
                text_box,
                text=subtitle,
                font=ctk.CTkFont(family=FONT_FAMILY, size=11),
                text_color=c["text_secondary"],
                anchor="w",
            )
            s_lbl.pack(fill="x")

            w = widget_factory(card)
            w.pack(side="right", padx=16, pady=12)
            return card

        self.port_entry = ctk.CTkEntry(
            self.page_settings,
            width=90,
            height=32,
            fg_color=c["input_bg"],
            border_width=0,
            corner_radius=6,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
        )
        self.port_entry.insert(0, str(self.config.get("port", 1080)))

        _make_setting_card(
            "Порт прокси",
            "Локальный порт для подключения Telegram клиента",
            lambda parent: self.port_entry,
        )

        self.host_entry = ctk.CTkEntry(
            self.page_settings,
            width=140,
            height=32,
            fg_color=c["input_bg"],
            border_width=0,
            corner_radius=6,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
        )
        self.host_entry.insert(0, str(self.config.get("host", "127.0.0.1")))

        _make_setting_card(
            "Хост прослушивания",
            "IP-адрес для привязки службы (127.0.0.1 для локального доступа)",
            lambda parent: self.host_entry,
        )

        self.secret_entry = ctk.CTkEntry(
            self.page_settings,
            width=260,
            height=32,
            fg_color=c["input_bg"],
            border_width=0,
            corner_radius=6,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
        )
        self.secret_entry.insert(0, str(self.config.get("secret", "")))

        _make_setting_card(
            "Секрет MTProto",
            "Ключ шифрования трафика с маскировкой под TLS",
            lambda parent: self.secret_entry,
        )

        self.minimize_var = ctk.BooleanVar(value=self.config.get("minimize_to_tray_on_close", True))
        self.switch_minimize = ctk.CTkSwitch(
            self.page_settings,
            text="",
            variable=self.minimize_var,
            progress_color=c["switch_active"],
            command=self._on_settings_changed,
        )

        _make_setting_card(
            "Сворачивать в трей при закрытии",
            "При нажатии на крестик окно скрывается, а прокси продолжает работать",
            lambda parent: self.switch_minimize,
        )

        btn_save = ctk.CTkButton(
            self.page_settings,
            text="Сохранить и перезапустить",
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
            fg_color=c["accent"],
            hover_color=c["accent_hover"],
            text_color=c["accent_text"],
            height=38,
            corner_radius=8,
            border_width=0,
            command=self._save_settings,
        )
        btn_save.pack(fill="x", pady=(16, 6))

        btn_full_exit = ctk.CTkButton(
            self.page_settings,
            text="Полностью выйти из программы",
            font=ctk.CTkFont(family=FONT_FAMILY, size=13),
            fg_color="#362222" if self.current_theme == "dark" else "#FFEBEE",
            hover_color="#482A2A" if self.current_theme == "dark" else "#FFCDD2",
            text_color="#FF6B6B" if self.current_theme == "dark" else "#C62828",
            height=38,
            corner_radius=8,
            border_width=0,
            command=self.exit_app,
        )
        btn_full_exit.pack(fill="x", pady=(4, 16))

    # ========================== ПЕРЕКЛЮЧЕНИЕ СТРАНИЦ ==========================
    def switch_page(self, page_id: str):
        self.current_page = page_id
        c = self.colors

        titles = {
            "dashboard": "Dashboard",
            "proxies": "Proxies",
            "logs": "Logs",
            "settings": "Settings",
        }
        self.page_title_lbl.configure(text=titles.get(page_id, "Dashboard"))

        for pid, w in self.nav_widgets.items():
            if pid == page_id:
                w["pill"].configure(fg_color=c["active_pill"])
                w["icon"].configure(image=self.icons[f"{pid}_active"])
                w["text"].configure(text_color=c["active_pill_text"])
            else:
                w["pill"].configure(fg_color="transparent")
                w["icon"].configure(image=self.icons[f"{pid}_inactive"])
                w["text"].configure(text_color=c["inactive_rail_text"])

        for p in [self.page_dashboard, self.page_proxies, self.page_logs, self.page_settings]:
            p.pack_forget()

        if page_id == "dashboard":
            self.page_dashboard.pack(fill="both", expand=True)
            self._draw_graph()
        elif page_id == "proxies":
            self.page_proxies.pack(fill="both", expand=True)
        elif page_id == "logs":
            self.page_logs.pack(fill="both", expand=True)
        elif page_id == "settings":
            self.page_settings.pack(fill="both", expand=True)

    # ========================== ГРАФИК ==========================
    def _draw_graph(self):
        if self.current_page != "dashboard":
            return

        w = self.speed_canvas.winfo_width()
        h = self.speed_canvas.winfo_height()
        if w < 50 or h < 50:
            return

        c = self.colors
        self.speed_canvas.delete("all")
        self.speed_canvas.configure(bg=c["card_bg"])

        for y_step in range(1, 4):
            y = int(h * y_step / 4)
            self.speed_canvas.create_line(0, y, w, y, fill=c["graph_grid"], dash=(2, 4))

        points = list(self.speed_history)
        max_val = max(points) if max(points) > 5.0 else 5.0

        n = len(points)
        coords = []
        for i, val in enumerate(points):
            x = int(i * (w / (n - 1)))
            y = int(h - 10 - (val / max_val) * (h - 25))
            coords.append((x, y))

        poly_points = [coords[0][0], h]
        for x, y in coords:
            poly_points.extend([x, y])
        poly_points.extend([coords[-1][0], h])

        self.speed_canvas.create_polygon(
            poly_points,
            fill=c["graph_fill"],
            outline="",
        )

        flat_coords = []
        for x, y in coords:
            flat_coords.extend([x, y])
        if len(flat_coords) >= 4:
            self.speed_canvas.create_line(
                flat_coords,
                fill=c["graph_line"],
                width=2,
                smooth=True,
            )

    # ========================== ТЕМА ==========================
    def toggle_theme(self):
        self.current_theme = "light" if self.current_theme == "dark" else "dark"
        self.config["theme"] = self.current_theme
        ctk.set_appearance_mode(self.current_theme)
        self.icons = get_ui_icons(is_dark=(self.current_theme == "dark"))
        self._apply_theme()
        if self.on_save_config:
            self.on_save_config(self.config)

    def _apply_theme(self):
        c = self.colors
        self.main_container.configure(fg_color=c["bg"])
        self.nav_rail.configure(fg_color=c["rail_bg"])
        self.content_area.configure(fg_color=c["bg"])
        self.page_title_lbl.configure(text_color=c["text_primary"])
        self.logo_lbl.configure(image=self.icons["logo"])
        self.theme_btn.configure(
            image=self.icons["theme"],
            fg_color=c["btn_secondary_bg"],
            hover_color=c["btn_secondary_hover"],
        )
        self.exit_btn.configure(
            image=self.icons["exit"],
            fg_color="#362222" if self.current_theme == "dark" else "#FCE4E4",
            hover_color="#482A2A" if self.current_theme == "dark" else "#F8D1D1",
        )
        for card in [self.card_speed, self.card_proxy, self.card_traffic, self.card_conn]:
            card.configure(fg_color=c["card_bg"])
        self.btn_open_tg.configure(fg_color=c["accent"], hover_color=c["accent_hover"], text_color=c["accent_text"])
        self.btn_copy_link.configure(fg_color=c["btn_secondary_bg"], hover_color=c["btn_secondary_hover"], text_color=c["btn_secondary_text"])
        self.timer_pill.configure(fg_color=c["timer_pill_bg"])
        self.lbl_timer_text.configure(text_color=c["timer_pill_text"])
        self.switch_page(self.current_page)

    def _on_switch_toggled(self):
        val = self.proxy_switch_var.get()
        if val == "on":
            self.on_start_proxy()
            if not self.start_timestamp:
                self.start_timestamp = time.time()
        else:
            self.on_stop_proxy()
            self.start_timestamp = None

        self._update_status_views()

    def _update_status_views(self):
        c = self.colors
        running = self.is_proxy_running()
        self.proxy_switch_var.set("on" if running else "off")
        self.status_icon_lbl.configure(
            image=self.icons["status_ok"] if running else self.icons["status_off"]
        )
        self.lbl_proxy_status_desc.configure(
            text="Служба активна и принимает соединения" if running else "Служба остановлена",
            text_color=c["status_online"] if running else c["status_offline"],
        )

    def _on_open_in_telegram(self):
        url = self.get_proxy_url()
        try:
            pyperclip.copy(url)
        except Exception:
            pass
        try:
            subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    def _on_copy_link(self):
        url = self.get_proxy_url()
        try:
            pyperclip.copy(url)
            self.btn_copy_link.configure(text="Ссылка скопирована!")
            self.root.after(2000, lambda: self.btn_copy_link.configure(text="Скопировать ссылку"))
        except Exception:
            pass

    def _on_copy_all_logs(self):
        try:
            txt = self.log_textbox.get("1.0", "end")
            pyperclip.copy(txt)
        except Exception:
            pass

    def _on_clear_logs(self):
        self.log_textbox.delete("1.0", "end")
        self._log_pos = 0

    def _on_settings_changed(self):
        self.config["minimize_to_tray_on_close"] = self.minimize_var.get()
        if self.on_save_config:
            self.on_save_config(self.config)

    def _save_settings(self):
        try:
            port = int(self.port_entry.get().strip())
            self.config["port"] = port
        except ValueError:
            pass

        self.config["host"] = self.host_entry.get().strip() or "127.0.0.1"
        self.config["secret"] = self.secret_entry.get().strip()
        self.config["minimize_to_tray_on_close"] = self.minimize_var.get()

        if self.on_save_config:
            self.on_save_config(self.config)

        self.on_restart_proxy()
        self._update_status_views()

    def _periodic_stats_update(self):
        if not self._running:
            return

        running = self.is_proxy_running()
        self._update_status_views()

        if running:
            if not self.start_timestamp:
                self.start_timestamp = time.time()
            elapsed = int(time.time() - self.start_timestamp)
            hrs = elapsed // 3600
            mins = (elapsed % 3600) // 60
            secs = elapsed % 60
            self.lbl_timer_text.configure(text=f"{hrs:02d}:{mins:02d}:{secs:02d}")
            self.speed_history.append(0.5 if running else 0.0)
        else:
            self.start_timestamp = None
            self.lbl_timer_text.configure(text="00:00:00")
            self.speed_history.append(0.0)

        self._draw_graph()

        if self._running:
            self.root.after(1000, self._periodic_stats_update)

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

                    if new_text and hasattr(self, "log_textbox"):
                        self.log_textbox.insert("end", new_text)
                        self.log_textbox.see("end")
        except Exception:
            pass

        if self._running:
            self.root.after(1500, self._poll_logs)

    def run(self):
        self.root.mainloop()
