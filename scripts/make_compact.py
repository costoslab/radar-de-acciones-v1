"""Genera una version compacta (numeros redondeados) del dataset para embeber en el dashboard."""
import json


def r(x, nd=2):
    if isinstance(x, (int, float)):
        return round(x, nd)
    return x


def compact_asset(a):
    cape = {}
    for k, v in a.get("cape", {}).items():
        cape[k] = {"value": r(v.get("value"), 2), "years_used": v.get("years_used"),
                    "source": v.get("source"), "reason": v.get("reason")}
    cycle = a.get("cycle", {})
    cycle_c = {
        "available": cycle.get("available", False),
    }
    if cycle.get("available"):
        cycle_c.update({
            "drawdown_from_ath_pct": r(cycle.get("drawdown_from_ath_pct")),
            "dist_from_5y_low_pct": r(cycle.get("dist_from_5y_low_pct")),
            "momentum_6m_pct": r(cycle.get("momentum_6m_pct")),
            "years_of_history": cycle.get("years_of_history"),
            "stage_label": cycle.get("stage_label"),
            "stage_score": cycle.get("stage_score"),
            "above_sma12": (cycle.get("last_price") > cycle["sma12"]) if cycle.get("sma12") else None,
            "above_sma36": (cycle.get("last_price") > cycle["sma36"]) if cycle.get("sma36") else None,
        })
    else:
        cycle_c["reason"] = cycle.get("reason")

    return {
        "ticker": a["ticker"],
        "name": a.get("name"),
        "asset_type": a["asset_type"],
        "currency": a["currency"],
        "price": r(a.get("price"), 4),
        "price_currency": a.get("price_currency"),
        "exchange": a.get("exchange"),
        "sector": a.get("sector"),
        "trailing_pe": r(a.get("trailing_pe")),
        "trailing_pe_source": a.get("trailing_pe_source", "Yahoo Finance"),
        "cape": cape,
        "eps_source": a.get("eps_source"),
        "eps_years_available": a.get("eps_years_available"),
        "cycle": cycle_c,
        "macro_region": a.get("macro_region"),
        "data_confidence": a.get("data_confidence"),
    }


def main():
    d = json.load(open("../output/dataset.json"))
    compact = {
        "generated_at": d["generated_at"],
        "macro_us": d["macro_us"],
        "macro_ar": d["macro_ar"],
        "sp500_cape_multpl": r(d.get("sp500_cape_multpl")),
        "sp500_pe_multpl": r(d.get("sp500_pe_multpl")),
        "assets": [compact_asset(a) for a in d["assets"]],
    }
    with open("../output/dataset_compact.json", "w") as f:
        json.dump(compact, f, separators=(",", ":"), default=str)
    import os
    size = os.path.getsize("../output/dataset_compact.json")
    print(f"dataset_compact.json: {size/1024:.1f} KB, {len(compact['assets'])} activos")


if __name__ == "__main__":
    main()
