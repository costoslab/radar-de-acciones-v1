"""
Universo de activos precargado para el screener masivo.
No es exhaustivo (S&P500 completo, todo BYMA, todos los CEDEAR) -- es una
seleccion curada representativa de cada categoria de la tabla del usuario,
elegida para mantener el tiempo de armado del dataset razonable y la
confiabilidad de los datos alta. Se puede ampliar bajo pedido.
"""

BYMA_LOCAL = [
    "GGAL.BA", "YPFD.BA", "PAMP.BA", "ALUA.BA", "TXAR.BA", "BMA.BA", "BBAR.BA",
    "SUPV.BA", "CEPU.BA", "TGSU2.BA", "TRAN.BA", "EDN.BA", "LOMA.BA", "CRES.BA",
    "IRSA.BA", "MIRG.BA", "VALO.BA", "COME.BA", "BYMA.BA", "TGNO4.BA", "CVH.BA",
    "METR.BA",
]

ADR_ARGENTINOS = [
    "GGAL", "YPF", "PAM", "BMA", "BBAR", "SUPV", "CEPU", "TGS", "EDN", "LOMA",
    "CRESY", "IRS", "TS", "BIOX", "GLOB",
]  # DESP (Despegar) excluido: deslistada tras su adquisicion por Prosus, sin datos de mercado

CEDEAR_SUBYACENTES = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "JPM", "KO", "PG",
    "JNJ", "V", "MA", "DIS", "NFLX", "XOM", "CVX", "WMT", "HD", "PFE", "BA",
    "INTC", "IBM", "UNH", "COST", "PEP", "MCD", "NKE", "ADBE", "CRM", "ORCL",
    "CSCO", "T", "VZ", "WFC", "GS", "BAC", "C", "MELI", "BRK-B",
]

ETFS = ["SPY", "QQQ", "IWM", "DIA", "EEM", "XLF", "XLE", "XLK", "GLD"]

UNIVERSE = (
    [{"ticker": t, "asset_type": "Accion local BYMA/MERVAL", "currency": "ARS", "is_argentine_issuer": True} for t in BYMA_LOCAL]
    + [{"ticker": t, "asset_type": "ADR estadounidense", "currency": "USD", "is_argentine_issuer": True} for t in ADR_ARGENTINOS]
    + [{"ticker": t, "asset_type": "CEDEAR (subyacente)", "currency": "USD", "is_argentine_issuer": False} for t in CEDEAR_SUBYACENTES]
    + [{"ticker": t, "asset_type": "ETF", "currency": "USD", "is_argentine_issuer": False} for t in ETFS]
)

if __name__ == "__main__":
    print(f"Universo total: {len(UNIVERSE)} activos")
    from collections import Counter
    print(Counter(u["asset_type"] for u in UNIVERSE))
