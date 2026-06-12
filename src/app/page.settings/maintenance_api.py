"""
데이터베이스 유지보수 API
- 거래 로그 정리
- 일일 요약 생성
- 시뮬레이션 기록 정리
"""

_TIME = wiz.model("portal/trading/kst")

def maintenance_status():
    """현재 데이터베이스 상태 조회"""
    try:
        trading = wiz.model("portal/trading/trading")
        
        # 테이블별 레코드 수 조회
        stats = {
            "trade_log": trading.db("trade_log").count(),
            "cycle_trade": trading.db("cycle_trade").count(),
            "simulation_run": trading.db("simulation_run").count(),
            "simulation_trade": trading.db("simulation_trade").count(),
            "daily_trade_summary": trading.db("daily_trade_summary").count(),
        }
        
        # 오래된 데이터 크기 추정 (30일 이상)
        import datetime
        cutoff_date = (_TIME.now() - datetime.timedelta(days=30)).replace(hour=0, minute=0, second=0, microsecond=0)
        
        old_logs = trading.db("trade_log").rows() or []
        old_logs = [log for log in old_logs if (log.get("created", _TIME.now()) < cutoff_date)]
        
        status = {
            "tables": stats,
            "old_trade_logs_count": len(old_logs),
            "timestamp": _TIME.isoformat(with_offset=True),
        }
        
        wiz.response.status(200, **status)
    except Exception as e:
        wiz.response.status(500, message=str(e))


def cleanup_database():
    """데이터베이스 전체 정리"""
    trading = wiz.model("portal/trading/trading")
    maintenance = trading.model("maintenance")
    
    try:
        result = maintenance.database_maintenance()
        wiz.response.status(200, **result)
    except Exception as e:
        wiz.response.status(500, message=str(e))


def cleanup_trade_logs():
    """오래된 거래 로그만 정리"""
    trading = wiz.model("portal/trading/trading")
    maintenance = trading.model("maintenance")
    days = int(wiz.request.query("days", 30))
    
    try:
        count = maintenance.archive_old_trade_logs(days_to_keep=days)
        wiz.response.status(200, deleted_count=count, days_kept=days)
    except Exception as e:
        wiz.response.status(500, message=str(e))


def cleanup_simulations():
    """시뮬레이션 기록 정리"""
    trading = wiz.model("portal/trading/trading")
    maintenance = trading.model("maintenance")
    days = int(wiz.request.query("days", 90))
    
    try:
        runs, trades = maintenance.cleanup_old_simulations(days_to_keep=days)
        wiz.response.status(200, deleted_runs=runs, deleted_trades=trades, days_kept=days)
    except Exception as e:
        wiz.response.status(500, message=str(e))


def rebuild_summaries():
    """일일 거래 요약 재생성"""
    trading = wiz.model("portal/trading/trading")
    maintenance = trading.model("maintenance")
    from_date = wiz.request.query("from_date", "")
    to_date = wiz.request.query("to_date", "")
    
    try:
        count = maintenance.rebuild_daily_summaries(from_date=from_date if from_date else None, 
                                                    to_date=to_date if to_date else None)
        wiz.response.status(200, rebuilt_count=count, from_date=from_date, to_date=to_date)
    except Exception as e:
        wiz.response.status(500, message=str(e))
