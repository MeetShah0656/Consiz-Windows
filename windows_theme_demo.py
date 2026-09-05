import ctypes
import platform
import sys
import tkinter as tk
from tkinter import ttk

# ==============================================================================
# Windows Win32 / DWM Structures for Transparent Glass & Acrylic Blur
# ==============================================================================
class ACCENT_POLICY(ctypes.Structure):
    _fields_ = [
        ('AccentState', ctypes.c_int),
        ('AccentFlags', ctypes.c_int),
        ('GradientColor', ctypes.c_int),
        ('AnimationId', ctypes.c_int)
    ]

class WINCOMPATTRDATA(ctypes.Structure):
    _fields_ = [
        ('Attribute', ctypes.c_int),
        ('Data', ctypes.POINTER(ACCENT_POLICY)),
        ('SizeOfData', ctypes.c_size_t)
    ]

class MARGINS(ctypes.Structure):
    _fields_ = [
        ('cxLeftWidth', ctypes.c_int),
        ('cxRightWidth', ctypes.c_int),
        ('cyTopHeight', ctypes.c_int),
        ('cyBottomHeight', ctypes.c_int)
    ]


def get_windows_theme_settings():
    """
    Detects the active Windows personalization settings:
    - OS version & build number
    - Light / Dark mode (from Windows Personalize registry)
    - Customized user Accent Color (from Windows DWM registry)
    """
    settings = {
        "os_name": "Not Windows",
        "build": 0,
        "is_dark": False,
        "accent_color": "#0078d4"
    }

    if platform.system() != "Windows":
        return settings

    # 1. OS & Build detection
    try:
        win_version = sys.getwindowsversion()
        settings["build"] = win_version.build
        if win_version.build >= 22000:
            settings["os_name"] = "Windows 11"
        elif win_version.major == 10:
            settings["os_name"] = "Windows 10"
        else:
            settings["os_name"] = "Legacy Windows"
    except Exception:
        settings["os_name"] = "Windows"

    # 2. Light / Dark mode detection from Registry
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        )
        apps_use_light, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        settings["is_dark"] = (apps_use_light == 0)
        winreg.CloseKey(key)
    except Exception:
        settings["is_dark"] = False

    # 3. Accent Color detection from DWM Registry
    try:
        import winreg
        dwm_key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\DWM"
        )
        accent_dword, _ = winreg.QueryValueEx(dwm_key, "AccentColor")
        winreg.CloseKey(dwm_key)

        # Stored in ABGR (0xAABBGGRR) format -> extract R, G, B
        r = accent_dword & 0xFF
        g = (accent_dword >> 8) & 0xFF
        b = (accent_dword >> 16) & 0xFF
        settings["accent_color"] = f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        settings["accent_color"] = "#0078d4" if settings["os_name"] != "Legacy Windows" else "#000080"

    return settings


def set_native_titlebar_theme(root, is_dark):
    """Sets the Windows 10/11 native title bar to dark or light mode using DWM."""
    if platform.system() != "Windows":
        return
    try:
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        val = ctypes.c_int(1 if is_dark else 0)
        res = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 20, ctypes.byref(val), ctypes.sizeof(val)
        )
        if res != 0:
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 19, ctypes.byref(val), ctypes.sizeof(val)
            )
    except Exception:
        pass


def apply_glass_effect(root, enable_glass=True, glass_type="Acrylic", opacity=0.92, is_dark=True):
    """
    Applies Windows 11/10 native transparent glass effect (Acrylic / Mica / BlurBehind)
    combined with Tkinter window translucency.
    """
    if platform.system() != "Windows":
        root.wm_attributes("-alpha", opacity if enable_glass else 1.0)
        return

    try:
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())

        if not enable_glass:
            # Disable DWM backdrop
            none_val = ctypes.c_int(1)  # DWMSBT_NONE
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 38, ctypes.byref(none_val), 4)

            # Disable accent policy
            policy = ACCENT_POLICY(0, 0, 0, 0)
            data = WINCOMPATTRDATA(19, ctypes.pointer(policy), ctypes.sizeof(policy))
            ctypes.windll.user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data))

            root.wm_attributes("-alpha", 1.0)
            return

        # 1. Windows 11 DWM Backdrop (Build 22621+ and build 26200+)
        # DWMSBT_MAINWINDOW = 2 (Mica), DWMSBT_TRANSIENTWINDOW = 3 (Acrylic)
        backdrop_val = 3 if glass_type == "Acrylic" else 2
        dw_val = ctypes.c_int(backdrop_val)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 38, ctypes.byref(dw_val), 4)

        # Windows 11 Build 22000 fallback (DWMWA_MICA_EFFECT = 1029)
        mica_val = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 1029, ctypes.byref(mica_val), 4)

        # 2. Extend Frame into Client Area
        margins = MARGINS(-1, -1, -1, -1)
        ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))

        # 3. Accent Policy: 4 = ACCENT_ENABLE_ACRYLICBLURBEHIND, 3 = ACCENT_ENABLE_BLURBEHIND
        accent_state = 4 if glass_type == "Acrylic" else 3
        # Tint color with alpha: 0x80202020 for dark, 0x80F0F0F0 for light
        gradient = 0x66202020 if is_dark else 0x66F5F5F5
        policy = ACCENT_POLICY(accent_state, 2, gradient, 0)
        data = WINCOMPATTRDATA(19, ctypes.pointer(policy), ctypes.sizeof(policy))
        ctypes.windll.user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data))

        # 4. Set smooth window opacity for translucent glass look
        root.wm_attributes("-alpha", opacity)
    except Exception:
        root.wm_attributes("-alpha", opacity if enable_glass else 1.0)


def get_contrast_text_color(hex_color):
    """Determines whether white or black text gives best contrast on a given hex color."""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 6:
        r, g, b = (int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        luminance = (0.299 * r + 0.587 * g + 0.114 * b)
        return "#000000" if luminance > 140 else "#ffffff"
    return "#ffffff"


def build_theme_palette(accent_color):
    """Generates theme definitions incorporating the user's active accent color."""
    btn_text_color = get_contrast_text_color(accent_color)

    return {
        "Windows 11 (Dark)": {
            "bg": "#1c1c1c",
            "card_bg": "#282828",
            "border": "#3d3d3d",
            "text": "#ffffff",
            "subtext": "#b0b0b0",
            "accent": accent_color,
            "btn_text": btn_text_color,
            "font": ("Segoe UI Variable", 10),
            "title_font": ("Segoe UI Variable", 15, "bold"),
            "radius": "10",
            "is_dark": True,
            "desc": "Windows 11 Mica / Acrylic Dark mode with translucent glass & modern geometry."
        },
        "Windows 11 (Light)": {
            "bg": "#f0f2f5",
            "card_bg": "#ffffff",
            "border": "#d8dce2",
            "text": "#1a1a1a",
            "subtext": "#555555",
            "accent": accent_color,
            "btn_text": btn_text_color,
            "font": ("Segoe UI Variable", 10),
            "title_font": ("Segoe UI Variable", 15, "bold"),
            "radius": "10",
            "is_dark": False,
            "desc": "Windows 11 Mica / Acrylic Light mode with soft frosted glass aesthetics."
        },
        "Windows 10 (Dark)": {
            "bg": "#121212",
            "card_bg": "#1e1e1e",
            "border": accent_color,
            "text": "#ffffff",
            "subtext": "#999999",
            "accent": accent_color,
            "btn_text": btn_text_color,
            "font": ("Segoe UI", 10),
            "title_font": ("Segoe UI", 15, "bold"),
            "radius": "0",
            "is_dark": True,
            "desc": "Windows 10 Metro Dark theme with sharp borders and glass blur effect."
        },
        "Windows 10 (Light)": {
            "bg": "#ebebeb",
            "card_bg": "#ffffff",
            "border": accent_color,
            "text": "#000000",
            "subtext": "#555555",
            "accent": accent_color,
            "btn_text": btn_text_color,
            "font": ("Segoe UI", 10),
            "title_font": ("Segoe UI", 15, "bold"),
            "radius": "0",
            "is_dark": False,
            "desc": "Windows 10 Metro Light theme with high contrast and sharp geometry."
        },
        "Legacy Windows": {
            "bg": "#d4d0c8",
            "card_bg": "#d4d0c8",
            "border": "#808080",
            "text": "#000000",
            "subtext": "#404040",
            "accent": "#000080",
            "btn_text": "#ffffff",
            "font": ("MS Sans Serif", 9),
            "title_font": ("MS Sans Serif", 12, "bold"),
            "radius": "0",
            "is_dark": False,
            "desc": "Windows 95/XP Classic theme with beveled 3D borders."
        },
        "Cross-Platform Dark": {
            "bg": "#1a1b22",
            "card_bg": "#242631",
            "border": "#353849",
            "text": "#f5f5f5",
            "subtext": "#a0a4b8",
            "accent": accent_color if accent_color else "#00adb5",
            "btn_text": btn_text_color,
            "font": ("Helvetica", 10),
            "title_font": ("Helvetica", 15, "bold"),
            "radius": "4",
            "is_dark": True,
            "desc": "Cross-platform dark theme fallback with translucent styling."
        }
    }


# ==============================================================================
# Initialization & State
# ==============================================================================
detected_settings = get_windows_theme_settings()

# Default initial theme from system
if detected_settings["os_name"] == "Windows 11":
    initial_theme = "Windows 11 (Dark)" if detected_settings["is_dark"] else "Windows 11 (Light)"
elif detected_settings["os_name"] == "Windows 10":
    initial_theme = "Windows 10 (Dark)" if detected_settings["is_dark"] else "Windows 10 (Light)"
elif detected_settings["os_name"] == "Legacy Windows":
    initial_theme = "Legacy Windows"
else:
    initial_theme = "Cross-Platform Dark" if detected_settings["is_dark"] else "Windows 11 (Light)"

theme_palettes = build_theme_palette(detected_settings["accent_color"])
theme_keys = list(theme_palettes.keys())
current_idx = theme_keys.index(initial_theme) if initial_theme in theme_keys else 0

# Glass state
glass_enabled = True
glass_type = "Acrylic"   # "Acrylic" or "Mica"
glass_opacity = 0.91     # 0.60 to 1.00

# ==============================================================================
# Tkinter Window & Widget Hierarchy
# ==============================================================================
root = tk.Tk()
root.geometry("560x440")
root.minsize(500, 390)

# Container Card (Glassmorphic card)
card = tk.Frame(root)
card.pack(padx=18, pady=18, fill="both", expand=True)

# Title Label
title_lbl = tk.Label(card)
title_lbl.pack(pady=(12, 4))

# Description Label
desc_lbl = tk.Label(card, wraplength=480, justify="center")
desc_lbl.pack(pady=2)

# System Info Frame (Detected Windows details)
info_frame = tk.Frame(card)
info_frame.pack(pady=8, padx=20, fill="x")

lbl_os = tk.Label(info_frame)
lbl_os.pack(anchor="w", pady=1)

lbl_mode = tk.Label(info_frame)
lbl_mode.pack(anchor="w", pady=1)

accent_box = tk.Frame(info_frame)
accent_box.pack(anchor="w", pady=1)

lbl_accent = tk.Label(accent_box)
lbl_accent.pack(side="left")

swatch = tk.Label(accent_box, text="   ", width=3, relief="solid", borderwidth=1)
swatch.pack(side="left", padx=6)

lbl_glass_status = tk.Label(info_frame)
lbl_glass_status.pack(anchor="w", pady=1)

# Glass Controls Frame
glass_frame = tk.LabelFrame(card, text=" Transparent Glass Controls ", padx=10, pady=8)
glass_frame.pack(padx=20, pady=8, fill="x")

glass_toggle_btn = tk.Button(glass_frame)
glass_toggle_btn.pack(side="left", padx=5)

glass_mode_btn = tk.Button(glass_frame)
glass_mode_btn.pack(side="left", padx=5)

# Opacity Slider
lbl_slider = tk.Label(glass_frame, text="Opacity:")
lbl_slider.pack(side="left", padx=(10, 4))

opacity_slider = tk.Scale(
    glass_frame,
    from_=60,
    to=100,
    orient="horizontal",
    showvalue=True,
    length=120,
    command=lambda val: on_opacity_change(float(val) / 100.0)
)
opacity_slider.set(int(glass_opacity * 100))
opacity_slider.pack(side="left", padx=4)

# Action Buttons Frame
btn_frame = tk.Frame(card)
btn_frame.pack(pady=(12, 8))

action_btn = tk.Button(btn_frame, text="Accent Action")
action_btn.pack(side="left", padx=6, ipadx=8, ipady=4)

switch_btn = tk.Button(btn_frame)
switch_btn.pack(side="left", padx=6, ipadx=8, ipady=4)

refresh_btn = tk.Button(btn_frame, text="⟳ Re-Detect System")
refresh_btn.pack(side="left", padx=6, ipadx=8, ipady=4)


# ==============================================================================
# Theme & Glass Application Logic
# ==============================================================================
def apply_theme(theme_name):
    """Applies a theme palette and updates the glass effect & title bar."""
    cfg = theme_palettes[theme_name]

    # Native Title Bar (Dark / Light)
    set_native_titlebar_theme(root, cfg["is_dark"])

    # Native Glass / Acrylic blur effect
    apply_glass_effect(
        root,
        enable_glass=glass_enabled,
        glass_type=glass_type,
        opacity=glass_opacity,
        is_dark=cfg["is_dark"]
    )

    # Window & Card
    root.title(f"Dynamic UI — {theme_name} [Glass: {'ON' if glass_enabled else 'OFF'}]")
    root.configure(bg=cfg["bg"])

    border_w = 2 if cfg["radius"] == "0" else 1
    card.configure(
        bg=cfg["card_bg"],
        highlightbackground=cfg["border"],
        highlightthickness=border_w
    )

    # Title & Description
    title_lbl.configure(
        text=f"{theme_name} Theme",
        fg=cfg["accent"],
        bg=cfg["card_bg"],
        font=cfg["title_font"]
    )
    desc_lbl.configure(
        text=cfg["desc"],
        fg=cfg["subtext"],
        bg=cfg["card_bg"],
        font=cfg["font"]
    )

    # System Info section
    info_frame.configure(bg=cfg["card_bg"])
    accent_box.configure(bg=cfg["card_bg"])

    os_display = f"Operating System: {detected_settings['os_name']}"
    if detected_settings['build'] > 0:
        os_display += f" (Build {detected_settings['build']})"

    mode_display = "Windows System Theme: " + ("Dark Mode 🌙" if detected_settings['is_dark'] else "Light Mode ☀️")

    lbl_os.configure(text=os_display, fg=cfg["text"], bg=cfg["card_bg"], font=cfg["font"])
    lbl_mode.configure(text=mode_display, fg=cfg["text"], bg=cfg["card_bg"], font=cfg["font"])
    lbl_accent.configure(
        text=f"System Accent Color: {detected_settings['accent_color']}",
        fg=cfg["text"],
        bg=cfg["card_bg"],
        font=cfg["font"]
    )
    swatch.configure(bg=detected_settings["accent_color"])

    glass_info_text = f"Transparent Glass: {'Enabled (Acrylic Frosted 🌟)' if glass_enabled else 'Disabled (Opaque)'}"
    lbl_glass_status.configure(text=glass_info_text, fg=cfg["accent"] if glass_enabled else cfg["subtext"], bg=cfg["card_bg"], font=cfg["font"])

    # Glass Controls Frame
    glass_frame.configure(
        bg=cfg["card_bg"],
        fg=cfg["text"],
        font=cfg["font"]
    )
    lbl_slider.configure(bg=cfg["card_bg"], fg=cfg["text"], font=cfg["font"])
    opacity_slider.configure(
        bg=cfg["card_bg"],
        fg=cfg["text"],
        highlightbackground=cfg["card_bg"],
        troughcolor=cfg["bg"]
    )

    glass_toggle_btn.configure(
        text=f"Glass: {'ON ✨' if glass_enabled else 'OFF ⚪'}",
        bg=cfg["accent"] if glass_enabled else (cfg["card_bg"] if theme_name != "Legacy Windows" else "#e0e0e0"),
        fg=cfg["btn_text"] if glass_enabled else cfg["text"],
        font=cfg["font"],
        relief="flat" if cfg["radius"] != "0" else "raised",
        borderwidth=1,
        command=toggle_glass
    )

    glass_mode_btn.configure(
        text=f"Material: {glass_type}",
        bg=cfg["card_bg"] if theme_name != "Legacy Windows" else "#e0e0e0",
        fg=cfg["text"],
        font=cfg["font"],
        relief="solid" if cfg["radius"] != "0" else "raised",
        borderwidth=1,
        command=toggle_glass_mode
    )

    # Action buttons
    btn_frame.configure(bg=cfg["card_bg"])

    action_btn.configure(
        bg=cfg["accent"],
        fg=cfg["btn_text"],
        font=cfg["font"],
        relief="flat" if cfg["radius"] != "0" else "raised",
        borderwidth=0 if cfg["radius"] != "0" else 2,
        activebackground=cfg["accent"],
        activeforeground=cfg["btn_text"]
    )

    switch_btn.configure(
        text="Cycle Theme ➔",
        bg=cfg["card_bg"] if theme_name != "Legacy Windows" else "#e0e0e0",
        fg=cfg["text"] if theme_name != "Legacy Windows" else "#000000",
        font=cfg["font"],
        relief="solid" if cfg["radius"] != "0" else "raised",
        borderwidth=1 if cfg["radius"] != "0" else 2,
        command=cycle_theme
    )

    refresh_btn.configure(
        text="⟳ Re-Detect System",
        bg=cfg["card_bg"] if theme_name != "Legacy Windows" else "#e0e0e0",
        fg=cfg["subtext"] if theme_name != "Legacy Windows" else "#000000",
        font=cfg["font"],
        relief="solid" if cfg["radius"] != "0" else "raised",
        borderwidth=1 if cfg["radius"] != "0" else 2,
        command=reload_system_settings
    )


def toggle_glass():
    """Toggles the transparent glass effect on or off."""
    global glass_enabled
    glass_enabled = not glass_enabled
    apply_theme(theme_keys[current_idx])


def toggle_glass_mode():
    """Switches between Acrylic (frosted glass) and Mica materials."""
    global glass_type
    glass_type = "Mica" if glass_type == "Acrylic" else "Acrylic"
    apply_theme(theme_keys[current_idx])


def on_opacity_change(new_opacity):
    """Dynamically updates window translucency from the slider."""
    global glass_opacity
    glass_opacity = new_opacity
    if glass_enabled:
        root.wm_attributes("-alpha", glass_opacity)


def cycle_theme():
    """Cycles through the available theme presets."""
    global current_idx
    current_idx = (current_idx + 1) % len(theme_keys)
    apply_theme(theme_keys[current_idx])


def reload_system_settings():
    """Re-reads Windows registry in case personalization changed."""
    global detected_settings, theme_palettes, current_idx
    detected_settings = get_windows_theme_settings()
    theme_palettes = build_theme_palette(detected_settings["accent_color"])

    if detected_settings["os_name"] == "Windows 11":
        new_theme = "Windows 11 (Dark)" if detected_settings["is_dark"] else "Windows 11 (Light)"
    elif detected_settings["os_name"] == "Windows 10":
        new_theme = "Windows 10 (Dark)" if detected_settings["is_dark"] else "Windows 10 (Light)"
    else:
        new_theme = "Legacy Windows" if detected_settings["os_name"] == "Legacy Windows" else "Cross-Platform Dark"

    current_idx = theme_keys.index(new_theme)
    apply_theme(new_theme)


# Apply the detected theme and glass effect on launch
apply_theme(theme_keys[current_idx])

root.mainloop()
