"""
app.py  –  SaaS Europe Sales Intelligence Dashboard
Railway-ready Flask backend.

Data source: Google Sheets (public CSV export).
Fetches and cleans data in memory every 10 seconds.

Endpoints
---------
GET /                              dashboard.html
GET /api/kpis                      KPI totals + last_updated
GET /api/top-companies             top N companies by employee count
GET /api/verticals                 contact distribution by vertical
GET /api/contacts?page=&search=    paginated, searchable contact table
GET /health                        Railway health check
"""

import os
import time
import threading
import logging

import pandas as pd
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

# ── Config ────────────────────────────────────────────────────────────────────
SHEET_ID   = "1mxLi3pPzD4Oxp63gkOV6jqfizWJ4O7Wedykr8UBjPO8"
SHEET_URL  = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv"
PORT       = int(os.environ.get("PORT", 5000))
PER_PAGE   = 50
REFRESH_S  = 10      # seconds between background data refreshes

COL_DROP   = "Rows from: Development:IT Firms US"
CONTACT_COLS = [
    "First Name", "Last Name", "Job Title", "Linkedin Profile",
    "Company Name", "Company Linkedin Url", "Company Domain",
    "Domain Suffix", "Vertical", "Offer", "Icp",
    "Short Description", "# Employees", "Domain Match",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Flask ─────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=BASE_DIR)
CORS(app)

# ── Thread-safe in-memory data store ─────────────────────────────────────────
_lock  = threading.Lock()
_store = {"df": None, "last_updated": "Loading…", "error": None}


# ── Data fetch + clean ────────────────────────────────────────────────────────
def fetch_and_clean():
    """Download Google Sheet, clean in memory, update _store."""
    try:
        log.info("Fetching data from Google Sheets…")
        df = pd.read_csv(SHEET_URL)
        original = len(df)

        # 1. Drop the empty column
        if COL_DROP in df.columns:
            df = df.drop(columns=[COL_DROP])

        # 2. Drop rows with ANY null
        df = df.dropna()

        # 3. Remove duplicates
        df = df.drop_duplicates()

        # 4. Coerce employee count to int
        if "# Employees" in df.columns:
            df["# Employees"] = (
                pd.to_numeric(df["# Employees"], errors="coerce")
                .fillna(0).astype(int)
            )

        ts = pd.Timestamp.now().strftime("%B %d, %Y  %H:%M:%S")

        with _lock:
            _store["df"]           = df
            _store["last_updated"] = ts
            _store["error"]        = None

        log.info("Data ready: %s rows  (%s)", f"{len(df):,}", ts)

    except Exception as exc:
        log.error("Fetch/clean failed: %s", exc)
        with _lock:
            _store["error"] = str(exc)


def _background_loop():
    """Refresh data every REFRESH_S seconds forever."""
    while True:
        time.sleep(REFRESH_S)
        fetch_and_clean()


# ── Bootstrap: initial fetch + start background thread ───────────────────────
fetch_and_clean()
_thread = threading.Thread(target=_background_loop, daemon=True)
_thread.start()


# ── Helper ────────────────────────────────────────────────────────────────────
def _get_df():
    with _lock:
        return _store["df"], _store["last_updated"]


# ── Routes ────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "dashboard.html")


@app.route("/health")
def health():
    with _lock:
        ok = _store["df"] is not None
    return jsonify({"status": "ok" if ok else "loading"}), 200


@app.route("/api/kpis")
def api_kpis():
    df, ts = _get_df()
    if df is None:
        return jsonify({"error": "Data not loaded yet"}), 503

    comp_emp = df.groupby("Company Name")["# Employees"].max()
    return jsonify({
        "total_companies": int(df["Company Name"].nunique()),
        "total_employees": int(comp_emp.sum()),
        "total_contacts":  len(df),
        "last_updated":    ts,
    })


@app.route("/api/top-companies")
def api_top_companies():
    df, _ = _get_df()
    if df is None:
        return jsonify({"error": "Data not loaded yet"}), 503

    comp_emp = df.groupby("Company Name")["# Employees"].max()
    top = (comp_emp.nlargest(20)
           .reset_index()
           .sort_values("# Employees", ascending=True))
    return jsonify({
        "companies": top["Company Name"].tolist(),
        "employees": top["# Employees"].tolist(),
    })


@app.route("/api/verticals")
def api_verticals():
    df, _ = _get_df()
    if df is None:
        return jsonify({"error": "Data not loaded yet"}), 503

    vc    = df["Vertical"].value_counts()
    top_n = 15
    if len(vc) > top_n:
        labels = vc.head(top_n).index.tolist() + ["Other"]
        values = vc.head(top_n).tolist()        + [int(vc.iloc[top_n:].sum())]
    else:
        labels, values = vc.index.tolist(), vc.tolist()

    return jsonify({"labels": labels, "values": values})


@app.route("/api/contacts")
def api_contacts():
    df, _ = _get_df()
    if df is None:
        return jsonify({"error": "Data not loaded yet"}), 503

    page   = max(1, int(request.args.get("page",   1)))
    search = request.args.get("search", "").strip().lower()

    out = df[CONTACT_COLS].copy()
    out["Domain Match"] = out["Domain Match"].astype(str)
    out = out.fillna("")

    if search:
        combined = out.astype(str).apply(" ".join, axis=1).str.lower()
        out = out[combined.str.contains(search, regex=False)]

    total  = len(out)
    pages  = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page   = min(page, pages)
    start  = (page - 1) * PER_PAGE
    rows   = out.iloc[start : start + PER_PAGE].values.tolist()

    return jsonify({
        "rows":     rows,
        "total":    total,
        "page":     page,
        "pages":    pages,
        "per_page": PER_PAGE,
    })


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
