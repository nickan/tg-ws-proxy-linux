# -*- coding: utf-8 -*-
from PIL import Image, ImageDraw
import customtkinter as ctk


def create_smooth_icon(draw_fn, size=(24, 24), color="#FFFFFF"):
    """Создает кристально четкую сглаженную иконку через суперсэмплинг 4x (96x96 -> 24x24)."""
    scale = 4
    high_w, high_h = size[0] * scale, size[1] * scale
    img = Image.new("RGBA", (high_w, high_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw_fn(draw, high_w, high_h, color)
    small_img = img.resize(size, Image.Resampling.LANCZOS)
    return ctk.CTkImage(light_image=small_img, dark_image=small_img, size=size)


def _draw_dashboard(draw, w, h, col):
    # 4 скругленных квадратика (Dashboard tile)
    pad = 12
    gap = 8
    half_w = (w - pad * 2 - gap) // 2
    half_h = (h - pad * 2 - gap) // 2
    r = 8
    # верхний левый
    draw.rounded_rectangle([pad, pad, pad + half_w, pad + half_h], radius=r, fill=col)
    # верхний правый
    draw.rounded_rectangle([pad + half_w + gap, pad, pad + half_w * 2 + gap, pad + half_h], radius=r, fill=col)
    # нижний левый
    draw.rounded_rectangle([pad, pad + half_h + gap, pad + half_w, pad + half_h * 2 + gap], radius=r, fill=col)
    # нижний правый
    draw.rounded_rectangle([pad + half_w + gap, pad + half_h + gap, pad + half_w * 2 + gap, pad + half_h * 2 + gap], radius=r, fill=col)


def _draw_proxies(draw, w, h, col):
    # Земной шар / сеть
    pad = 12
    draw.ellipse([pad, pad, w - pad, h - pad], outline=col, width=6)
    # вертикальный овал
    draw.ellipse([w // 2 - 16, pad, w // 2 + 16, h - pad], outline=col, width=5)
    # горизонтальная линия
    draw.line([pad, h // 2, w - pad, h // 2], fill=col, width=5)


def _draw_logs(draw, w, h, col):
    # Документ со строками
    pad_x, pad_y = 18, 14
    draw.rounded_rectangle([pad_x, pad_y, w - pad_x, h - pad_y], radius=6, outline=col, width=5)
    # Строчки
    draw.line([pad_x + 12, pad_y + 16, w - pad_x - 12, pad_y + 16], fill=col, width=4)
    draw.line([pad_x + 12, pad_y + 32, w - pad_x - 12, pad_y + 32], fill=col, width=4)
    draw.line([pad_x + 12, pad_y + 48, w - pad_x - 22, pad_y + 48], fill=col, width=4)


def _draw_settings(draw, w, h, col):
    # Шестеренка
    cx, cy = w // 2, h // 2
    r_outer = 32
    r_inner = 14
    draw.ellipse([cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer], outline=col, width=10)
    draw.ellipse([cx - r_inner, cy - r_inner, cx + r_inner, cy + r_inner], fill=col)
    # 4 луча
    draw.line([cx - 40, cy, cx + 40, cy], fill=col, width=8)
    draw.line([cx, cy - 40, cx, cy + 40], fill=col, width=8)
    draw.line([cx - 28, cy - 28, cx + 28, cy + 28], fill=col, width=8)
    draw.line([cx - 28, cy + 28, cx + 28, cy - 28], fill=col, width=8)


def _draw_lightning(draw, w, h, col):
    # Молния (логотип)
    pts = [
        (w * 0.55, h * 0.12),
        (w * 0.25, h * 0.52),
        (w * 0.48, h * 0.52),
        (w * 0.42, h * 0.88),
        (w * 0.75, h * 0.44),
        (w * 0.52, h * 0.44),
    ]
    draw.polygon(pts, fill=col)


def _draw_check(draw, w, h, col):
    # Круг с галочкой
    pad = 6
    draw.ellipse([pad, pad, w - pad, h - pad], fill="#4CAF50")
    # Галочка
    pts = [(w * 0.28, h * 0.52), (w * 0.44, h * 0.68), (w * 0.72, h * 0.34)]
    draw.line(pts, fill="#FFFFFF", width=8, joint="curve")


def _draw_pause(draw, w, h, col):
    # Круг с паузой
    pad = 6
    draw.ellipse([pad, pad, w - pad, h - pad], fill="#757575")
    draw.line([w * 0.38, h * 0.32, w * 0.38, h * 0.68], fill="#FFFFFF", width=6)
    draw.line([w * 0.62, h * 0.32, w * 0.62, h * 0.68], fill="#FFFFFF", width=6)


def _draw_exit(draw, w, h, col):
    # Выход (дверь со стрелкой)
    draw.rounded_rectangle([16, 12, 54, 84], radius=6, outline=col, width=6)
    # Стрелка направо
    draw.line([42, 48, 80, 48], fill=col, width=6)
    draw.line([66, 34, 80, 48], fill=col, width=6)
    draw.line([66, 62, 80, 48], fill=col, width=6)


def _draw_theme(draw, w, h, col):
    # Солнце / месяц (круг разделенный пополам)
    cx, cy = w // 2, h // 2
    r = 30
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=col, width=6)
    draw.pieslice([cx - r, cy - r, cx + r, cy + r], 90, 270, fill=col)


def get_ui_icons(is_dark=True):
    fg = "#EDEBF2" if is_dark else "#1D192B"
    muted = "#9D98A7" if is_dark else "#79747E"
    accent = "#F1A490" if is_dark else "#6750A4"

    return {
        "logo": create_smooth_icon(_draw_lightning, size=(28, 28), color=accent),
        "dashboard_active": create_smooth_icon(_draw_dashboard, size=(22, 22), color=fg),
        "dashboard_inactive": create_smooth_icon(_draw_dashboard, size=(22, 22), color=muted),
        "proxies_active": create_smooth_icon(_draw_proxies, size=(22, 22), color=fg),
        "proxies_inactive": create_smooth_icon(_draw_proxies, size=(22, 22), color=muted),
        "logs_active": create_smooth_icon(_draw_logs, size=(22, 22), color=fg),
        "logs_inactive": create_smooth_icon(_draw_logs, size=(22, 22), color=muted),
        "settings_active": create_smooth_icon(_draw_settings, size=(22, 22), color=fg),
        "settings_inactive": create_smooth_icon(_draw_settings, size=(22, 22), color=muted),
        "theme": create_smooth_icon(_draw_theme, size=(20, 20), color=fg),
        "exit": create_smooth_icon(_draw_exit, size=(20, 20), color="#FF6B6B" if is_dark else "#D32F2F"),
        "status_ok": create_smooth_icon(_draw_check, size=(26, 26)),
        "status_off": create_smooth_icon(_draw_pause, size=(26, 26)),
    }
