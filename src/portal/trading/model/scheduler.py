"""
데이터베이스 자동 정리 스케줄러
매일 밤 오후 11시에 정리 작업 수행
"""

import datetime
import time

_TIME = wiz.model("portal/trading/kst")


def _trading():
    return wiz.model("portal/trading/trading")


def _load_last_run():
    try:
        trading = _trading()
        value = str(trading.get_config("maintenance_last_run_at", "") or "").strip()
        if value == "":
            return None
        return _TIME.parse(value)
    except Exception:
        return None


def _save_last_run(dt):
    try:
        trading = _trading()
        trading.set_config("maintenance_last_run_at", _TIME.isoformat(dt, with_offset=True), description="Last trading maintenance run timestamp")
        trading.set_config("maintenance_last_run_date", dt.strftime("%Y-%m-%d"), description="Last trading maintenance run date")
    except Exception:
        pass

class MaintenanceScheduler:
    """데이터베이스 유지보수 작업을 자동으로 수행"""
    
    def __init__(self):
        self.last_run = _load_last_run()
        self.run_hour = 23  # 오후 11시
        self.run_minute = 0
    
    def should_run(self):
        """현재 시간에 작업을 실행할지 결정"""
        now = _TIME.now()

        scheduled_today = now.replace(hour=self.run_hour, minute=self.run_minute, second=0, microsecond=0)
        target_date = now.date() if now >= scheduled_today else (now - datetime.timedelta(days=1)).date()
        if self.last_run is not None and self.last_run.date() >= target_date:
            return False
        return True
    
    def run(self):
        """유지보수 작업 실행"""
        try:
            trading = wiz.model("portal/trading/trading")
            maintenance = trading.model("maintenance")
            
            result = maintenance.database_maintenance()
            self.last_run = _TIME.now()
            _save_last_run(self.last_run)
            
            return result
        except Exception as e:
            _log("error", f"Maintenance scheduler failed: {e}")
            return None


# 전역 스케줄러 인스턴스
_scheduler = MaintenanceScheduler()


def check_and_run_maintenance():
    """애플리케이션 시작 또는 정기적인 체크 시 호출"""
    if _scheduler.should_run():
        _log("info", "Running scheduled maintenance...")
        return _scheduler.run()
    return None


def _log(level, message):
    """로깅 헬퍼"""
    try:
        logger = wiz.logger("database", "scheduler")
        getattr(logger, level)(message)
    except Exception:
        pass


Model = _scheduler
