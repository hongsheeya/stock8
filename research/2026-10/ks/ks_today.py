import json, importlib.util
spec = importlib.util.spec_from_file_location("y", "ks_year_study.py"); y = importlib.util.module_from_spec(spec); spec.loader.exec_module(y)
base = r"C:\Users\변기국학부재학지능형반도체공학과\Documents\ChatGPT\New project 3\stock8\data"
t = json.load(open(base + r"\paper\daytrade\ks_minute_archive\2026-10-21.json", encoding="utf-8"))
p = json.load(open(base + r"\live\daytrade\f20da15217e609e9eebc99f3\ks_minute_archive\2026-10-20.json", encoding="utf-8"))
data = {}
for sym, rows in t["bars"].items():
    data[sym] = {"2026-10-21": y.five_minute(rows)}
print("symbols", sorted(t["bars"]), {s: len(r) for s, r in t["bars"].items()})
for idx in ("069500", "229200"):
    pc = p["bars"][idx][-1]["close"]; ix = data[idx]["2026-10-21"]
    print(idx, "prev", pc, "open", ix[0]["open"], "gap %+.2f%%" % ((ix[0]["open"] / pc - 1) * 100),
          "close %+.2f%% vs open" % ((ix[-1]["close"] / ix[0]["open"] - 1) * 100), "high", max(b["high"] for b in ix), "low", min(b["low"] for b in ix))
    for b in ix:
        if b["hm"] in ("09:00","09:10","09:15","09:20","09:30","09:45","10:00","10:30","11:00","12:00","13:00","14:00","14:30","15:00","15:15"):
            print("  ", b["hm"], round(b["close"], 1), "vwap", round(b["vwap"], 1), "%+.2f%%" % ((b["close"] / ix[0]["open"] - 1) * 100))
for etf in y.PAIRS:
    if etf in data and data[y.PAIRS[etf][1]]:
        for start in ("09:15", "10:00"):
            print(etf, start, [round(x, 2) for x in y.run(data, etf, "2026-10-21", start=start)])
