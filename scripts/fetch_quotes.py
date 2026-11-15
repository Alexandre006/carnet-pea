"""Carnet PEA — robot de cours.

Récupère les cours de Bourse (Yahoo Finance, via la bibliothèque yfinance) pour l'univers
suivi, puis écrit :
  data/quotes.json     dernier cours, variation, plus haut/bas 52 semaines, perf., dividendes
  data/h/<TICKER>.json clôtures quotidiennes sur 2 ans (pour graphiques et indicateurs)
Les données de marché sont publiques : aucune donnée personnelle n'est lue ni écrite ici.
"""
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(os.environ.get("CARNET_ROOT") or Path(__file__).resolve().parent.parent)
DATA = ROOT / "data"
HDIR = DATA / "h"
UNIVERSE = json.loads((ROOT / "data" / "universe.json").read_text(encoding="utf-8"))


def fname(ticker):
    """Nom de fichier sûr pour Pages (pas de caractère spécial, pas de tiret bas initial)."""
    return ticker.replace("^", "IDX-").replace("/", "-") + ".json"


def r4(x):
    return round(float(x), 4)


def extra_tickers():
    p = ROOT / "extra-tickers.txt"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        t = line.split("#")[0].strip().upper()
        if t:
            out.append(t)
    return out


def frame_to_series(df):
    """DataFrame yfinance (index daté, colonnes Close/Dividends) → (dates, clôtures, dividendes)."""
    if df is None or len(df) == 0 or "Close" not in df.columns:
        return [], [], []
    divs = []
    if "Dividends" in df.columns:
        for ix, v in df["Dividends"].items():
            try:
                v = float(v)
            except (TypeError, ValueError):
                continue
            if v > 0:
                divs.append((ix.strftime("%Y-%m-%d"), v))
    df = df.dropna(subset=["Close"])
    dates = [ix.strftime("%Y-%m-%d") for ix in df.index]
    closes = [float(x) for x in df["Close"]]
    keep = [(d, c) for d, c in zip(dates, closes) if c > 0]
    return [d for d, _ in keep], [c for _, c in keep], divs


def summarize(dates, closes, divs):
    n = len(closes)
    if n < 2:
        return None
    last, prev, d = closes[-1], closes[-2], dates[-1]
    win = closes[-252:]
    before = [c for dd, c in zip(dates, closes) if dd[:4] < d[:4]]
    item = {
        "p": r4(last), "pc": r4(prev), "d": d, "ch": round(last / prev - 1, 5),
        "h52": r4(max(win)), "l52": r4(min(win)),
        "ytd": round(last / before[-1] - 1, 4) if before else None,
        "y1": round(last / closes[-253] - 1, 4) if n > 252 else None,
        "dv": [[dd, r4(a)] for dd, a in divs[-12:]],
    }
    return item


def fetch_yfinance(tickers):
    import yfinance as yf  # noqa: import tardif (absent des tests locaux)

    out = {}
    df = yf.download(tickers, period="2y", interval="1d", auto_adjust=False, actions=True,
                     group_by="ticker", threads=True, progress=False)
    for t in tickers:
        try:
            sub = df[t] if len(tickers) > 1 else df
            s = frame_to_series(sub)
            if s[0]:
                out[t] = s
        except Exception:  # ticker absent de la réponse groupée
            pass
    for t in [t for t in tickers if t not in out]:
        try:
            h = yf.Ticker(t).history(period="2y", interval="1d", auto_adjust=False, actions=True)
            s = frame_to_series(h)
            if s[0]:
                out[t] = s
            time.sleep(0.4)
        except Exception as e:
            print("échec", t, e)
    return out


def fetch_direct(tickers):
    """Secours sans bibliothèque : API publique « chart » de Yahoo."""
    out = {}
    for t in tickers:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/%s?range=2y&interval=1d&events=div" % t
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                j = json.loads(r.read().decode("utf-8"))
            res = j["chart"]["result"][0]
            ts, cl = res.get("timestamp") or [], res["indicators"]["quote"][0]["close"]
            tz = res["meta"].get("gmtoffset", 0)
            dates, closes = [], []
            for k, c in zip(ts, cl):
                if c:
                    dates.append(datetime.fromtimestamp(k + tz, timezone.utc).strftime("%Y-%m-%d"))
                    closes.append(float(c))
            divs = sorted((datetime.fromtimestamp(int(v["date"]) + tz, timezone.utc).strftime("%Y-%m-%d"), float(v["amount"]))
                          for v in (res.get("events", {}).get("dividends", {}) or {}).values())
            if dates:
                out[t] = (dates, closes, divs)
        except Exception as e:
            print("échec direct", t, e)
        time.sleep(0.3)
    return out


def build(series, tickers, old_items):
    items, ok, files = {}, 0, {}
    for t in tickers:
        s = series.get(t)
        item = summarize(*s) if s and s[0] else None
        if item:
            items[t] = item
            ok += 1
            dates, closes, _ = s
            files[fname(t)] = {"d": dates[-520:], "c": [r4(c) for c in closes[-520:]]}
        elif t in old_items:
            items[t] = dict(old_items[t], stale=True)
    return items, ok, files


def main(fetcher=None):
    tickers = list(dict.fromkeys([u[0] for u in UNIVERSE] + extra_tickers()))
    qpath = DATA / "quotes.json"
    old = {}
    if qpath.exists():
        try:
            old = json.loads(qpath.read_text(encoding="utf-8")).get("items", {}) or {}
        except ValueError:
            old = {}
    series = {}
    if fetcher:
        series = fetcher(tickers)
    else:
        try:
            series = fetch_yfinance(tickers)
        except Exception as e:
            print("yfinance indisponible :", e)
        missing = [t for t in tickers if t not in series]
        if len(missing) > len(tickers) // 2:
            series.update(fetch_direct(missing))
    items, ok, files = build(series, tickers, old)
    print("cours récupérés : %d / %d" % (ok, len(tickers)))
    if ok < max(3, len(tickers) // 3):
        print("Trop d'échecs : les données précédentes sont conservées.")
        return 1
    HDIR.mkdir(parents=True, exist_ok=True)
    # Historiques : une fois par jour après la clôture (ou lancement manuel), sinon seulement s'ils manquent.
    daily = datetime.now(timezone.utc).hour >= 16 or os.environ.get("GITHUB_EVENT_NAME") != "schedule"
    for name, h in files.items():
        f = HDIR / name
        if daily or not f.exists():
            f.write_text(json.dumps(h, separators=(",", ":")), encoding="utf-8")
    doc = {"asOf": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "src": "Yahoo Finance", "n": ok, "items": items}
    qpath.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
