"""Corporate Clean design tokens → Qt StyleSheet.

Maps Tailwind tokens from styles/corporate-clean.md:
  bg-white / bg-slate-50 / text-gray-900 / blue-600 / border-gray-200 /
  rounded-lg / rounded-xl / shadow-sm
"""

from __future__ import annotations

# ── Color tokens (Tailwind → hex) ──────────────────────────────────────────
WHITE = "#ffffff"
SLATE_50 = "#f8fafc"
SLATE_100 = "#f1f5f9"
GRAY_50 = "#f9fafb"
GRAY_100 = "#f3f4f6"
GRAY_200 = "#e5e7eb"
GRAY_300 = "#d1d5db"
GRAY_400 = "#9ca3af"
GRAY_500 = "#6b7280"
GRAY_600 = "#4b5563"
GRAY_700 = "#374151"
GRAY_900 = "#111827"

BLUE_50 = "#eff6ff"
BLUE_500 = "#3b82f6"
BLUE_600 = "#2563eb"  # primary button
BLUE_700 = "#1d4ed8"  # primary hover

# Video stage keeps a calm dark plane (not neon) so subtitles stay readable
STAGE_BG = "#0f172a"  # slate-900
STAGE_HINT = "#94a3b8"  # slate-400

# ── Geometry ───────────────────────────────────────────────────────────────
RADIUS_LG = "8px"  # rounded-lg
RADIUS_XL = "12px"  # rounded-xl
BORDER = f"1px solid {GRAY_200}"
BORDER_INPUT = f"1px solid {GRAY_300}"

# Prefer professional system stacks (no purple AI defaults)
FONT_UI = '"Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif'
FONT_MONO = '"SF Mono", "Menlo", "Monaco", monospace'


def application_qss() -> str:
    """Global Corporate Clean stylesheet for the whole app."""
    return f"""
    /* ── Base ─────────────────────────────────────────────────────────── */
    QWidget {{
        font-family: {FONT_UI};
        font-size: 13px;
        color: {GRAY_900};
        background: {SLATE_50};
    }}

    QMainWindow {{
        background: {SLATE_50};
    }}

    QStatusBar {{
        background: {WHITE};
        color: {GRAY_500};
        border-top: {BORDER};
        font-size: 12px;
        padding: 2px 8px;
    }}

    QStatusBar::item {{
        border: none;
    }}

    /* ── Buttons ──────────────────────────────────────────────────────── */
    QPushButton {{
        font-family: {FONT_UI};
        font-size: 13px;
        font-weight: 500;
        color: {GRAY_700};
        background: {WHITE};
        border: {BORDER_INPUT};
        border-radius: {RADIUS_LG};
        padding: 7px 14px;
        min-height: 20px;
    }}
    QPushButton:hover {{
        background: {GRAY_50};
        border-color: {GRAY_300};
    }}
    QPushButton:pressed {{
        background: {GRAY_100};
    }}
    QPushButton:disabled {{
        color: {GRAY_400};
        background: {GRAY_100};
        border-color: {GRAY_200};
    }}

    QPushButton#primaryBtn {{
        color: {WHITE};
        background: {BLUE_600};
        border: 1px solid {BLUE_600};
    }}
    QPushButton#primaryBtn:hover {{
        background: {BLUE_700};
        border-color: {BLUE_700};
    }}
    QPushButton#primaryBtn:pressed {{
        background: {BLUE_700};
    }}
    QPushButton#primaryBtn:disabled {{
        color: {WHITE};
        background: #93c5fd;
        border-color: #93c5fd;
    }}

    QPushButton#ghostBtn {{
        background: transparent;
        border: none;
        color: {GRAY_500};
        padding: 4px 10px;
    }}
    QPushButton#ghostBtn:hover {{
        color: {BLUE_600};
        background: {BLUE_50};
        border-radius: {RADIUS_LG};
    }}

    /* ── Inputs ───────────────────────────────────────────────────────── */
    QLineEdit {{
        background: {WHITE};
        color: {GRAY_900};
        border: {BORDER_INPUT};
        border-radius: {RADIUS_LG};
        padding: 8px 12px;
        selection-background-color: {BLUE_500};
        selection-color: {WHITE};
    }}
    QLineEdit:focus {{
        border: 1px solid {BLUE_500};
    }}
    QLineEdit:disabled {{
        background: {SLATE_50};
        color: {GRAY_400};
    }}

    QComboBox {{
        background: {WHITE};
        color: {GRAY_900};
        border: {BORDER_INPUT};
        border-radius: {RADIUS_LG};
        padding: 6px 10px;
        padding-right: 32px;
        min-height: 22px;
    }}
    QComboBox:focus {{
        border: 1px solid {BLUE_500};
    }}
    QComboBox:editable {{
        padding-right: 32px;
    }}
    QComboBox:editable QLineEdit {{
        background: transparent;
        border: none;
        padding: 0;
        margin: 0;
    }}
    QComboBox::drop-down {{
        subcontrol-origin: padding;
        subcontrol-position: top right;
        width: 28px;
        border: none;
        border-left: 1px solid {GRAY_300};
        border-top-right-radius: {RADIUS_LG};
        border-bottom-right-radius: {RADIUS_LG};
        background: {GRAY_50};
    }}
    QComboBox::drop-down:hover {{
        background: {GRAY_100};
    }}
    QComboBox::down-arrow {{
        image: none;
        width: 0;
        height: 0;
        border-left: 5px solid transparent;
        border-right: 5px solid transparent;
        border-top: 6px solid {GRAY_500};
        margin-right: 9px;
    }}
    QComboBox::down-arrow:on {{
        border-top-color: {BLUE_600};
    }}
    QComboBox QAbstractItemView {{
        background: {WHITE};
        border: {BORDER};
        selection-background-color: {BLUE_50};
        selection-color: {GRAY_900};
        outline: none;
    }}

    QTextEdit {{
        background: {WHITE};
        color: {GRAY_900};
        border: {BORDER};
        border-radius: {RADIUS_LG};
        padding: 10px;
        selection-background-color: {BLUE_500};
        selection-color: {WHITE};
    }}
    QTextEdit:focus {{
        border: 1px solid {BLUE_500};
    }}

    /* ── Tabs ─────────────────────────────────────────────────────────── */
    QTabWidget::pane {{
        background: {WHITE};
        border: {BORDER};
        border-radius: {RADIUS_XL};
        top: -1px;
        padding: 4px;
    }}
    QTabBar::tab {{
        background: transparent;
        color: {GRAY_500};
        font-weight: 500;
        padding: 8px 16px;
        margin-right: 2px;
        border: none;
        border-bottom: 2px solid transparent;
    }}
    QTabBar::tab:selected {{
        color: {BLUE_600};
        border-bottom: 2px solid {BLUE_600};
        background: transparent;
    }}
    QTabBar::tab:hover:!selected {{
        color: {GRAY_700};
        background: {SLATE_50};
        border-radius: {RADIUS_LG} {RADIUS_LG} 0 0;
    }}

    /* ── Splitter ─────────────────────────────────────────────────────── */
    QSplitter::handle {{
        background: {GRAY_200};
        width: 1px;
    }}
    QSplitter::handle:hover {{
        background: {BLUE_500};
    }}

    /* ── Scrollbars (subtle) ──────────────────────────────────────────── */
    QScrollBar:vertical {{
        background: transparent;
        width: 8px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {GRAY_300};
        border-radius: 4px;
        min-height: 24px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {GRAY_400};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 8px;
    }}
    QScrollBar::handle:horizontal {{
        background: {GRAY_300};
        border-radius: 4px;
        min-width: 24px;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0;
    }}

    /* ── Dialog ───────────────────────────────────────────────────────── */
    QDialog {{
        background: {WHITE};
    }}
    QFormLayout QLabel, QDialog QLabel {{
        color: {GRAY_700};
    }}

    /* ── Object-named regions ─────────────────────────────────────────── */
    QWidget#topBar {{
        background: {WHITE};
        border-bottom: {BORDER};
    }}

    QLabel#brandTitle {{
        font-size: 16px;
        font-weight: 600;
        color: {GRAY_900};
        letter-spacing: -0.3px;
        background: transparent;
    }}

    QLabel#brandSub {{
        font-size: 11px;
        color: {GRAY_400};
        background: transparent;
    }}

    QWidget#stageCard {{
        background: {WHITE};
        border: {BORDER};
        border-radius: {RADIUS_XL};
    }}

    QWidget#videoStage {{
        background: {STAGE_BG};
        border-radius: {RADIUS_LG};
    }}

    QLabel#stageHint {{
        color: {STAGE_HINT};
        font-size: 14px;
        background: transparent;
    }}

    QLabel#stageHintSmall {{
        color: #64748b;
        font-size: 12px;
        background: transparent;
    }}

    QLabel#videoAlert {{
        color: {GRAY_900};
        font-size: 13px;
        font-weight: 600;
        background: #eff6ff;
        border: 1px solid #bfdbfe;
        border-radius: 8px;
        padding: 10px 12px;
    }}

    QLabel#videoTitle {{
        color: {GRAY_700};
        font-size: 12px;
        font-weight: 500;
        background: transparent;
    }}

    QLabel#modelMeta {{
        color: {GRAY_400};
        font-size: 11px;
        background: transparent;
        max-width: 420px;
    }}

    QWidget#aiPanel {{
        background: {WHITE};
        border: {BORDER};
        border-radius: {RADIUS_XL};
    }}

    QLabel#panelHeading {{
        font-size: 13px;
        font-weight: 600;
        color: {GRAY_900};
        background: transparent;
    }}

    QLabel#panelStatus {{
        color: {GRAY_400};
        font-size: 12px;
        background: transparent;
        padding: 2px 0;
    }}

    QWidget#logStrip {{
        background: {WHITE};
        border: {BORDER};
        border-radius: {RADIUS_XL};
    }}

    QLabel#logHeading {{
        font-size: 12px;
        font-weight: 600;
        color: {GRAY_700};
        background: transparent;
    }}

    QTextEdit#logPanel {{
        font-family: {FONT_MONO};
        font-size: 11px;
        background: {SLATE_50};
        color: {GRAY_600};
        border: none;
        border-radius: {RADIUS_LG};
        padding: 8px 10px;
    }}

    QWidget#subtitleStrip {{
        background: {WHITE};
        border-top: {BORDER};
    }}

    QLabel#subtitleZh {{
        color: {GRAY_900};
        font-size: 18px;
        font-weight: 600;
        background: {SLATE_50};
        border: {BORDER};
        border-radius: {RADIUS_LG};
        padding: 8px 14px;
    }}

    QLabel#subtitleEn {{
        color: {GRAY_500};
        font-size: 12px;
        background: transparent;
        padding: 2px 8px;
    }}

    QLabel#settingsHint {{
        color: {GRAY_400};
        font-size: 12px;
        background: transparent;
    }}
    """
