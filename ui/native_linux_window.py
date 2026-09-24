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
    """Отправляет команду уже работающему приложению развернуть окно."""
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


class NativeLinuxAppWindow:
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

        # Создаем нативное главное окно
        self.root = tk.Tk()
        self.root.title("TG WS Proxy — Telegram MTProto Bridge")
        self.root.geometry("580x620")
        self.root.minsize(520, 560)

        # Настройка стандартной системной темы Linux
        self.style = ttk.Style()
        if "clam" in self.style.theme_names():
            self.style.theme_use("clam")

        # Шрифт интерфейса
        default_font = ("DejaVu Sans", 10)
        bold_font = ("DejaVu Sans", 10, "bold")
        title_font = ("DejaVu Sans", 14, "bold")
        status_font = ("DejaVu Sans", 12, "bold")

        self.style.configure(".", font=default_font)
        self.style.configure("TLabel", font=default_font)
        self.style.configure("TButton", font=default_font, padding=6)
        self.style.configure("TNotebook.Tab", font=bold_font, padding=(12, 6))
        self.style.configure("Header.TLabel", font=title_font)
        self.style.configure("Status.TLabel", font=status_font)
        self.style.configure("Accent.TButton", font=bold_font, padding=8)

        # Иконка окна
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

    def _build_ui(self):
        main_frame = ttk.Frame(self.root, padding=12)
        main_frame.pack(fill="both", expand=True)

        # Системные вкладки Linux (Notebook)
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(fill="both", expand=True)

        self.tab_main = ttk.Frame(self.notebook, padding=14)
        self.tab_settings = ttk.Frame(self.notebook, padding=14)
        self.tab_logs = ttk.Frame(self.notebook, padding=14)
        self.tab_about = ttk.Frame(self.notebook, padding=14)

        self.notebook.add(self.tab_main, text=" Главная ")
        self.notebook.add(self.tab_settings, text=" Настройки ")
        self.notebook.add(self.tab_logs, text=" Журнал ")
        self.notebook.add(self.tab_about, text=" О программе ")

        self._build_main_tab()
        self._build_settings_tab()
        self._build_logs_tab()
        self._build_about_tab()

    # ========================== ВКЛАДКА ГЛАВНАЯ ==========================
    def _build_main_tab(self):
        # 1. Заголовок и статус
        header_frame = ttk.Frame(self.tab_main)
        header_frame.pack(fill="x", pady=(0, 10))

        title_lbl = ttk.Label(header_frame, text="TG WS Proxy", style="Header.TLabel")
        title_lbl.pack(anchor="w")

        sub_lbl = ttk.Label(
            header_frame,
            text="Telegram WebSocket Bridge с защитой от блокировок РКН",
            foreground="#555555",
        )
        sub_lbl.pack(anchor="w", pady=(2, 0))

        # 2. Карточка статуса соединения
        status_box = ttk.LabelFrame(self.tab_main, text=" Состояние службы ", padding=12)
        status_box.pack(fill="x", pady=8)

        status_row = ttk.Frame(status_box)
        status_row.pack(fill="x", pady=4)

        ttk.Label(status_row, text="Статус: ").pack(side="left")
        self.lbl_status_val = ttk.Label(
            status_row,
            text="Подключено" if self.is_proxy_running() else "Остановлено",
            style="Status.TLabel",
            foreground="#2E7D32" if self.is_proxy_running() else "#C62828",
        )
        self.lbl_status_val.pack(side="left", padx=6)

        # Кнопка включения/выключения
        self.btn_toggle_proxy = ttk.Button(
            status_box,
            text="Остановить прокси" if self.is_proxy_running() else "Запустить прокси",
            command=self._on_toggle_proxy,
        )
        self.btn_toggle_proxy.pack(fill="x", pady=(8, 4))

        # 3. Главные кнопки действий
        actions_box = ttk.LabelFrame(self.tab_main, text=" Подключение клиента ", padding=12)
        actions_box.pack(fill="x", pady=8)

        self.btn_apply_tg = ttk.Button(
            actions_box,
            text="🚀  Применить в Telegram",
            style="Accent.TButton",
            command=self._on_apply_telegram,
        )
        self.btn_apply_tg.pack(fill="x", pady=4)

        self.btn_copy_url = ttk.Button(
            actions_box,
            text="📋  Скопировать ссылку подключения",
            command=self._on_copy_link,
        )
        self.btn_copy_url.pack(fill="x", pady=4)

        # 4. Параметры прокси (как на Android-экране)
        params_box = ttk.LabelFrame(self.tab_main, text=" Параметры соединения ", padding=12)
        params_box.pack(fill="x", pady=8)

        def _make_param_row(parent, label_text, val_text):
            r = ttk.Frame(parent)
            r.pack(fill="x", pady=3)
            ttk.Label(r, text=label_text, width=18, anchor="w").pack(side="left")
            val_lbl = ttk.Label(r, text=val_text, font=("DejaVu Sans", 9, "bold"))
            val_lbl.pack(side="left")
            return val_lbl

        self.lbl_param_host = _make_param_row(params_box, "Локальный адрес:", f"{self.config.get('host', '127.0.0.1')}:{self.config.get('port', 1080)}")
        self.lbl_param_secret = _make_param_row(params_box, "Секрет MTProto:", f"{str(self.config.get('secret', ''))[:16]}...")
        _make_param_row(params_box, "Cloudflare туннель:", "Включен (Smart Dynamic Pool)")
        _make_param_row(params_box, "Маскировка:", "TLS / www.cloudflare.com")

        # 5. Нижняя панель действий
        bottom_row = ttk.Frame(self.tab_main)
        bottom_row.pack(side="bottom", fill="x", pady=(10, 0))

        self.btn_exit = ttk.Button(
            bottom_row,
            text="Выход из программы",
            command=self.exit_app,
        )
        self.btn_exit.pack(side="right")

    # ========================== ВКЛАДКА НАСТРОЙКИ ==========================
    def _build_settings_tab(self):
        settings_box = ttk.LabelFrame(self.tab_settings, text=" Основные параметры ", padding=12)
        settings_box.pack(fill="x", pady=6)

        # Порт
        p_row = ttk.Frame(settings_box)
        p_row.pack(fill="x", pady=5)
        ttk.Label(p_row, text="Порт прокси:", width=20, anchor="w").pack(side="left")
        self.entry_port = ttk.Entry(p_row, width=12)
        self.entry_port.insert(0, str(self.config.get("port", 1080)))
        self.entry_port.pack(side="left")

        # Хост
        h_row = ttk.Frame(settings_box)
        h_row.pack(fill="x", pady=5)
        ttk.Label(h_row, text="Хост прослушивания:", width=20, anchor="w").pack(side="left")
        self.entry_host = ttk.Entry(h_row, width=18)
        self.entry_host.insert(0, str(self.config.get("host", "127.0.0.1")))
        self.entry_host.pack(side="left")

        # Секрет
        s_row = ttk.Frame(settings_box)
        s_row.pack(fill="x", pady=5)
        ttk.Label(s_row, text="Секрет MTProto:", width=20, anchor="w").pack(side="left")
        self.entry_secret = ttk.Entry(s_row)
        self.entry_secret.insert(0, str(self.config.get("secret", "")))
        self.entry_secret.pack(side="left", fill="x", expand=True, padx=(0, 6))

        btn_gen_sec = ttk.Button(s_row, text="Создать", width=8, command=self._generate_secret)
        btn_gen_sec.pack(side="right")

        # Поведение окна
        tray_box = ttk.LabelFrame(self.tab_settings, text=" Поведение и системный трей ", padding=12)
        tray_box.pack(fill="x", pady=6)

        self.var_minimize = tk.BooleanVar(value=self.config.get("minimize_to_tray_on_close", True))
        chk_min = ttk.Checkbutton(
            tray_box,
            text="Сворачивать в системный трей при закрытии крестиком",
            variable=self.var_minimize,
            command=self._on_settings_check_changed,
        )
        chk_min.pack(anchor="w", pady=4)

        # Кнопка сохранения
        btn_save = ttk.Button(
            self.tab_settings,
            text="💾  Сохранить и перезапустить службу",
            style="Accent.TButton",
            command=self._save_settings,
        )
        btn_save.pack(fill="x", pady=(16, 6))

    # ========================== ВКЛАДКА ЖУРНАЛ ==========================
    def _build_logs_tab(self):
        bar = ttk.Frame(self.tab_logs)
        bar.pack(fill="x", pady=(0, 8))

        btn_copy = ttk.Button(bar, text="Скопировать журнал", command=self._on_copy_logs)
        btn_copy.pack(side="left", padx=(0, 6))

        btn_clear = ttk.Button(bar, text="Очистить", command=self._on_clear_logs)
        btn_clear.pack(side="left")

        log_container = ttk.Frame(self.tab_logs)
        log_container.pack(fill="both", expand=True)

        scrollbar = ttk.Scrollbar(log_container)
        scrollbar.pack(side="right", fill="y")

        self.txt_log = tk.Text(
            log_container,
            wrap="word",
            bg="#1E1E1E",
            fg="#DCDCDC",
            insertbackground="#FFFFFF",
            font=("Monospace", 9),
            yscrollcommand=scrollbar.set,
            bd=1,
            relief="solid",
        )
        self.txt_log.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.txt_log.yview)

    # ========================== ВКЛАДКА О ПРОГРАММЕ ==========================
    def _build_about_tab(self):
        box = ttk.LabelFrame(self.tab_about, text=" Информация о приложении ", padding=14)
        box.pack(fill="both", expand=True)

        ttk.Label(box, text="TG WS Proxy для Linux", font=("DejaVu Sans", 12, "bold")).pack(anchor="w", pady=4)
        ttk.Label(box, text=f"Версия ядра: {__version__} (Актуальная)").pack(anchor="w", pady=2)
        ttk.Label(box, text="Сборка: Standalone AppImage (glibc 2.17+)").pack(anchor="w", pady=2)

        desc_txt = (
            "\nПрокси-клиент для обхода блокировок Telegram на территории РФ.\n"
            "Трафик маскируется под обычный защищенный WebSocket/TLS трафик "
            "к Cloudflare CDN, делая блокировку со стороны ТСПУ невозможной.\n\n"
            "Разработано на основе открытых компонентов tg-ws-proxy."
        )
        ttk.Label(box, text=desc_txt, wraplength=480, justify="left").pack(anchor="w", pady=6)

    # ========================== ЛОГИКА И СОБЫТИЯ ==========================
    def _on_toggle_proxy(self):
        if self.is_proxy_running():
            self.on_stop_proxy()
        else:
            self.on_start_proxy()
        self._update_status_ui()

    def _update_status_ui(self):
        running = self.is_proxy_running()
        if running:
            self.lbl_status_val.config(text="Подключено", foreground="#2E7D32")
            self.btn_toggle_proxy.config(text="Остановить прокси")
        else:
            self.lbl_status_val.config(text="Остановлено", foreground="#C62828")
            self.btn_toggle_proxy.config(text="Запустить прокси")

    def _on_apply_telegram(self):
        url = self.get_proxy_url()
        try:
            pyperclip.copy(url)
        except Exception:
            pass
        try:
            subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            messagebox.showinfo("Telegram Proxy", f"Ссылка скопирована в буфер:\n{url}")

    def _on_copy_link(self):
        url = self.get_proxy_url()
        try:
            pyperclip.copy(url)
            self.btn_copy_url.config(text="✓ Ссылка скопирована!")
            self.root.after(2000, lambda: self.btn_copy_url.config(text="📋  Скопировать ссылку подключения"))
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось скопировать: {e}")

    def _generate_secret(self):
        new_sec = os.urandom(16).hex()
        self.entry_secret.delete(0, "end")
        self.entry_secret.insert(0, new_sec)

    def _on_settings_check_changed(self):
        self.config["minimize_to_tray_on_close"] = self.var_minimize.get()
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
        self.config["minimize_to_tray_on_close"] = self.var_minimize.get()

        if self.on_save_config:
            self.on_save_config(self.config)

        self.lbl_param_host.config(text=f"{self.config['host']}:{self.config['port']}")
        self.lbl_param_secret.config(text=f"{str(self.config['secret'])[:16]}...")

        self.on_restart_proxy()
        self._update_status_ui()
        messagebox.showinfo("Настройки", "Настройки успешно сохранены, служба перезапущена.")

    def _on_copy_logs(self):
        try:
            txt = self.txt_log.get("1.0", "end")
            pyperclip.copy(txt)
            messagebox.showinfo("Журнал", "Журнал скопирован в буфер обмена!")
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))

    def _on_clear_logs(self):
        self.txt_log.delete("1.0", "end")
        self._log_pos = 0

    def _periodic_update(self):
        if not self._running:
            return
        self._update_status_ui()
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

                    if new_text and hasattr(self, "txt_log"):
                        self.txt_log.insert("end", new_text)
                        self.txt_log.see("end")
        except Exception:
            pass

        if self._running:
            self.root.after(1500, self._poll_logs)

    def run(self):
        self.root.mainloop()
