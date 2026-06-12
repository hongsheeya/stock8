"""
데이터베이스 정리 및 최적화 유틸리티
- 오래된 거래 로그 정리
- 일일 거래 요약 생성 및 관리
- 시뮬레이션 기록 정리
"""

import datetime
import json
from collections import defaultdict

_TIME = wiz.model("portal/trading/kst")

def generate_daily_trade_summary(trade_date):
    """
    특정 날짜의 거래 로그에서 일일 거래 요약을 생성한다.
    
    Args:
        trade_date: 'YYYY-MM-DD' 형식
    
    Returns:
        요약 dict 또는 None
    """
    try:
        trading = wiz.model("portal/trading/trading")
        cycle_db = trading.db("trading_cycle")
        cycle_trade_db = trading.db("cycle_trade")
        
        # 해당 날짜의 거래 사이클 조회
        cycles = cycle_db.rows(completed_at__isnull=False) or []
        cycles = [c for c in cycles if str(c.get("completed_at", ""))[:10] == trade_date]
        
        # cycle_trade에서 해당 날짜 거래 조회
        trades = cycle_trade_db.rows() or []
        trades = [t for t in trades if t.get("trade_date", "") == trade_date]
        
        if len(cycles) == 0 and len(trades) == 0:
            return None
        
        # 요약 계산
        buy_trades = [t for t in trades if t.get("action", "") == "BUY"]
        sell_trades = [t for t in trades if t.get("action", "") == "SELL"]
        
        summary = {
            "trade_date": trade_date,
            "buy_count": len(buy_trades),
            "sell_count": len(sell_trades),
            "total_count": len(trades),
            "total_buy_amount": sum(float(t.get("filled_amount", 0) or 0) for t in buy_trades),
            "total_sell_amount": sum(float(t.get("filled_amount", 0) or 0) for t in sell_trades),
            "net_investment": sum(float(t.get("filled_amount", 0) or 0) for t in buy_trades) - 
                             sum(float(t.get("filled_amount", 0) or 0) for t in sell_trades),
            "realized_profit": sum(float(c.get("current_eval", 0) or 0) - float(c.get("total_spent", 0) or 0) for c in cycles),
            "realized_profit_rate": 0.0,  # 나중에 계산
            "total_commission": sum(float(t.get("commission", 0) or 0) for t in trades),
            "total_tax": 0.0,  # 세금 계산 필요
            "symbols_count": len(set(t.get("symbol", "") for t in trades if t.get("symbol", ""))),
            "symbols_list": json.dumps(sorted(set(t.get("symbol", "") for t in trades if t.get("symbol", "")))),
            "cycle_trade_count": len(trades),
            "data_source": "auto",
            "raw_data_count": len(trades),
        }
        
        # 수익률 계산
        if summary["total_buy_amount"] > 0:
            summary["realized_profit_rate"] = (summary["realized_profit"] / summary["total_buy_amount"]) * 100
        
        return summary
    except Exception as e:
        _log("error", f"Failed to generate daily summary for {trade_date}: {e}")
        return None


def archive_old_trade_logs(days_to_keep=30):
    """
    지정된 기간보다 오래된 거래 로그를 삭제한다.
    
    Args:
        days_to_keep: 유지할 일수 (기본값: 30일)
    
    Returns:
        삭제된 레코드 수
    """
    try:
        trading = wiz.model("portal/trading/trading")
        trade_log_db = trading.db("trade_log")
        
        cutoff_date = (_TIME.now() - datetime.timedelta(days=days_to_keep)).replace(hour=0, minute=0, second=0, microsecond=0)
        
        # 해당 날짜 이전의 거래 로그 조회
        old_logs = trade_log_db.rows() or []
        old_logs = [log for log in old_logs if (log.get("created", _TIME.now()) < cutoff_date)]
        
        deleted_count = 0
        for log in old_logs:
            try:
                trade_log_db.delete(id=log.get("id"))
                deleted_count += 1
            except Exception as e:
                _log("warn", f"Failed to delete trade_log {log.get('id')}: {e}")
        
        _log("info", f"Archived {deleted_count} old trade logs (older than {cutoff_date})")
        return deleted_count
    except Exception as e:
        _log("error", f"Failed to archive old trade logs: {e}")
        return 0


def cleanup_old_simulations(days_to_keep=90):
    """
    오래된 시뮬레이션 기록을 정리한다.
    - simulation_run: 결과 요약만 유지
    - simulation_trade: 모두 삭제 (용량 절약)
    
    Args:
        days_to_keep: 유지할 일수 (기본값: 90일)
    
    Returns:
        (삭제된 simulation_run 수, 삭제된 simulation_trade 수)
    """
    try:
        trading = wiz.model("portal/trading/trading")
        sim_run_db = trading.db("simulation_run")
        sim_trade_db = trading.db("simulation_trade")
        
        cutoff_date = (_TIME.now() - datetime.timedelta(days=days_to_keep)).replace(hour=0, minute=0, second=0, microsecond=0)
        
        # simulation_trade 모두 삭제 (재현 불필요, 결과만 유지)
        all_sim_trades = sim_trade_db.rows() or []
        deleted_trades = 0
        for trade in all_sim_trades:
            try:
                sim_trade_db.delete(id=trade.get("id"))
                deleted_trades += 1
            except Exception:
                pass
        
        # 오래된 simulation_run 삭제
        all_sim_runs = sim_run_db.rows() or []
        old_runs = [r for r in all_sim_runs if (r.get("created", _TIME.now()) < cutoff_date)]
        
        deleted_runs = 0
        for run in old_runs:
            try:
                sim_run_db.delete(id=run.get("id"))
                deleted_runs += 1
            except Exception:
                pass
        
        _log("info", f"Cleanup simulations: deleted {deleted_runs} old runs, {deleted_trades} trades")
        return (deleted_runs, deleted_trades)
    except Exception as e:
        _log("error", f"Failed to cleanup simulations: {e}")
        return (0, 0)


def remove_incomplete_trade_entries():
    """
    완료되지 않은 거래 데이터를 정리한다.
    - status가 PENDING인 이전 데이터
    - 연결이 끊긴 cycle_trade
    
    Returns:
        삭제된 레코드 수
    """
    try:
        trading = wiz.model("portal/trading/trading")
        cycle_trade_db = trading.db("cycle_trade")
        
        # PENDING 상태로 7일 이상인 거래 삭제
        cutoff_date = (_TIME.now() - datetime.timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
        
        pending_trades = cycle_trade_db.rows() or []
        pending_trades = [t for t in pending_trades 
                         if t.get("status", "") == "PENDING" and 
                         (t.get("created", _TIME.now()) < cutoff_date)]
        
        deleted_count = 0
        for trade in pending_trades:
            try:
                cycle_trade_db.delete(id=trade.get("id"))
                deleted_count += 1
            except Exception:
                pass
        
        _log("info", f"Removed {deleted_count} incomplete trade entries")
        return deleted_count
    except Exception as e:
        _log("error", f"Failed to remove incomplete trades: {e}")
        return 0


def rebuild_daily_summaries(from_date=None, to_date=None):
    """
    지정된 기간의 일일 거래 요약을 (re)생성한다.
    
    Args:
        from_date: 시작 날짜 ('YYYY-MM-DD') - None이면 최근 30일
        to_date: 종료 날짜 ('YYYY-MM-DD') - None이면 오늘
    
    Returns:
        생성/업데이트된 요약 수
    """
    try:
        trading = wiz.model("portal/trading/trading")
        summary_db = trading.db("daily_trade_summary")
        
        if to_date is None:
            to_date = _TIME.today()
        
        if from_date is None:
            from_date = (_TIME.now() - datetime.timedelta(days=30)).strftime("%Y-%m-%d")
        
        # 날짜 범위 생성
        start_dt = datetime.datetime.strptime(from_date, "%Y-%m-%d")
        end_dt = datetime.datetime.strptime(to_date, "%Y-%m-%d")
        
        count = 0
        current_dt = start_dt
        
        while current_dt <= end_dt:
            date_str = current_dt.strftime("%Y-%m-%d")
            
            # 요약 생성
            summary = generate_daily_trade_summary(date_str)
            
            if summary:
                try:
                    # 기존이 있으면 업데이트
                    existing = summary_db.get(trade_date=date_str)
                    if existing:
                        summary_db.update(summary, trade_date=date_str)
                    else:
                        summary["id"] = f"daily_{date_str}_{int(_TIME.now().timestamp())}"
                        summary_db.insert(summary)
                    count += 1
                except Exception as e:
                    _log("warn", f"Failed to save summary for {date_str}: {e}")
            
            current_dt += datetime.timedelta(days=1)
        
        _log("info", f"Rebuilt {count} daily trade summaries from {from_date} to {to_date}")
        return count
    except Exception as e:
        _log("error", f"Failed to rebuild daily summaries: {e}")
        return 0


def database_maintenance():
    """
    전체 데이터베이스 유지보수 작업 수행
    """
    _log("info", "Starting database maintenance...")
    
    # 1. 불완전한 거래 제거
    removed_incomplete = remove_incomplete_trade_entries()
    
    # 2. 오래된 거래 로그 아카이브 (30일 이상)
    archived_logs = archive_old_trade_logs(days_to_keep=30)
    
    # 3. 오래된 시뮬레이션 정리 (90일 이상 simulation_run, 모든 simulation_trade)
    cleaned_runs, cleaned_trades = cleanup_old_simulations(days_to_keep=90)
    
    # 4. 최근 30일 일일 요약 재생성
    built_summaries = rebuild_daily_summaries(
        from_date=(_TIME.now() - datetime.timedelta(days=30)).strftime("%Y-%m-%d"),
        to_date=_TIME.today()
    )
    
    summary = {
        "removed_incomplete_trades": removed_incomplete,
        "archived_trade_logs": archived_logs,
        "cleaned_simulation_runs": cleaned_runs,
        "cleaned_simulation_trades": cleaned_trades,
        "built_daily_summaries": built_summaries,
    }
    
    _log("info", f"Database maintenance completed: {summary}")
    return summary


def _log(level, message):
    """로깅 헬퍼"""
    try:
        logger = wiz.logger("database", "maintenance")
        getattr(logger, level)(message)
    except Exception:
        pass
