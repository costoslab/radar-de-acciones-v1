"""
Radar de Acciones - Fuentes de datos externas.
Todas las funciones devuelven None / listas vacías en caso de falla,
nunca datos inventados.
"""
import json
import time
import urllib.parse
import os
import re
import subprocess
import tempfile

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
SEC_UA = "RadarDeAcciones fabiconti7@gmail.com"

CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "cache")
COOKIE_JAR = os.path.join(CACHE_DIR, "_yahoo_cookies.txt")
os.makedirs(CACHE_DIR, exist_ok=True)


def _cache_path(key):
    safe = re.sub(r"[^a-zA-Z0-9_.-]", "_", key)
    return os.path.join(CACHE_DIR, safe + ".json")


def _get(url, headers=None, use_cookiejar=False, timeout=20, retries=3):
    """Fetch via curl subprocess (proved far more reliable than urllib in this
    sandbox for several hosts, e.g. FRED hangs under urllib but is instant via curl).
    The egress proxy in this sandbox is occasionally flaky on the first hit of a
    host, so we retry a few times before giving up."""
    hdrs = headers or {"User-Agent": UA}
    cmd = ["curl", "-s", "-m", str(timeout), "-L", "--http1.1"]
    for k, v in hdrs.items():
        cmd += ["-H", f"{k}: {v}"]
    if use_cookiejar:
        cmd += ["-c", COOKIE_JAR, "-b", COOKIE_JAR]
    cmd.append(url)
    last_err = None
    for attempt in range(retries):
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=timeout + 5,
                                     env=os.environ.copy(), stdin=subprocess.DEVNULL)
            if result.returncode == 0 and result.stdout:
                return result.stdout
            last_err = f"curl rc={result.returncode} stderr={result.stderr[:200]}"
        except subprocess.TimeoutExpired:
            last_err = "subprocess timeout"
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"curl failed for {url}: {last_err}")


def cached_json_fetch(cache_key, fetch_fn, max_age_sec=None, force=False):
    """Fetch JSON with disk caching to survive re-runs during dev / avoid re-hitting rate limits."""
    path = _cache_path(cache_key)
    if not force and os.path.exists(path):
        if max_age_sec is None or (time.time() - os.path.getmtime(path)) < max_age_sec:
            try:
                with open(path) as f:
                    return json.load(f)
            except Exception:
                pass
    try:
        data = fetch_fn()
    except Exception as e:
        return {"__error__": str(e)}
    with open(path, "w") as f:
        json.dump(data, f)
    return data


# ---------------------------------------------------------------------------
# Yahoo Finance (sin API key, usa endpoints publicos no documentados)
# ---------------------------------------------------------------------------
_yahoo_crumb = None


def _get_yahoo_crumb():
    global _yahoo_crumb
    if _yahoo_crumb:
        return _yahoo_crumb
    try:
        _get("https://fc.yahoo.com", use_cookiejar=True)
    except Exception:
        pass
    try:
        crumb = _get("https://query1.finance.yahoo.com/v1/test/getcrumb", use_cookiejar=True).decode()
    except Exception:
        crumb = None
    _yahoo_crumb = crumb
    return crumb


def yahoo_chart(ticker, range_="20y", interval="1mo"):
    """Historial de precios. No requiere crumb."""
    def fetch():
        url = f"https://query2.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}?range={range_}&interval={interval}"
        raw = _get(url)
        d = json.loads(raw)
        res = d.get("chart", {}).get("result")
        if not res:
            return {"__error__": "sin datos"}
        r = res[0]
        ts = r.get("timestamp", [])
        closes = r.get("indicators", {}).get("quote", [{}])[0].get("close", [])
        meta = r.get("meta", {})
        return {"timestamps": ts, "closes": closes, "meta": meta}
    return cached_json_fetch(f"chart_{ticker}_{range_}_{interval}", fetch, max_age_sec=6 * 3600)


def yahoo_quote_summary(ticker):
    """P/E, EPS, marketCap, sector, etc. Requiere crumb (cookie flow)."""
    def fetch():
        crumb = _get_yahoo_crumb()
        if not crumb:
            return {"__error__": "no crumb"}
        modules = "defaultKeyStatistics,summaryDetail,assetProfile,price,financialData"
        url = (f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{urllib.parse.quote(ticker)}"
               f"?modules={modules}&crumb={urllib.parse.quote(crumb)}")
        raw = _get(url, use_cookiejar=True)
        d = json.loads(raw)
        res = d.get("quoteSummary", {}).get("result")
        if not res:
            return {"__error__": d.get("quoteSummary", {}).get("error", "sin datos")}
        return res[0]
    return cached_json_fetch(f"qsum_{ticker}", fetch, max_age_sec=6 * 3600)


# ---------------------------------------------------------------------------
# SEC EDGAR - EPS historico real para emisores registrados en EEUU (incluye
# ADRs de empresas argentinas que presentan 20-F).
# ---------------------------------------------------------------------------
_cik_map = None


def _load_cik_map():
    global _cik_map
    if _cik_map is not None:
        return _cik_map

    def fetch():
        raw = _get("https://www.sec.gov/files/company_tickers.json", headers={"User-Agent": SEC_UA})
        return json.loads(raw)
    d = cached_json_fetch("sec_company_tickers", fetch, max_age_sec=7 * 24 * 3600)
    m = {}
    if "__error__" not in d:
        for v in d.values():
            m[v["ticker"].upper()] = v["cik_str"]
    _cik_map = m
    return m


def sec_eps_history(ticker):
    """Devuelve lista de dicts {fy, end, val} de EPS diluido anual (10-K/20-F), o [] si no disponible."""
    cik_map = _load_cik_map()
    cik = cik_map.get(ticker.upper())
    if not cik:
        return []
    cik_padded = f"{cik:010d}"

    def fetch_concept(concept, taxonomy):
        url = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik_padded}/{taxonomy}/{concept}.json"
        raw = _get(url, headers={"User-Agent": SEC_UA})
        return json.loads(raw)

    candidates = [
        ("us-gaap", "EarningsPerShareDiluted"),
        ("us-gaap", "EarningsPerShareBasic"),
        ("ifrs-full", "DilutedEarningsLossPerShare"),
        ("ifrs-full", "BasicEarningsLossPerShare"),
        ("ifrs-full", "BasicAndDilutedEarningsLossPerShare"),
    ]
    for taxonomy, concept in candidates:
        d = cached_json_fetch(f"sec_{ticker}_{taxonomy}_{concept}", lambda: fetch_concept(concept, taxonomy),
                               max_age_sec=24 * 3600)
        if "__error__" in d:
            continue
        try:
            units = d["units"]
            unit_key = next(iter(units.keys()))
            points = units[unit_key]
        except Exception:
            continue
        annual = [p for p in points if p.get("form") in ("10-K", "20-F") and p.get("fp") == "FY" and p.get("fy")]
        by_fy = {}
        for p in annual:
            by_fy[p["fy"]] = {"fy": p["fy"], "end": p.get("end"), "val": p.get("val")}
        series = sorted(by_fy.values(), key=lambda x: x["fy"])
        if series:
            return series
    return []


# ---------------------------------------------------------------------------
# FRED (macro EEUU) - CSV publico, sin API key
# ---------------------------------------------------------------------------
def fred_series(series_id):
    def fetch():
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
        raw = _get(url, timeout=40).decode()
        lines = raw.strip().split("\n")[1:]
        out = []
        for line in lines:
            parts = line.split(",")
            if len(parts) != 2:
                continue
            date, val = parts
            if val == ".":
                continue
            try:
                out.append({"date": date, "value": float(val)})
            except ValueError:
                continue
        return out
    return cached_json_fetch(f"fred_{series_id}", fetch, max_age_sec=12 * 3600)


# ---------------------------------------------------------------------------
# BCRA (macro Argentina) - API v4.0 publica, sin API key
# ---------------------------------------------------------------------------
BCRA_VARS = {
    "reservas_usd_mm": 1,
    "tipo_cambio_mayorista": 5,
    "inflacion_mensual_pct": 27,
    "inflacion_interanual_pct": 28,
    "base_monetaria": 71,
}


def bcra_series(id_variable, limit=3000):
    def fetch():
        url = f"https://api.bcra.gob.ar/estadisticas/v4.0/monetarias/{id_variable}?limit={limit}"
        raw = _get(url)
        d = json.loads(raw)
        results = d.get("results", [])
        if not results:
            return []
        detalle = results[0].get("detalle", [])
        # normalize to {date, value}
        return [{"date": p["fecha"], "value": p["valor"]} for p in detalle]
    return cached_json_fetch(f"bcra_{id_variable}", fetch, max_age_sec=12 * 3600)


# ---------------------------------------------------------------------------
# multpl.com - CAPE y P/E historico REAL del S&P 500 (nivel indice, la fuente
# de Shiller). Se usa como referencia de indice / para SPY.
# ---------------------------------------------------------------------------
def multpl_latest(path):
    """path: 'shiller-pe' o 's-p-500-pe-ratio'. Devuelve {value, date} del ultimo dato publicado."""
    def fetch():
        url = f"https://www.multpl.com/{path}/table/by-month"
        raw = _get(url, headers={"User-Agent": UA}).decode(errors="ignore")
        idx = raw.find('id="datatable"')
        if idx == -1:
            return {"__error__": "tabla no encontrada"}
        raw = raw[idx:]
        rows = re.findall(r"<tr[^>]*>\s*<td[^>]*>([^<]+)</td>\s*<td[^>]*>([^<]+)</td>", raw)
        out = []
        for date_s, val_s in rows:
            val_s = re.sub(r"&#x?[0-9a-fA-F]+;", " ", val_s)
            val_s = val_s.strip().replace(",", "")
            m = re.search(r"[-+]?[0-9]*\.?[0-9]+", val_s)
            if not m:
                continue
            out.append({"date": date_s.strip(), "value": float(m.group())})
        return out
    return cached_json_fetch(f"multpl_{path}", fetch, max_age_sec=24 * 3600)


if __name__ == "__main__":
    print("Test chart GGAL.BA:", str(yahoo_chart("GGAL.BA"))[:200])
    print("Test qsum AAPL:", str(yahoo_quote_summary("AAPL"))[:200])
    print("Test SEC YPF:", sec_eps_history("YPF")[:5])
    print("Test FRED FEDFUNDS:", fred_series("FEDFUNDS")[-3:])
    print("Test BCRA reservas:", bcra_series(1)[:2])
    print("Test multpl CAPE:", multpl_latest("shiller-pe")[:3])
