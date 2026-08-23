"""The look, shared by the Streamlit views and out/index.html.

Lifted from page.py so the three surfaces read as one product rather than three
tools that happen to share a database. Kept as one string in one place — the
last thing anyone wants is two palettes drifting apart.
"""

BG, PANEL, RAISED, LINE = "#0c0c0d", "#141416", "#1b1b1e", "#27272b"
FG, MUTED, DIM = "#e8e8ea", "#8b8b93", "#5f5f67"
ACCENT, GREEN, RED, BLUE = "#d97757", "#4ade80", "#f87171", "#7aa2f7"

CSS = f"""
<style>
  .stApp, [data-testid="stHeader"] {{ background:{BG}; }}
  [data-testid="stSidebar"] {{ background:{PANEL}; border-right:1px solid {LINE}; }}
  html, body, [class*="css"] {{
    color:{FG};
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,sans-serif;
  }}
  h1 {{ font-size:26px !important; font-weight:600 !important; letter-spacing:-.01em; }}
  h2, h3 {{ font-size:15px !important; font-weight:500 !important; }}

  /* Counts read as quiet reference, not a scoreboard. */
  [data-testid="stMetric"] {{
    background:{PANEL}; border:1px solid {LINE}; border-radius:10px; padding:12px 15px;
  }}
  [data-testid="stMetricLabel"] {{ color:{DIM} !important; font-size:11px !important;
    text-transform:uppercase; letter-spacing:.07em; }}
  [data-testid="stMetricValue"] {{ font-size:24px !important; font-weight:500 !important;
    font-variant-numeric:tabular-nums; }}

  .stTabs [data-baseweb="tab-list"] {{ gap:22px; border-bottom:1px solid {LINE}; }}
  .stTabs [data-baseweb="tab"] {{ color:{MUTED}; font-size:13.5px; padding:6px 0; }}
  .stTabs [aria-selected="true"] {{ color:{FG} !important; }}
  .stTabs [data-baseweb="tab-highlight"] {{ background:{ACCENT}; }}

  /* Filter chips: the default red read as an error state. */
  [data-baseweb="tag"] {{ background:{RAISED} !important; border:1px solid {LINE} !important;
    color:{FG} !important; border-radius:5px !important; font-size:12px !important; }}
  [data-baseweb="select"] > div {{ background:{RAISED} !important; border-color:{LINE} !important; }}

  .stAlert {{ background:{PANEL} !important; border:1px dashed {LINE} !important;
    color:{MUTED} !important; border-radius:10px; }}
  hr {{ border-color:{LINE} !important; }}
  [data-testid="stCaptionContainer"] {{ color:{MUTED} !important; font-size:12.5px !important; }}

  .card {{ background:{PANEL}; border:1px solid {LINE}; border-radius:10px;
    padding:14px 16px; margin-bottom:10px; }}
  .card .head {{ color:{DIM}; font-size:11.5px;
    font-family:ui-monospace,SFMono-Regular,Menlo,monospace; margin-bottom:8px; }}
  .card .head b {{ color:{FG}; font-weight:500; }}
  .assumed {{ color:{MUTED}; font-size:13px; margin-bottom:4px; }}
  .said {{ color:{FG}; font-size:13.5px; }}
  .said b {{ color:{ACCENT}; font-weight:500; }}
  .quote {{ border-left:2px solid {LINE}; padding:2px 0 2px 13px; color:{MUTED};
    font-size:12.5px; font-style:italic; margin-top:8px; }}
  .tag {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:10.5px;
    padding:2px 7px; border-radius:4px; background:{RAISED}; color:{MUTED};
    border:1px solid {LINE}; }}
  .tag.on {{ color:{ACCENT}; border-color:rgba(217,119,87,.28); }}
</style>
"""
