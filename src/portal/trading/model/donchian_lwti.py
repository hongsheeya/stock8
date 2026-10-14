"""Research-only Donchian/LWTI/volume hypothesis. Never sends orders.

LWTI convention: 50 + 50*SMA(close-close[n],n)/Wilder ATR(n).
Green means >50, not a guarantee of trend strength. No optional smoothing.
"""
import numpy as np
import pandas as pd


def indicators(frame, channel=20, period=8, volume_period=20):
    if min(channel,period,volume_period)<2:
        raise ValueError('Periods must be >=2')
    f=frame.copy()
    c,h,l=f['close'],f['high'],f['low']
    tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    atr=pd.Series(np.nan,index=f.index,dtype=float)
    if len(f)>=period:
        atr.iloc[period-1]=tr.iloc[:period].mean()
        for i in range(period,len(f)):
            atr.iloc[i]=(atr.iloc[i-1]*(period-1)+tr.iloc[i])/period
    # Exclude the signal bar from the channel/volume benchmark.
    f['upper']=h.shift().rolling(channel,min_periods=channel).max()
    f['lower']=l.shift().rolling(channel,min_periods=channel).min()
    f['middle']=(f.upper+f.lower)/2
    f['lwti']=50+50*(c-c.shift(period)).rolling(period,min_periods=period).mean()/atr.replace(0,np.nan)
    f['rvol']=f.volume/f.volume.shift().rolling(volume_period,min_periods=volume_period).mean().replace(0,np.nan)
    return f


def targets(frame, use_lwti=True, use_volume=True, volume_multiple=1.5):
    """Completed-close signal; caller executes next open. Long-only/day-flat.
    Warmup carries across sessions, but positions reset. No entry after 14:30.
    Exit is mid-channel close breach (all variants) or scheduled close in replay.
    """
    f=indicators(frame)
    values=[]; state=0; day=None
    for ts,b in f.iterrows():
        if ts.date()!=day: state=0; day=ts.date()
        if state:
            if b.close<b.middle: state=0
        elif ('09:30'<=ts.strftime('%H:%M')<='14:30' and b.close>b.upper
              and (not use_lwti or b.lwti>50)
              and (not use_volume or b.rvol>=volume_multiple)):
            state=1
        values.append(state)
    return pd.Series(values,index=f.index,dtype=float)
