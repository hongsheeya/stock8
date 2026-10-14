"""Offline Williams-inspired hypotheses, not an original-system reproduction."""
import pandas as pd


def targets(frame, guarded=False):
    daily = frame.groupby(frame.index.date).agg(
        open=('open','first'), high=('high','max'), low=('low','min'), close=('close','last'))
    prior_range = (daily.high-daily.low).shift(1)
    prior_close = daily.close.shift(1)
    prior_ma = daily.close.rolling(10).mean().shift(1)
    result = []
    for day, bars in frame.groupby(frame.index.date):
        width = prior_range.loc[day]
        trigger = bars.open.iloc[0] + 0.5*width
        state = 0.0
        entered = False
        allowed = not guarded or prior_close.loc[day] > prior_ma.loc[day]
        for ts, bar in bars.iterrows():
            # Close-confirmed exit, NOT an intrabar guaranteed stop price.
            if state and guarded and bar.close < trigger-0.25*width:
                state = 0.0
            if not entered and allowed and '09:30' <= ts.strftime('%H:%M') <= '14:30' and bar.close > trigger:
                state = 1.0
                entered = True
            result.append(state)
    return pd.Series(result,index=frame.index,dtype=float)
