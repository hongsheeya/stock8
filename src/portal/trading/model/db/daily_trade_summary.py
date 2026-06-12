import peewee as pw
import datetime

orm = wiz.model("portal/season/orm")
base = orm.base("trading")
_TIME = wiz.model("portal/trading/kst")


def _kst_now():
    return _TIME.now()

class Model(base):
    class Meta:
        db_table = "daily_trade_summary"

    id = pw.CharField(max_length=32, primary_key=True)
    trade_date = pw.CharField(max_length=10, index=True, unique=True)
    
    # 거래 개수
    buy_count = pw.IntegerField(default=0)
    sell_count = pw.IntegerField(default=0)
    total_count = pw.IntegerField(default=0)
    
    # 거래 금액 (KRW)
    total_buy_amount = pw.FloatField(default=0.0)
    total_sell_amount = pw.FloatField(default=0.0)
    net_investment = pw.FloatField(default=0.0)
    
    # 수익성
    realized_profit = pw.FloatField(default=0.0)
    realized_profit_rate = pw.FloatField(default=0.0)
    unrealized_profit = pw.FloatField(default=0.0)
    total_profit = pw.FloatField(default=0.0)
    total_profit_rate = pw.FloatField(default=0.0)
    
    # 거래 유형별 분류
    cycle_trade_count = pw.IntegerField(default=0)
    daytrade_count = pw.IntegerField(default=0)
    infinitebuy_count = pw.IntegerField(default=0)
    
    # 수수료 및 세금
    total_commission = pw.FloatField(default=0.0)
    total_tax = pw.FloatField(default=0.0)
    
    # 관여 종목 개수
    symbols_count = pw.IntegerField(default=0)
    symbols_list = pw.TextField(default="")  # JSON array of symbols
    
    # 메타데이터
    data_source = pw.CharField(max_length=32, default="auto")  # 'auto', 'manual', 'broker_sync'
    raw_data_count = pw.IntegerField(default=0)  # trade_log에서 집계된 레코드 수
    archived = pw.BooleanField(default=False, index=True)
    archived_at = pw.DateTimeField(null=True)
    
    created = pw.DateTimeField(default=_kst_now)
    updated = pw.DateTimeField(default=_kst_now)
