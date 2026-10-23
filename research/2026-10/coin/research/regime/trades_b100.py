"""List the selected combo's (B100) position changes from 2025-10-22 on, for the audit trail."""
import pandas as pd
import regime as R
data = {m: R.load5m(m) for m in R.MARKETS}
closes = {m: R.daily_closes(m, data[m])[0] for m in R.MARKETS}
for m in R.MARKETS:
    s = R.signal("btc", 100, closes[m], closes["KRW-BTC"]).astype(int).shift(1)  # held on day D
    s = s[s.index >= R.START]
    ch = s[s.diff().fillna(s.iloc[0]) != 0]
    print(m, " ".join(f"{d.date()}:{'IN' if v else 'OUT'}" for d, v in ch.items()), "| last day", s.index[-1].date(), "IN" if s.iloc[-1] else "OUT")
