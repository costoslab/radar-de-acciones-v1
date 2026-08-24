"""
Orquesta la construccion del dataset completo del Radar de Acciones:
para cada ticker del universo, trae precio, EPS historico (si hay fuente),
calcula P/E, pseudo-CAPE (3/5/10 anios), proxy de ciclo y contexto macro,
y arma el score combinado. Escribe output/dataset.json
"""
import json
import time
import sys
import traceback
from datetime import datetime, timezone

import data_sources as ds
import compute as cp
from universe import UNIVERSE

CAPE_WINDOWS = [3, 5, 10]


def _num(d, *keys):
    for k in keys:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    if isinstance(d, dict):
        return d.get("raw")
    return d


def build_asset_record(entry, cpi_series, multpl_cape, multpl_pe):
    ticker = entry["ticker"]
    asset_type = entry["asset_type"]
    currency = entry["currency"]
    record = {
        "ticker": ticker,
        "asset_type": asset_type,
        "currency": currency,
        "errors": [],
    }

    # --- Precio + historial ---
    chart = ds.yahoo_chart(ticker, range_="20y", interval="1mo")
    if "__error__" in chart:
        record["errors"].append(f"chart: {chart['__error__']}")
        closes, timestamps, meta = [], [], {}
    else:
        closes, timestamps, meta = chart.get("closes", []), chart.get("timestamps", []), chart.get("meta", {})

    price = meta.get("regularMarketPrice")
    record["name"] = meta.get("longName") or meta.get("shortName") or ticker
    record["price"] = price
    record["price_currency"] = meta.get("currency")
    record["exchange"] = meta.get("fullExchangeName")

    # --- Fundamentals via Yahoo (trailing PE, EPS, sector) ---
    qsum = ds.yahoo_quote_summary(ticker)
    trailing_pe_yahoo = None
    trailing_eps_yahoo = None
    sector = None
    if "__error__" not in qsum:
        sd = qsum.get("summaryDetail", {})
        dks = qsum.get("defaultKeyStatistics", {})
        ap = qsum.get("assetProfile", {})
        trailing_pe_yahoo = _num(sd, "trailingPE") or _num(dks, "trailingEps")  # fallback path handled below
        trailing_pe_yahoo = _num(sd, "trailingPE")
        trailing_eps_yahoo = _num(dks, "trailingEps")
        sector = ap.get("sector")
    else:
        record["errors"].append(f"quoteSummary: {qsum['__error__']}")
    record["sector"] = sector

    # --- EPS historico real (SEC EDGAR primero, unica fuente con profundidad) ---
    # IMPORTANTE: para emisores argentinos, los estados contables se re-expresan
    # por inflacion (NIIF 29) y el EPS nominal historico NO es comparable ano a
    # ano ni contra un precio en USD sin una metodologia de tipo de cambio mucho
    # mas fina que la que se puede garantizar con fuentes gratuitas. Se detecto
    # empiricamente probando con GGAL (salto de EPS nominal 32.98 -> 1095.51 en
    # 2 anios) que produce un pseudo-CAPE sin sentido. Por eso se excluye el
    # pseudo-CAPE para estos emisores y se deja solo el P/E puntual.
    is_ar_issuer = entry.get("is_argentine_issuer", False)
    eps_points = [] if is_ar_issuer else ds.sec_eps_history(ticker.replace(".BA", ""))
    eps_source = "SEC EDGAR (10-K/20-F)" if eps_points else None

    real_eps = cp.real_eps_series(eps_points, cpi_series) if eps_points else []

    trailing_pe = trailing_pe_yahoo if trailing_pe_yahoo else cp.trailing_pe(price, trailing_eps_yahoo)
    record["trailing_pe"] = trailing_pe
    record["trailing_eps"] = trailing_eps_yahoo

    cape_by_window = {}
    for n in CAPE_WINDOWS:
        if ticker == "SPY" and multpl_cape:
            cape_by_window[str(n)] = {"value": multpl_cape, "years_used": None,
                                       "source": "multpl.com (Shiller CAPE real del S&P 500)"}
            continue
        if is_ar_issuer:
            cape_by_window[str(n)] = {
                "value": None, "years_used": 0,
                "reason": ("No calculable de forma confiable: los balances de emisores argentinos se "
                           "re-expresan por inflacion (NIIF 29), lo que hace que el EPS nominal historico "
                           "no sea comparable ano a ano ni contra el precio sin un ajuste cambiario fino "
                           "que no se puede garantizar con fuentes gratuitas."),
            }
            continue
        val, years_used = cp.pseudo_cape(price, real_eps, n)
        if val is not None:
            cape_by_window[str(n)] = {"value": val, "years_used": years_used,
                                       "source": "pseudo-CAPE aproximado (EPS SEC EDGAR ajustado por CPI EEUU)"}
        else:
            cape_by_window[str(n)] = {"value": None, "years_used": years_used,
                                       "reason": "EPS historico insuficiente o negativo"}
    record["cape"] = cape_by_window
    record["eps_source"] = eps_source
    record["eps_years_available"] = len(real_eps)

    # --- Valuacion: bandas del video ---
    pe_score, pe_label = cp.band_score(trailing_pe if ticker != "SPY" else multpl_pe)
    record["pe_band"] = {"score": pe_score, "label": pe_label}
    if ticker == "SPY" and multpl_pe:
        record["trailing_pe"] = multpl_pe
        record["trailing_pe_source"] = "multpl.com (P/E real del S&P 500)"

    valuation_by_window = {}
    for n in CAPE_WINDOWS:
        cape_val = cape_by_window[str(n)]["value"]
        cape_score, cape_label = cp.band_score(cape_val)
        if pe_score is not None and cape_score is not None:
            v_score = (pe_score + cape_score) / 2
        elif pe_score is not None:
            v_score = pe_score
        elif cape_score is not None:
            v_score = cape_score
        else:
            v_score = None
        valuation_by_window[str(n)] = {"score": v_score, "pe_label": pe_label, "cape_label": cape_label}
    record["valuation_by_window"] = valuation_by_window

    # --- Ciclo (proxy heuristico) ---
    cycle = cp.cycle_proxy(closes, timestamps)
    record["cycle"] = cycle

    # --- Macro segun moneda ---
    record["macro_region"] = "AR" if currency == "ARS" else "US"

    # --- Confianza del dato ---
    if eps_source and record["eps_years_available"] >= 8:
        confidence = "Alta"
    elif eps_source and record["eps_years_available"] >= 3:
        confidence = "Media"
    elif trailing_pe is not None:
        confidence = "Baja (solo P/E puntual, sin historial de EPS)"
    else:
        confidence = "Muy baja / datos insuficientes"
    if ticker == "SPY":
        confidence = "Alta (CAPE real de Shiller via multpl.com)"
    record["data_confidence"] = confidence

    record["last_updated"] = datetime.now(timezone.utc).isoformat()
    return record


def main():
    cpi_series = ds.fred_series("CPIAUCSL")
    if not isinstance(cpi_series, list):
        print("ADVERTENCIA: no se pudo obtener CPI de EEUU, pseudo-CAPE quedara sin ajuste por inflacion", file=sys.stderr)
        cpi_series = []

    multpl_cape_series = ds.multpl_latest("shiller-pe")
    multpl_pe_series = ds.multpl_latest("s-p-500-pe-ratio")
    multpl_cape = multpl_cape_series[0]["value"] if isinstance(multpl_cape_series, list) and multpl_cape_series else None
    multpl_pe = multpl_pe_series[0]["value"] if isinstance(multpl_pe_series, list) and multpl_pe_series else None

    macro_us = cp.macro_us_snapshot()
    macro_ar = cp.macro_ar_snapshot()

    records = []
    n = len(UNIVERSE)
    for i, entry in enumerate(UNIVERSE):
        ticker = entry["ticker"]
        print(f"[{i+1}/{n}] {ticker} ...", file=sys.stderr)
        try:
            rec = build_asset_record(entry, cpi_series, multpl_cape, multpl_pe)
        except Exception as e:
            print(f"  ERROR en {ticker}: {e}", file=sys.stderr)
            traceback.print_exc()
            rec = {"ticker": ticker, "asset_type": entry["asset_type"], "currency": entry["currency"],
                   "errors": [str(e)], "data_confidence": "Error"}
        records.append(rec)
        time.sleep(0.35)

    dataset = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "macro_us": macro_us,
        "macro_ar": macro_ar,
        "sp500_cape_multpl": multpl_cape,
        "sp500_pe_multpl": multpl_pe,
        "assets": records,
    }

    out_path = "../output/dataset.json"
    with open(out_path, "w") as f:
        json.dump(dataset, f, indent=2, default=str)
    print(f"\nDataset escrito en {out_path} ({len(records)} activos)", file=sys.stderr)


if __name__ == "__main__":
    main()
