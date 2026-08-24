"""
Radar de Acciones - Logica de calculo: P/E, pseudo-CAPE, proxy de ciclo
(heuristica, NO Ondas de Elliott reales), contexto macro, y score combinado.

Todo numero mostrado sale de un dato real obtenido en data_sources.py.
Cuando falta un dato, el campo correspondiente queda None y se marca
data_quality mas bajo -- nunca se inventa un valor.
"""
from datetime import datetime, timezone
import statistics
import data_sources as ds

VIDEO_BANDS = [
    (0, 10, 2, "Oportunidad historica"),
    (10, 20, 1, "Zona de valor"),
    (20, 25, 0, "Valuacion normal"),
    (25, 30, -1, "Zona de atencion"),
    (30, float("inf"), -2, "Zona de alerta historica"),
]


def band_score(value):
    """Aplica los rangos de P/E y CAPE que el video propone (a nivel S&P500)."""
    if value is None:
        return None, None
    for lo, hi, score, label in VIDEO_BANDS:
        if lo <= value < hi:
            return score, label
    return None, None


# ---------------------------------------------------------------------------
# Precio / EPS -> P/E, pseudo-CAPE
# ---------------------------------------------------------------------------
def _closest_cpi(cpi_series, date_str):
    """cpi_series: lista [{date,value}] mensual. date_str: 'YYYY-MM-DD'."""
    if not cpi_series or not date_str:
        return None
    target = date_str[:7]  # YYYY-MM
    best = None
    best_diff = None
    for p in cpi_series:
        diff = abs((p["date"][:7] > target) - (p["date"][:7] < target))
        # simpler: exact or closest by string distance on year-month
        d = p["date"][:7]
        dist = abs(int(d[:4]) * 12 + int(d[5:7]) - (int(target[:4]) * 12 + int(target[5:7])))
        if best_diff is None or dist < best_diff:
            best_diff = dist
            best = p
    return best["value"] if best else None


def real_eps_series(eps_points, cpi_series):
    """eps_points: [{fy,end,val}] nominal EPS anual (USD).
    Devuelve [{fy,end,nominal,real}] ajustado a poder adquisitivo actual (US CPI)."""
    if not eps_points or not cpi_series:
        return []
    # el cache de FRED se escribe en orden cronologico ascendente (mas viejo primero)
    cpi_now = cpi_series[-1]["value"]
    out = []
    for p in eps_points:
        cpi_then = _closest_cpi(cpi_series, p.get("end"))
        if cpi_then is None or p.get("val") is None:
            continue
        real = p["val"] * (cpi_now / cpi_then)
        out.append({"fy": p["fy"], "end": p["end"], "nominal": p["val"], "real": real})
    return out


def pseudo_cape(price, real_eps_pts, n_years):
    """Precio / promedio de EPS real de los ultimos n_years disponibles."""
    if not real_eps_pts or price is None:
        return None, 0
    pts = sorted(real_eps_pts, key=lambda x: x["fy"])[-n_years:]
    if not pts:
        return None, 0
    avg = statistics.mean(p["real"] for p in pts)
    if avg <= 0:
        return None, len(pts)  # ganancias promedio negativas -> CAPE no interpretable
    return price / avg, len(pts)


def trailing_pe(price, trailing_eps):
    if price is None or not trailing_eps:
        return None
    if trailing_eps <= 0:
        return None
    return price / trailing_eps


# ---------------------------------------------------------------------------
# Proxy heuristico de "ubicacion en el ciclo" (NO es conteo de Ondas de
# Elliott real -- es una aproximacion transparente basada en precio).
# ---------------------------------------------------------------------------
def _sma(values, window):
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def cycle_proxy(closes, timestamps):
    """closes/timestamps: series mensuales de yahoo_chart (mas reciente al final)."""
    pts = [(t, c) for t, c in zip(timestamps or [], closes or []) if c is not None]
    if len(pts) < 6:
        return {"available": False, "reason": "historial de precio insuficiente"}
    vals = [c for _, c in pts]
    last_price = vals[-1]
    ath = max(vals)
    ath_idx = vals.index(ath)
    months_since_ath = len(vals) - 1 - ath_idx
    drawdown_pct = (ath - last_price) / ath * 100 if ath else None

    low_5y = min(vals[-60:]) if len(vals) >= 6 else min(vals)
    dist_from_5y_low_pct = (last_price - low_5y) / low_5y * 100 if low_5y else None

    sma12 = _sma(vals, 12)
    sma36 = _sma(vals, 36)
    sma60 = _sma(vals, 60)

    above_sma12 = last_price > sma12 if sma12 else None
    above_sma36 = last_price > sma36 if sma36 else None

    # momentum: variacion de los ultimos 6 meses vs los 6 anteriores
    momentum = None
    if len(vals) >= 12:
        recent = vals[-6:]
        prior = vals[-12:-6]
        if prior[0]:
            momentum = (statistics.mean(recent) - statistics.mean(prior)) / statistics.mean(prior) * 100

    # clasificacion heuristica
    stage, score = "Sin datos suficientes", None
    if drawdown_pct is not None and dist_from_5y_low_pct is not None:
        if drawdown_pct >= 40 and dist_from_5y_low_pct <= 15:
            stage, score = "Posible piso / acumulacion (precio cerca de minimos de 5 anios, lejos del maximo)", 2
        elif drawdown_pct >= 20 and (momentum is not None and momentum > 0):
            stage, score = "Posible recuperacion temprana (recupera desde una caida, con momentum positivo)", 1
        elif drawdown_pct <= 5 and above_sma12 and above_sma36:
            stage, score = "Cerca de maximos historicos / posible zona de distribucion-euforia", -2
        elif drawdown_pct <= 15 and above_sma12 and (momentum is not None and momentum < 0):
            stage, score = "Extendido, con perdida de momentum (posible techo formandose)", -1
        elif above_sma12 and above_sma36:
            stage, score = "Tendencia alcista de mediano/largo plazo en curso", 0
        elif not above_sma12 and not above_sma36:
            stage, score = "Tendencia bajista / correctiva de mediano/largo plazo", 0
        else:
            stage, score = "Fase mixta / sin sesgo claro", 0

    return {
        "available": True,
        "last_price": last_price,
        "ath": ath,
        "months_since_ath": months_since_ath,
        "drawdown_from_ath_pct": drawdown_pct,
        "low_5y": low_5y,
        "dist_from_5y_low_pct": dist_from_5y_low_pct,
        "sma12": sma12,
        "sma36": sma36,
        "sma60": sma60,
        "momentum_6m_pct": momentum,
        "years_of_history": round(len(vals) / 12, 1),
        "stage_label": stage,
        "stage_score": score,
    }


# ---------------------------------------------------------------------------
# Macro
# ---------------------------------------------------------------------------
def macro_us_snapshot():
    fedfunds = ds.fred_series("FEDFUNDS")
    cpi = ds.fred_series("CPIAUCSL")
    t10y2y = ds.fred_series("T10Y2Y")
    unrate = ds.fred_series("UNRATE")
    if not isinstance(fedfunds, list) or not fedfunds:
        return {"available": False}

    ff_now = fedfunds[-1]["value"]
    ff_date = fedfunds[-1]["date"]
    ff_12m_ago = None
    for p in reversed(fedfunds):
        if p["date"] <= _shift_year(ff_date, -1):
            ff_12m_ago = p["value"]
            break
    ff_change = (ff_now - ff_12m_ago) if ff_12m_ago is not None else None

    cpi_yoy = None
    if isinstance(cpi, list) and len(cpi) >= 13:
        cpi_now = cpi[-1]["value"]
        cpi_prior = cpi[-13]["value"]
        cpi_yoy = (cpi_now / cpi_prior - 1) * 100

    curve_spread = t10y2y[-1]["value"] if isinstance(t10y2y, list) and t10y2y else None
    unemployment = unrate[-1]["value"] if isinstance(unrate, list) and unrate else None

    score = 0
    notes = []
    if ff_change is not None:
        if ff_change <= -0.25:
            score += 1
            notes.append(f"Tasa de la Fed bajando (variacion interanual {ff_change:+.2f} pp) -> sesgo expansivo")
        elif ff_change >= 0.25:
            score -= 1
            notes.append(f"Tasa de la Fed subiendo (variacion interanual {ff_change:+.2f} pp) -> sesgo restrictivo")
        else:
            notes.append(f"Tasa de la Fed estable (variacion interanual {ff_change:+.2f} pp)")
    if curve_spread is not None and curve_spread < 0:
        notes.append(f"Curva 10a-2a invertida ({curve_spread:.2f} pp) -> senial historica de alerta de recesion")
    if cpi_yoy is not None and cpi_yoy > 4:
        notes.append(f"Inflacion interanual EEUU en {cpi_yoy:.1f}% (por encima del objetivo de 2% de la Fed)")

    return {
        "available": True,
        "fed_funds_rate": ff_now,
        "fed_funds_date": ff_date,
        "fed_funds_change_12m_pp": ff_change,
        "cpi_yoy_pct": cpi_yoy,
        "yield_curve_10y2y": curve_spread,
        "unemployment_rate": unemployment,
        "macro_score": max(-1, min(1, score)),
        "notes": notes,
    }


def _shift_year(date_str, years):
    y, m, d = date_str.split("-")
    return f"{int(y) + years:04d}-{m}-{d}"


def macro_ar_snapshot():
    infl_m = ds.bcra_series(ds.BCRA_VARS["inflacion_mensual_pct"])
    infl_ia = ds.bcra_series(ds.BCRA_VARS["inflacion_interanual_pct"])
    reservas = ds.bcra_series(ds.BCRA_VARS["reservas_usd_mm"])
    tc = ds.bcra_series(ds.BCRA_VARS["tipo_cambio_mayorista"])
    if not isinstance(infl_m, list) or not infl_m:
        return {"available": False}

    # bcra_series viene ordenado del mas reciente al mas viejo (indice 0 = ultimo dato)
    infl_m_sorted = sorted(infl_m, key=lambda x: x["date"])
    last6 = [p["value"] for p in infl_m_sorted[-6:]]
    prev6 = [p["value"] for p in infl_m_sorted[-12:-6]] if len(infl_m_sorted) >= 12 else None

    score = 0
    notes = []
    trend = None
    if prev6 and last6:
        avg_last6 = statistics.mean(last6)
        avg_prev6 = statistics.mean(prev6)
        trend = avg_last6 - avg_prev6
        if trend < -0.3:
            score = 1
            notes.append(f"Inflacion mensual desacelerando (prom. ult. 6m {avg_last6:.1f}% vs 6m previos {avg_prev6:.1f}%)")
        elif trend > 0.3:
            score = -1
            notes.append(f"Inflacion mensual acelerando (prom. ult. 6m {avg_last6:.1f}% vs 6m previos {avg_prev6:.1f}%)")
        else:
            notes.append(f"Inflacion mensual relativamente estable (prom. ult. 6m {avg_last6:.1f}%)")

    infl_ia_last = None
    if isinstance(infl_ia, list) and infl_ia:
        infl_ia_last = sorted(infl_ia, key=lambda x: x["date"])[-1]["value"]
        notes.append(f"Inflacion interanual {infl_ia_last:.1f}%")

    reservas_last = None
    if isinstance(reservas, list) and reservas:
        reservas_last = sorted(reservas, key=lambda x: x["date"])[-1]["value"]

    tc_last = None
    if isinstance(tc, list) and tc:
        tc_last = sorted(tc, key=lambda x: x["date"])[-1]["value"]

    return {
        "available": True,
        "inflacion_mensual_ult_pct": last6[-1] if last6 else None,
        "inflacion_interanual_pct": infl_ia_last,
        "reservas_usd_mm": reservas_last,
        "tipo_cambio_mayorista": tc_last,
        "macro_score": score,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# Score combinado (3 pilares) -- heuristica transparente, NO una probabilidad
# estadistica ni asesoramiento financiero.
# ---------------------------------------------------------------------------
WEIGHTS = {"valuacion": 0.40, "ciclo": 0.35, "macro": 0.25}


def combined_signal(valuation_score, cycle_score, macro_score, confidence):
    """Cada score de entrada esta en escala -2..+2 (valuacion, ciclo) o -1..+1
    (macro). Se normaliza todo a -2..+2, se pondera y se mapea a 0-100."""
    parts = []
    if valuation_score is not None:
        parts.append(("valuacion", valuation_score, WEIGHTS["valuacion"]))
    if cycle_score is not None:
        parts.append(("ciclo", cycle_score, WEIGHTS["ciclo"]))
    if macro_score is not None:
        parts.append(("macro", macro_score * 2, WEIGHTS["macro"]))  # -1..1 -> -2..2

    if not parts:
        return {"score_0_100": None, "signal": "Sin datos suficientes", "detail": []}

    total_w = sum(w for _, _, w in parts)
    weighted = sum(v * w for _, v, w in parts) / total_w  # -2..2

    score_0_100 = round((weighted + 2) / 4 * 100)

    if score_0_100 >= 65:
        signal = "Compra (favorable)"
    elif score_0_100 <= 35:
        signal = "Venta / evitar (desfavorable)"
    else:
        signal = "Mantener / neutral"

    return {
        "score_0_100": score_0_100,
        "signal": signal,
        "confidence": confidence,
        "detail": [{"pilar": p, "valor": v, "peso": w} for p, v, w in parts],
    }
