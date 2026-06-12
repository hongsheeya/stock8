# =============================================================================
# Domestic Daytrade Research/Backtest Struct
# =============================================================================
import datetime
import itertools
import json
import math
import subprocess
import sys
import time as _time

class Daytrade:
    # 클래스 레벨 TTL 캐시: (symbol, period, interval) → (ts, data)
    _DATASET_CACHE: dict = {}
    _DATASET_CACHE_TTL: int = 180
    STRATEGIES = {
        "vrev": {
            "id": "vrev",
            "name": "V-REV 역추세",
            "summary": "전일종가 앵커, VWAP, 거래량 지배력을 이용한 눌림-반등형 전략",
            "entry": [
                "전일종가 대비 1차/2차 눌림 구간에서 분할 진입",
                "VWAP과 거래량 지배력으로 횡보/추세 레짐 구분",
            ],
            "exit": [
                "평단가 잭팟 전량 청산",
                "기준가 회복 방어 청산 및 구조 복구 청산",
            ],
            "live_supported": True,
        },
        "volume_breakout": {
            "id": "volume_breakout",
            "name": "거래량 돌파",
            "summary": "오프닝레인지/직전 고점 돌파와 거래량 급증이 함께 나오는 구간을 추종",
            "entry": [
                "거래량 급증률 임계치 초과",
                "직전 n봉 고점 돌파 + VWAP 상단 유지",
            ],
            "exit": [
                "돌파 실패 재이탈",
                "트레일링/장마감 평탄화",
            ],
            "live_supported": True,
        },
        "us_premarket": {
            "id": "us_premarket",
            "name": "US 프리마켓 갭업 하따",
            "summary": "프리마켓 갭업(+5% 이상) 후 본장 초입 되밀림 구간에서 진입, 3-4% 분할 익절 전략",
            "entry": [
                "프리마켓 +5% 이상 갭업 후 본장 시작 직후 (-3~-10%) 되밀림 진입",
                "5분봉 기준 거래대금 $2M 이상, VWAP 상단 유지 확인",
            ],
            "exit": [
                "1차 +3% 익절 (절반 매도)",
                "2차 진입가 대비 +4~6% 잔량 청산 또는 LOC 마감 청산",
                "고점 대비 -20% 또는 진입가 대비 -8% 손절",
            ],
            "live_supported": True,
            "market": "US",
        },
        "us_breakout": {
            "id": "us_breakout",
            "name": "US 개장 돌파",
            "summary": "장시작 후 30분 내 전고 돌파 + 거래량 3배 이상 시 진입, 목표 +5~10%, 손절 -3~5%",
            "entry": [
                "09:30~10:00 ET 기간 중 전일 고가 돌파",
                "거래량 평소 대비 3배 이상 확인",
                "상승률 +5% 이상 필터",
            ],
            "exit": [
                "1차 +5% 익절 (절반 매도)",
                "2차 +10% 잔량 청산",
                "진입가 대비 -3~5% 손절",
            ],
            "live_supported": True,
            "market": "US",
        },
        "us_pullback": {
            "id": "us_pullback",
            "name": "US 눌림목 반등",
            "summary": "급등 후 첫 눌림목(5분봉 거래량 감소 + 가격 유지) 진입, 추세 추종",
            "entry": [
                "급등(+10% 이상) 후 첫 5분봉 눌림목 진입",
                "거래량 감소 + 가격 VWAP 부근 유지 확인",
                "ET 11:30~14:00 횡보 구간 진입 금지",
            ],
            "exit": [
                "VWAP 하단 이탈 시 즉시 손절",
                "+4% 익절 또는 장 마감 청산",
            ],
            "live_supported": True,
            "market": "US",
        },
        "us_vwap": {
            "id": "us_vwap",
            "name": "US VWAP 밴드",
            "summary": "현재가가 VWAP 위에 있을 때 유지, VWAP 아래 이탈 시 즉시 손절. VWAP 재돌파 시 재진입",
            "entry": [
                "현재가 ≥ VWAP 이고 거래량 평소 대비 2배 이상",
                "상승세 VWAP 재돌파(이전봉 VWAP 하회 → 현재봉 VWAP 상회) 진입",
            ],
            "exit": [
                "현재가 VWAP 아래 이탈 시 즉시 손절",
                "+6% 익절 또는 장 마감 청산",
            ],
            "live_supported": True,
            "market": "US",
        },
        "us_opening_reclaim": {
            "id": "us_opening_reclaim",
            "name": "US 오프닝 리클레임",
            "summary": "개장 초반 흔들림 뒤 오프닝 레인지 상단과 VWAP를 함께 되찾는 순간만 노리는 연구용 전략",
            "entry": [
                "개장 후 15~20분 안에 1차 흔들림이 나온 뒤 재상승",
                "VWAP 회복과 오프닝 상단 회복이 동시에 발생",
                "거래량 재유입과 MACD 양전환 확인",
            ],
            "exit": [
                "VWAP 재이탈 또는 오프닝 저점 붕괴 시 손절",
                "+3~4% 익절 또는 당일 평탄화",
            ],
            "live_supported": False,
            "market": "US",
        },
    }

    DEFAULT_CANDIDATES = [
        {"symbol": "035420", "market": "KS", "name": "NAVER"},
        {"symbol": "005930", "market": "KS", "name": "삼성전자"},
        {"symbol": "000660", "market": "KS", "name": "SK하이닉스"},
        {"symbol": "068270", "market": "KS", "name": "셀트리온"},
        {"symbol": "051910", "market": "KS", "name": "LG화학"},
        {"symbol": "247540", "market": "KQ", "name": "에코프로비엠"},
        {"symbol": "005380", "market": "KS", "name": "현대차"},
        {"symbol": "012330", "market": "KS", "name": "현대모비스"},
        {"symbol": "105560", "market": "KS", "name": "KB금융"},
        {"symbol": "034020", "market": "KS", "name": "두산에너빌리티"},
        {"symbol": "036570", "market": "KS", "name": "엔씨소프트"},
        {"symbol": "329180", "market": "KS", "name": "HD현대중공업"},
        {"symbol": "042660", "market": "KS", "name": "한화오션"},
        {"symbol": "012450", "market": "KS", "name": "한화에어로스페이스"},
        {"symbol": "267260", "market": "KS", "name": "HD현대일렉트릭"},
        {"symbol": "000270", "market": "KS", "name": "기아"},
        {"symbol": "003670", "market": "KS", "name": "포스코퓨처엠"},
        {"symbol": "196170", "market": "KQ", "name": "알테오젠"},
        {"symbol": "091990", "market": "KQ", "name": "셀트리온헬스케어"},
        {"symbol": "086520", "market": "KQ", "name": "에코프로"},
        {"symbol": "228340", "market": "KQ", "name": "레이크머티리얼즈"},
        {"symbol": "277810", "market": "KQ", "name": "레인보우로보틱스"},
        {"symbol": "214150", "market": "KQ", "name": "클래시스"},
        {"symbol": "285130", "market": "KS", "name": "SK케미칼"},
        {"symbol": "348370", "market": "KS", "name": "엔켐"},
        {"symbol": "000100", "market": "KS", "name": "유한양행"},
        {"symbol": "005940", "market": "KS", "name": "NH투자증권"},
        {"symbol": "011780", "market": "KS", "name": "금호석유"},
        {"symbol": "033780", "market": "KS", "name": "KT&G"},
        {"symbol": "047050", "market": "KS", "name": "포스코인터내셔널"},
        {"symbol": "009150", "market": "KS", "name": "삼성전기"},
        {"symbol": "086280", "market": "KS", "name": "현대글로비스"},
        {"symbol": "010140", "market": "KS", "name": "삼성중공업"},
        {"symbol": "028260", "market": "KS", "name": "삼성물산"},
        {"symbol": "030200", "market": "KS", "name": "KT"},
        {"symbol": "017670", "market": "KS", "name": "SK텔레콤"},
        {"symbol": "112610", "market": "KQ", "name": "씨젠"},
        {"symbol": "066970", "market": "KQ", "name": "엘앤에프"},
        {"symbol": "253450", "market": "KQ", "name": "스튜디오드래곤"},
        {"symbol": "035720", "market": "KS", "name": "카카오"},
        {"symbol": "000720", "market": "KS", "name": "현대건설"},
        {"symbol": "015760", "market": "KS", "name": "한국전력"},
        {"symbol": "004020", "market": "KS", "name": "현대제철"},
        {"symbol": "006260", "market": "KS", "name": "LS"},
        {"symbol": "021240", "market": "KS", "name": "코웨이"},
        {"symbol": "004170", "market": "KS", "name": "신세계"},
        {"symbol": "008770", "market": "KS", "name": "호텔신라"},
        {"symbol": "007070", "market": "KS", "name": "GS리테일"},
        {"symbol": "000080", "market": "KS", "name": "하이트진로"},
        {"symbol": "001450", "market": "KS", "name": "현대해상"},
        {"symbol": "005830", "market": "KS", "name": "DB손해보험"},
        {"symbol": "000810", "market": "KS", "name": "삼성화재"},
        {"symbol": "139480", "market": "KS", "name": "이마트"},
    ]

    DEFAULT_PROFILE = {
        "budget_ratio": 1.0,
        "buy_split_ratio": 1.0,
        "buy_trigger_1_pct": 0.0,
        "buy_trigger_2_pct": -0.35,
        "jackpot_take_profit_pct": 1.2,      # 기본 익절 폭을 조금 줄여 체결 빈도를 높임
        "jackpot_soft_exit_guard_ratio": 0.995, # 잭팟 99.5% 근처 전까지는 soft exit보다 잭팟 우선
        "stop_loss_pct": 1.5,                 # 자동 손절: 평단가 -1.5%
        "min_exit_net_profit_krw": 300,       # 미세 익절 방지 기준을 약간 완화
        "min_exit_fee_multiple": 1.5,         # 익절 보류 기준을 조금 완화해 회전율을 높임
        "rsi_exit_overbought": 75,            # RSI 과매수 익절 기준
        "recent_lot_take_profit_pct": 0.6,
        "rescue_take_profit_pct": 0.5,
        "profit_reentry_min_pullback_pct": 0.7,
        "transferred_take_profit_pct": 0.5,
        "dominance_threshold": 0.45,
        "compound_factor": 0.35,
        "ma_fast": 5,
        "ma_slow": 20,
        "ma_trend": 60,
        "rsi_period": 14,
        "rsi_entry": 34,
        "min_live_entry_rsi": 30,
        "vrev_entry_min_rsi": 35,
        "vrev_entry_max_vwap_discount_pct": 0.5,
        "vrev_entry_min_trend_strength_pct": 0.0,
        "vrev_entry_require_ma_support": True,
        "rsi_exit": 64,
        "trend_take_profit_pct": 1.2,
        "trend_stop_loss_pct": 0.8,
        "breakout_volume_ratio": 1.2,
        "breakout_lookback": 20,
        "breakout_take_profit_pct": 1.4,
        "breakout_stop_loss_pct": 0.8,
        "commission_bps": 1.5,
        "sell_tax_bps": 18.0,
        "slippage_bps": 2.5,
        "max_live_day_range_pct": 8.5,
        "max_live_gap_pct": 5.5,
        "max_live_vwap_discount_pct": 0.8,
        "max_order_cooldown_sec": 12,
        "stop_reentry_same_day_block": True,
        "carry_overnight_enabled": True,
        "carry_max_loss_pct": 0.8,
        "carry_min_vwap_ratio": 0.997,
        "carry_min_close_strength_pct": -1.2,
        "overnight_open_grace_minutes": 18,
        "overnight_panic_stop_loss_pct": 3.2,
        "close_liquidity_take_profit_pct": 0.4,
        "vrev_min_trend_alignment_score": -0.18,
        "rsi_reversion_min_trend_alignment_score": -0.10,
        "ma_trend_min_trend_alignment_score": 0.12,
        "volume_breakout_min_trend_alignment_score": 0.08,
        "max_hold_days": 5,               # 국장 장기보유 강제손절: 최대 보유 영업일 수
        "force_cut_loss_pct": 8.0,        # 국장 장기보유 강제손절: 강제 손절 손실률 (%)
    }

    # ─── 미장(US) ────────────────────────────────────────────────────────────
    US_DEFAULT_CANDIDATES = [
        {"symbol": "TQQQ", "market": "US", "name": "ProShares UltraPro QQQ", "exchange": "NASD"},
        {"symbol": "SOXL", "market": "US", "name": "Direxion Daily Semi 3x", "exchange": "NASD"},
        {"symbol": "SPXL", "market": "US", "name": "Direxion Daily S&P 500 Bull 3x", "exchange": "NYSE"},
        {"symbol": "UPRO", "market": "US", "name": "ProShares UltraPro S&P500", "exchange": "NYSE"},
        {"symbol": "NVDA", "market": "US", "name": "NVIDIA", "exchange": "NASD"},
        {"symbol": "AVGO", "market": "US", "name": "Broadcom", "exchange": "NASD"},
        {"symbol": "TSLA", "market": "US", "name": "Tesla", "exchange": "NASD"},
        {"symbol": "AMD",  "market": "US", "name": "AMD", "exchange": "NASD"},
        {"symbol": "MU",   "market": "US", "name": "Micron Technology", "exchange": "NASD"},
        {"symbol": "ARM",  "market": "US", "name": "Arm Holdings", "exchange": "NASD"},
        {"symbol": "TSM",  "market": "US", "name": "Taiwan Semiconductor ADR", "exchange": "NYSE"},
        {"symbol": "META", "market": "US", "name": "Meta Platforms", "exchange": "NASD"},
        {"symbol": "AMZN", "market": "US", "name": "Amazon", "exchange": "NASD"},
        {"symbol": "GOOGL","market": "US", "name": "Alphabet (GOOGL)", "exchange": "NASD"},
        {"symbol": "MSFT", "market": "US", "name": "Microsoft", "exchange": "NASD"},
        {"symbol": "AAPL", "market": "US", "name": "Apple", "exchange": "NASD"},
        {"symbol": "NFLX", "market": "US", "name": "Netflix", "exchange": "NASD"},
        {"symbol": "SMCI", "market": "US", "name": "Super Micro Computer", "exchange": "NASD"},
        {"symbol": "PLTR", "market": "US", "name": "Palantir", "exchange": "NASD"},
        {"symbol": "MSTR", "market": "US", "name": "MicroStrategy", "exchange": "NASD"},
        {"symbol": "COIN", "market": "US", "name": "Coinbase", "exchange": "NASD"},
        {"symbol": "CRWD", "market": "US", "name": "CrowdStrike", "exchange": "NASD"},
        {"symbol": "PANW", "market": "US", "name": "Palo Alto Networks", "exchange": "NASD"},
        {"symbol": "APP",  "market": "US", "name": "AppLovin", "exchange": "NASD"},
        {"symbol": "NET",  "market": "US", "name": "Cloudflare", "exchange": "NYSE"},
        {"symbol": "SNOW", "market": "US", "name": "Snowflake", "exchange": "NYSE"},
        {"symbol": "MELI", "market": "US", "name": "MercadoLibre", "exchange": "NASD"},
        {"symbol": "IONQ", "market": "US", "name": "IonQ", "exchange": "NASD"},
        {"symbol": "RKLB", "market": "US", "name": "Rocket Lab", "exchange": "NASD"},
        {"symbol": "ASTS", "market": "US", "name": "AST SpaceMobile", "exchange": "NASD"},
        {"symbol": "SERV", "market": "US", "name": "Serve Robotics", "exchange": "NASD"},
        {"symbol": "TEM",  "market": "US", "name": "Tempus AI", "exchange": "NASD"},
        {"symbol": "RIVN", "market": "US", "name": "Rivian", "exchange": "NASD"},
        {"symbol": "HOOD", "market": "US", "name": "Robinhood", "exchange": "NASD"},
        {"symbol": "SPY",  "market": "US", "name": "SPDR S&P 500 ETF", "exchange": "NYSE"},
        {"symbol": "QQQ",  "market": "US", "name": "Invesco QQQ ETF", "exchange": "NASD"},
        {"symbol": "IWM",  "market": "US", "name": "iShares Russell 2000 ETF", "exchange": "NYSE"},
    ]

    # KIS 기준 미국 주식 수수료: 매수 0.25% + 매도 0.25% + SEC fee $8/million(매도)
    US_DEFAULT_PROFILE = {
        "budget_ratio": 1.0,
        "buy_split_ratio": 0.5,             # 포지션 절반씩 분할 매도
        "jackpot_take_profit_pct": 3.0,     # 1차 익절: +3%
        "jackpot2_take_profit_pct": 5.0,    # 2차 익절: +5%
        "stop_loss_pct": 8.0,               # 진입가 대비 -8% 손절
        "high_stop_pct": 20.0,              # 고점 대비 -20% 손절
        "premarket_gap_min_pct": 5.0,       # 진입 조건: 프리마켓 갭 최소 +5%
        "entry_drawdown_min_pct": 3.0,      # 진입 조건: 갭 고점 대비 되밀림 최소 3%
        "entry_drawdown_max_pct": 10.0,     # 진입 조건: 갭 고점 대비 되밀림 최대 10%
        "min_volume_usd": 2000000,          # 진입 조건: 거래대금 최소 $2M
        "commission_bps": 25.0,             # KIS 매수 수수료 0.25%
        "sell_commission_bps": 25.0,        # KIS 매도 수수료 0.25%
        "sec_fee_per_million_usd": 8.0,     # SEC fee: $8 per $1M 매도금액
        "slippage_bps": 3.0,
        "max_order_cooldown_sec": 30,
        "max_live_day_range_pct": 30.0,     # 미장은 변동폭 제한 완화
        "max_live_gap_pct": 50.0,           # 커버리지 갭 허용 완화
        "breakout_volume_ratio": 3.0,       # us_breakout: 거래량 기준 배율
        "breakout_lookback": 20,
        "min_change_pct": 5.0,              # us_breakout: 최소 상승률 %
        "min_prior_surge_pct": 10.0,        # us_pullback: 선행 급등 최소 %
        "rsi_period": 14,
        "ma_fast": 5,
        "ma_slow": 20,
        "shadow_mode": False,                # 기본값: shadow mode (실제 주문 X)
    }
    # ─────────────────────────────────────────────────────────────────────────

    MIN_SEED = 100000
    DEFAULT_SEED = 5000000

    def __init__(self, struct):
        self.struct = struct

    def _now(self):
        return wiz.model("portal/trading/kst").now()

    def _config(self, key, default=None):
        """매 요청 DB 쿼리 대신 Struct 싱글톤 캐시에서 읽음 — 연결 고갈 방지"""
        return self.struct.get_config(key, default)

    def _normalized_seed(self, seed=0, default=None):
        base_default = self.DEFAULT_SEED if default is None else default
        value = self._safe_float(seed, base_default)
        if value <= 0:
            value = base_default
        return max(float(self.MIN_SEED), value)

    def defaults(self):
        seed = self._normalized_seed(self._config("daytrade_default_seed", str(self.DEFAULT_SEED)), self.DEFAULT_SEED)
        return {
            "symbol": self._config("daytrade_default_symbol", "035420"),
            "market": self._config("daytrade_default_market", "KS"),
            "strategy": self._normalize_strategy(self._config("daytrade_default_strategy", "vrev")),
            "period": "5d",
            "interval": "1m",
            "seed": seed,
        }

    def us_defaults(self):
        seed = self._normalized_seed(self._config("daytrade_us_default_seed", str(self.DEFAULT_SEED)), self.DEFAULT_SEED)
        return {
            "symbol": self._config("daytrade_us_default_symbol", "TQQQ"),
            "market": "US",
            "strategy": self._normalize_strategy(self._config("daytrade_us_default_strategy", "us_premarket")),
            "period": "10d",
            "interval": "5m",
            "seed": seed,
        }

    def recommendation_training_defaults(self):
        return {
            "period": str(self._config("daytrade_training_period", "10d") or "10d"),
            "interval": str(self._config("daytrade_training_interval", "5m") or "5m"),
            "min_session_count": max(3, self._safe_int(self._config("daytrade_training_min_sessions", "6"), 6)),
            "min_validation_sessions": max(2, self._safe_int(self._config("daytrade_training_min_validation_sessions", "3"), 3)),
            "min_success_rate": max(0.0, self._safe_float(self._config("daytrade_training_min_success_rate", "35"), 35)),
            "min_avg_total_return": self._safe_float(self._config("daytrade_training_min_avg_total_return", "0"), 0),
        }

    def strategy_options(self):
        return [dict(item) for item in self.STRATEGIES.values()]

    def _normalize_strategy(self, strategy_id):
        strategy_id = str(strategy_id or "vrev").strip().lower()
        if strategy_id not in self.STRATEGIES:
            return "vrev"
        return strategy_id

    def strategy_spec(self, strategy_id="vrev"):
        strategy_id = self._normalize_strategy(strategy_id)
        return dict(self.STRATEGIES.get(strategy_id, self.STRATEGIES["vrev"]))

    def _learned_candidate_universe(self, market="KS"):
        market_key = str(market or "KS").upper()
        if market_key == "US":
            return []
        book = self._load_profile_book(market=market_key)
        if isinstance(book, dict) is False or len(book) == 0:
            return []
        min_validation_return = self._safe_float(self._config("daytrade_candidate_learned_min_validation_return_pct", "2.0"), 2.0)
        min_validation_avg_profit = max(0.0, self._safe_float(self._config("daytrade_candidate_learned_min_validation_avg_profit_krw", "20000"), 20000))
        min_validation_win_rate = max(0.0, self._safe_float(self._config("daytrade_candidate_learned_min_validation_win_rate", "50"), 50))
        min_validation_profit_factor = max(0.0, self._safe_float(self._config("daytrade_candidate_learned_min_validation_profit_factor", "1.25"), 1.25))
        max_negative_fold_ratio = min(1.0, max(0.0, self._safe_float(self._config("daytrade_candidate_learned_max_negative_fold_ratio", "0.34"), 0.34)))
        max_return_swing = max(0.0, self._safe_float(self._config("daytrade_candidate_learned_max_return_swing_pct", "8.0"), 8.0))
        limit = max(0, self._safe_int(self._config("daytrade_candidate_learned_limit", "12"), 12))
        if limit <= 0:
            return []

        selected = {}
        for entry in book.values():
            if isinstance(entry, dict) is False:
                continue
            symbol = str(entry.get("symbol", "") or "").strip().upper()
            item_market = str(entry.get("market", market_key) or market_key).upper()
            if symbol == "" or item_market != market_key:
                continue
            validation = entry.get("validation", {}) or {}
            validation_summary = validation.get("validation", {}) or {}
            graph_validation = validation.get("graph_validation", {}) or self._graph_validation_metrics(validation.get("walk_forward", []) or [], validation_summary)
            validation_return = self._safe_float(validation_summary.get("total_return", 0), 0)
            validation_avg_profit = self._safe_float(validation_summary.get("avg_profit", 0), 0)
            validation_win_rate = self._safe_float(validation_summary.get("win_rate", 0), 0)
            validation_profit_factor = self._safe_float(validation_summary.get("profit_factor", 0), 0)
            negative_fold_ratio = self._safe_float(graph_validation.get("negative_fold_ratio", 0), 0)
            return_swing = self._safe_float(graph_validation.get("return_swing_pct", 0), 0)
            if validation_return < min_validation_return:
                continue
            if validation_avg_profit < min_validation_avg_profit:
                continue
            if validation_win_rate < min_validation_win_rate:
                continue
            if validation_profit_factor < min_validation_profit_factor:
                continue
            if negative_fold_ratio > max_negative_fold_ratio:
                continue
            if return_swing > max_return_swing:
                continue
            score = (
                validation_avg_profit
                + (validation_return * 10000.0)
                + (self._safe_float(graph_validation.get("stability_score", 0), 0) * 2000.0)
            )
            candidate = {
                "symbol": symbol,
                "market": item_market,
                "name": entry.get("name") or self._resolve_symbol_name(symbol),
                "source": "profile_book",
                "strategy_hint": entry.get("strategy_id", ""),
            }
            current = selected.get(symbol)
            if current is None or score > current.get("_score", -999999999):
                candidate["_score"] = score
                selected[symbol] = candidate

        rows = list(selected.values())
        rows.sort(key=lambda x: x.get("_score", 0), reverse=True)
        result = []
        for row in rows[:limit]:
            item = dict(row)
            item.pop("_score", None)
            result.append(item)
        return result

    def candidate_universe(self, market="KS"):
        if str(market).upper() == "US":
            return self.us_candidate_universe()
        rows = [dict(item) for item in self.DEFAULT_CANDIDATES]
        seen = set(str(item.get("symbol", "") or "").strip().upper() for item in rows)
        for item in self._learned_candidate_universe(market=market):
            symbol = str(item.get("symbol", "") or "").strip().upper()
            if symbol == "" or symbol in seen:
                continue
            rows.append(dict(item))
            seen.add(symbol)
        return rows

    def us_candidate_universe(self):
        return [dict(item) for item in self.US_DEFAULT_CANDIDATES]

    def us_candidate_universe_policy(self):
        return {
            "mode": "curated_whitelist",
            "summary": "실시간 계산 비용과 오탐을 줄이기 위해 전체 미국시장 스캐너 대신 유동성·변동성 상위의 선별 화이트리스트를 기본 유니버스로 사용합니다.",
            "selection_rules": [
                "KIS 실시간 조회가 안정적인 대형주/레버리지 ETF/반도체·AI 리더 중심으로 우선 선별",
                "검증 수익률·손익비·유동성·과최적화·추세정합 품질 게이트를 통과한 종목만 실전 후보로 채택",
                "전체 시장 급등주 스캔은 아직 자동화되지 않아 직접 검색으로 보완",
            ],
            "allow_manual_search": True,
            "candidate_count": len(self.US_DEFAULT_CANDIDATES),
        }

    def us_strategy_options(self):
        return [dict(v) for k, v in self.STRATEGIES.items() if v.get("market") == "US"]

    def us_profile(self):
        return self._default_profile_for_market("US")

    def _volatility_from_sessions(self, sessions):
        if not sessions:
            return {
                "avg_day_range_pct": 0.0,
                "avg_intraday_move_pct": 0.0,
                "avg_turnover_krw": 0.0,
                "liquidity_score": 0.0,
                "tradability_score": 0.0,
                "fee_buffer_ok": False,
            }
        day_ranges = []
        intraday_moves = []
        turnovers = []
        for session in sessions:
            bars = session.get("bars", [])
            anchor = self._safe_float(session.get("prev_close", 0), 0)
            if len(bars) == 0 or anchor <= 0:
                continue
            highs = [self._safe_float(x.get("high", 0), 0) for x in bars]
            lows = [self._safe_float(x.get("low", 0), 0) for x in bars]
            closes = [self._safe_float(x.get("close", 0), 0) for x in bars]
            vols = [self._safe_int(x.get("volume", 0), 0) for x in bars]
            day_high = max(highs) if highs else 0
            day_low = min(lows) if lows else 0
            if day_high > 0 and day_low > 0:
                day_ranges.append((day_high - day_low) / anchor * 100)
            move_sum = 0.0
            for idx in range(1, len(closes)):
                prev_price = closes[idx - 1]
                curr_price = closes[idx]
                if prev_price > 0:
                    move_sum += abs(curr_price - prev_price) / prev_price * 100
            intraday_moves.append(move_sum)
            turnover = 0.0
            for idx, close_price in enumerate(closes):
                volume = vols[idx] if idx < len(vols) else 0
                turnover += close_price * volume
            turnovers.append(turnover)
        avg_day_range_pct = round(sum(day_ranges) / len(day_ranges), 4) if day_ranges else 0.0
        avg_intraday_move_pct = round(sum(intraday_moves) / len(intraday_moves), 4) if intraday_moves else 0.0
        avg_turnover_krw = round(sum(turnovers) / len(turnovers), 2) if turnovers else 0.0
        liquidity_score = round(max(0.0, min(6.0, math.log10(avg_turnover_krw + 1) - 7.0)), 4) if avg_turnover_krw > 0 else 0.0
        tradability_score = round((avg_day_range_pct * 1.1) + (avg_intraday_move_pct * 0.25) + (liquidity_score * 1.5), 4)
        fee_buffer_ok = avg_day_range_pct >= 1.2
        return {
            "avg_day_range_pct": avg_day_range_pct,
            "avg_intraday_move_pct": avg_intraday_move_pct,
            "avg_turnover_krw": avg_turnover_krw,
            "liquidity_score": liquidity_score,
            "tradability_score": tradability_score,
            "fee_buffer_ok": fee_buffer_ok,
        }

    def volatility_profile(self, symbol, market="KS"):
        sessions = self._prepare_dataset(symbol, market=market, period="5d", interval="5m")
        result = self._volatility_from_sessions(sessions)
        # 마지막 실제 가격 추가 (auto_candidates 예산 필터용, 이미 캐시된 데이터 사용)
        last_price = 0.0
        try:
            if sessions and sessions[-1].get("bars"):
                last_price = self._safe_float(sessions[-1]["bars"][-1].get("close", 0), 0)
        except Exception:
            pass
        result["last_price"] = last_price
        return result

    def _resolve_symbol_name(self, symbol):
        symbol = str(symbol or "").strip()
        if not symbol:
            return ""
        for item in self.DEFAULT_CANDIDATES:
            if item.get("symbol") == symbol:
                return item.get("name", "")
        try:
            from pykrx import stock
            name = stock.get_market_ticker_name(symbol)
            if name and name != symbol:
                return name
        except Exception:
            pass
        return ""

    def symbol_name(self, symbol):
        return self._resolve_symbol_name(symbol)

    def _infer_market(self, symbol, preferred="KS"):
        preferred = str(preferred or "KS").upper()
        candidates = [preferred]
        for market in ("KS", "KQ"):
            if market not in candidates:
                candidates.append(market)
        for market in candidates:
            try:
                self._prepare_dataset(symbol, market=market, period="5d", interval="5m")
                return market
            except Exception:
                pass
        return preferred

    def search_symbols(self, query="", limit=12, market=""):
        query = str(query or "").strip()
        limit = max(self._safe_int(limit, 12), 1)
        market = str(market or "").upper()
        if market == "US":
            universe = self.us_candidate_universe()
        else:
            universe = self.candidate_universe()
        if query == "":
            return universe[:limit]
        upper_query = query.upper()
        results = []
        seen = set()
        for item in universe:
            haystack = f"{item.get('symbol', '')} {item.get('name', '')} {item.get('market', '')}".upper()
            if upper_query in haystack:
                results.append(item)
                seen.add(item.get("symbol"))
        if market != "US":
            digits = "".join([ch for ch in query if ch.isdigit()])
            if len(digits) == 6 and digits not in seen:
                name = self._resolve_symbol_name(digits)
                if name:
                    results.insert(0, {"symbol": digits, "market": self._infer_market(digits), "name": name})
        return results[:limit]

    # =========================================================================
    # Internal
    # =========================================================================

    def _fs(self):
        return wiz.project.fs()

    def _docs_path(self, name=""):
        base = "docs/daytrade"
        return f"{base}/{name}" if name else base

    def _data_path(self, name=""):
        base = "data/daytrade"
        return f"{base}/{name}" if name else base

    def _market_scope(self, market="KS"):
        return "us" if str(market or "KS").upper() == "US" else "ks"

    def _market_docs_path(self, name="", market="KS"):
        base = self._docs_path(self._market_scope(market))
        return f"{base}/{name}" if name else base

    def _market_data_path(self, name="", market="KS"):
        base = self._data_path(self._market_scope(market))
        return f"{base}/{name}" if name else base

    def _default_profile_for_market(self, market="KS", strategy_id=""):
        is_us = str(market or "KS").upper() == "US" or str(strategy_id or "").startswith("us_")
        return dict(self.US_DEFAULT_PROFILE if is_us else self.DEFAULT_PROFILE)

    def _profile_book_path(self, market="KS"):
        return self._market_data_path("profile_book.json", market=market)

    def _load_profile_book(self, market="KS"):
        fs = self._fs()
        path = self._profile_book_path(market=market)
        if fs.exists(path) == False:
            return {}
        data = fs.read.json(path, default={})
        return data if isinstance(data, dict) else {}

    def _save_profile_book_entries(self, entries, market="KS"):
        if not isinstance(entries, dict) or len(entries) == 0:
            return
        fs = self._fs()
        fs.makedirs(self._market_data_path(market=market))
        book = self._load_profile_book(market=market)
        book.update(entries)
        fs.write.json(self._profile_book_path(market=market), book)

    def latest_profile(self, symbol, strategy_id="", market="KS"):
        symbol = str(symbol or "").strip().upper()
        strategy_id = self._normalize_strategy(strategy_id)
        if symbol == "":
            return None
        key = f"{symbol}:{strategy_id}"
        book = self._load_profile_book(market=market)
        entry = book.get(key, {}) if isinstance(book, dict) else {}
        if not isinstance(entry, dict):
            return None
        profile = entry.get("profile", {})
        return dict(profile) if isinstance(profile, dict) else None

    def _safe_float(self, value, default=0.0):
        try:
            value = float(value)
            if math.isnan(value) or math.isinf(value):
                return default
            return value
        except Exception:
            return default

    def _safe_int(self, value, default=0):
        try:
            return int(value)
        except Exception:
            return default

    def _normalize_symbol(self, symbol, market="KS"):
        symbol = str(symbol or "").strip().upper()
        market = str(market or "KS").strip().upper()
        if "." in symbol:
            return symbol
        if symbol.isdigit() and len(symbol) == 6:
            return f"{symbol}.{market}"
        return symbol

    def read_docs(self, market="KS"):
        fs = self._fs()
        report_path = self._market_docs_path("optimization-report.md", market=market)
        if fs.exists(report_path) == False:
            report_path = self._docs_path("optimization-report.md")
        return {
            "architecture": fs.read(self._docs_path("architecture.md")) if fs.exists(self._docs_path("architecture.md")) else "",
            "vrev": fs.read(self._docs_path("vrev-model.md")) if fs.exists(self._docs_path("vrev-model.md")) else "",
            "strategies": fs.read(self._docs_path("strategy-playbook.md")) if fs.exists(self._docs_path("strategy-playbook.md")) else "",
            "live_mechanism": fs.read(self._docs_path("live-trading-mechanism.md")) if fs.exists(self._docs_path("live-trading-mechanism.md")) else "",
            "report": fs.read(report_path) if fs.exists(report_path) else "",
        }

    def latest_training(self, market="KS"):
        fs = self._fs()
        scoped_path = self._market_data_path("latest_training.json", market=market)
        legacy_path = self._data_path("latest_training.json")
        for path in [scoped_path, legacy_path]:
            if fs.exists(path) == False:
                continue
            data = fs.read.json(path, default=None)
            if not isinstance(data, dict):
                continue
            data_market = str(data.get("market", market) or market).upper()
            if data_market == str(market or "KS").upper():
                return data
        return None

    def _recommendation_price_cap(self, seed=0):
        requested_seed = self._safe_float(seed, 0)
        if requested_seed <= 0:
            return 0.0
        return round(max(0.0, requested_seed * 0.985), 2)

    def _recommendation_cache_key(self, seed=0, strategy_id="", price_cap=0, market="KS"):
        requested_seed = round(max(0.0, self._safe_float(seed, 0)), 2)
        effective_price_cap = round(max(0.0, self._safe_float(price_cap, self._recommendation_price_cap(requested_seed))), 2)
        training_defaults = self.recommendation_training_defaults()
        market_scope = str(market or "KS").upper()
        return {
            "selection_version": "2026-05-08.2",
            "strategy_catalog": "|".join(sorted(list(self.STRATEGIES.keys()))),
            "requested_seed": requested_seed,
            "market_scope": market_scope,
            "strategy_scope": self._normalize_strategy(strategy_id) if strategy_id else "all",
            "price_cap_krw": effective_price_cap,
            "training_period": training_defaults.get("period", "10d"),
            "training_interval": training_defaults.get("interval", "5m"),
            "min_session_count": training_defaults.get("min_session_count", 6),
            "min_validation_sessions": training_defaults.get("min_validation_sessions", 3),
        }

    def _recommendation_cache_matches(self, cached_key, expected_key, seed=0, strategy_id="", price_cap=0, market="KS"):
        if isinstance(cached_key, dict) is False:
            return False
        if str(cached_key.get("selection_version", "")) != str(expected_key.get("selection_version", "")):
            return False
        if str(cached_key.get("strategy_catalog", "")) != str(expected_key.get("strategy_catalog", "")):
            return False
        if str(cached_key.get("training_period", "")) != str(expected_key.get("training_period", "")):
            return False
        if str(cached_key.get("training_interval", "")) != str(expected_key.get("training_interval", "")):
            return False
        if self._safe_int(cached_key.get("min_session_count", 0), 0) != self._safe_int(expected_key.get("min_session_count", 0), 0):
            return False
        if self._safe_int(cached_key.get("min_validation_sessions", 0), 0) != self._safe_int(expected_key.get("min_validation_sessions", 0), 0):
            return False

        market_scope = str(market or "").upper()
        if market_scope:
            if str(cached_key.get("market_scope", "KS")).upper() != market_scope:
                return False
        if strategy_id:
            if str(cached_key.get("strategy_scope", "all")) != str(expected_key.get("strategy_scope", "all")):
                return False
        if self._safe_float(seed, 0) > 0:
            if round(self._safe_float(cached_key.get("requested_seed", 0), 0), 2) != expected_key.get("requested_seed", 0):
                return False
        if self._safe_float(price_cap, 0) > 0:
            if round(self._safe_float(cached_key.get("price_cap_krw", 0), 0), 2) != expected_key.get("price_cap_krw", 0):
                return False
        return True

    def _recommendation_price_filter(self, recommendation, strategy_id="", price_cap=0, market="KS"):
        if isinstance(recommendation, dict) is False:
            return recommendation

        market_scope = str(market or "KS").upper()
        normalized_strategy = self._normalize_strategy(strategy_id) if strategy_id else ""
        limit_price = self._safe_float(price_cap, 0)

        leaderboard = []
        for row in list(recommendation.get("leaderboard", []) or []):
            row_market = str(row.get("market", market_scope) or market_scope).upper()
            row_strategy = str(row.get("strategy_id", "") or "").strip().lower()
            if row_market != market_scope:
                continue
            if normalized_strategy and row_strategy != normalized_strategy:
                continue
            last_price = self._safe_float(row.get("last_price", 0), 0)
            if market_scope == "KS" and limit_price > 0 and last_price > 0 and last_price > limit_price:
                continue
            leaderboard.append(dict(row))

        if len(leaderboard) == 0:
            return recommendation

        selected_pool = [row for row in leaderboard if row.get("trade_ready")]
        if len(selected_pool) == 0:
            selected_pool = leaderboard
        selected_row = dict(selected_pool[0])

        result = dict(recommendation)
        result["leaderboard"] = leaderboard[:12]
        result["peer_comparison"] = leaderboard[1:6]
        result["cross_validation"] = [row.get("validation", {}) for row in leaderboard[:5]]
        result["selected"] = {
            "symbol": selected_row.get("symbol", ""),
            "market": selected_row.get("market", market_scope),
            "name": selected_row.get("name", ""),
            "strategy_id": selected_row.get("strategy_id", normalized_strategy or self.defaults().get("strategy", "vrev")),
            "strategy_name": selected_row.get("strategy_name", ""),
            "reason": selected_row.get("reason", result.get("selected", {}).get("reason", "")),
        }

        aggregate = dict(result.get("aggregate", {}) or {})
        tested_count = len(leaderboard)
        if tested_count > 0:
            aggregate["tested_count"] = tested_count
            aggregate["success_rate"] = round((len([row for row in leaderboard if self._safe_float(row.get("total_return", 0), 0) > 0]) / tested_count) * 100, 2)
            aggregate["avg_total_return"] = round(sum(self._safe_float(row.get("total_return", 0), 0) for row in leaderboard) / tested_count, 4)
            aggregate["avg_validation_return"] = round(sum(self._safe_float(row.get("validation_return", 0), 0) for row in leaderboard) / tested_count, 4)
            aggregate["avg_win_rate"] = round(sum(self._safe_float(row.get("win_rate", 0), 0) for row in leaderboard) / tested_count, 2)
            aggregate["avg_validation_win_rate"] = round(sum(self._safe_float(row.get("validation_win_rate", 0), 0) for row in leaderboard) / tested_count, 2)
            aggregate["avg_trades"] = round(sum(self._safe_float(row.get("avg_trades", 0), 0) for row in leaderboard) / tested_count, 2)
            aggregate["avg_validation_trades"] = round(sum(self._safe_float(row.get("validation_avg_trades", 0), 0) for row in leaderboard) / tested_count, 2)
            aggregate["avg_score"] = round(sum(self._safe_float(row.get("score", 0), 0) for row in leaderboard) / tested_count, 4)
            aggregate["avg_day_range_pct"] = round(sum(self._safe_float(row.get("avg_day_range_pct", 0), 0) for row in leaderboard) / tested_count, 4)
            aggregate["trade_ready_count"] = len([row for row in leaderboard if row.get("trade_ready")])
            aggregate["strategies_tested"] = sorted(list(set([str(row.get("strategy_id", "") or "") for row in leaderboard])))
        result["aggregate"] = aggregate
        result["quality_guard"] = self._build_quality_guard(leaderboard, self.recommendation_training_defaults(), market=market_scope)
        result["requested_seed"] = round(max(self._safe_float(result.get("requested_seed", 0), 0), self._safe_float(seed, 0)), 2)
        result["price_cap_krw"] = round(limit_price if limit_price > 0 else self._safe_float(result.get("price_cap_krw", 0), 0), 2)
        result["market"] = market_scope
        result["cache_relaxed"] = True
        return result

    def _validate_recommendation_cache(self, data, seed=0, strategy_id="", price_cap=0, market="KS"):
        if not data or not data.get("recommendations"):
            return None
        
        expected_key = self._recommendation_cache_key(seed=seed, strategy_id=strategy_id, price_cap=price_cap, market=market)
        cached_key = data.get("cache_key", {}) if isinstance(data.get("cache_key", {}), dict) else {}
        if self._recommendation_cache_matches(cached_key, expected_key, seed=seed, strategy_id=strategy_id, price_cap=price_cap, market=market) is False:
            return None

        return data

    def latest_recommendation(self, seed=0, strategy_id="", price_cap=0, max_age_sec=0, allow_stale_day=False, market="KS"):
        fs = self._fs()
        paths = [self._market_data_path("recommendation.json", market=market), self._data_path("recommendation.json")]
        for path in paths:
            if fs.exists(path) == False:
                continue
            try:
                data = fs.read.json(path, default=None)
                if data is None:
                    continue
                selected_strategy = str(data.get("selected", {}).get("strategy_id") or "").strip().lower()
                if selected_strategy == "" or selected_strategy not in self.STRATEGIES:
                    continue
                if isinstance(data.get("leaderboard"), list):
                    data["leaderboard"] = [x for x in data.get("leaderboard", []) if str(x.get("strategy_id", "") or "").strip().lower() in self.STRATEGIES]
                if isinstance(data.get("top_candidates"), list):
                    data["top_candidates"] = [x for x in data.get("top_candidates", []) if str(x.get("strategy_id", "") or "").strip().lower() in self.STRATEGIES]
                if isinstance(data.get("peer_comparison"), list):
                    data["peer_comparison"] = [x for x in data.get("peer_comparison", []) if str(x.get("strategy_id", "") or "").strip().lower() in self.STRATEGIES]
                if max_age_sec > 0:
                    generated_at = str(data.get("generated_at", "") or "").strip()
                    if generated_at:
                        try:
                            generated_dt = datetime.datetime.strptime(generated_at, "%Y-%m-%d %H:%M:%S")
                            age_sec = max(0.0, (self._now() - generated_dt).total_seconds())
                            if age_sec > max_age_sec:
                                continue
                        except Exception:
                            pass
                gen = data.get("generated_date", "")
                today = self._now().strftime("%Y-%m-%d")
                if allow_stale_day is False and gen != today:
                    continue
                expected_key = self._recommendation_cache_key(seed=seed, strategy_id=strategy_id, price_cap=price_cap, market=market)
                cached_key = data.get("cache_key", {}) if isinstance(data.get("cache_key", {}), dict) else {}
                if self._recommendation_cache_matches(cached_key, expected_key, seed=seed, strategy_id=strategy_id, price_cap=price_cap, market=market) is False:
                    continue
                return data
            except Exception:
                pass
        return None

    def _save_recommendation(self, data, market="KS"):
        fs = self._fs()
        fs.makedirs(self._market_data_path(market=market))
        data["generated_date"] = self._now().strftime("%Y-%m-%d")
        data["generated_at"] = self._now().strftime("%Y-%m-%d %H:%M:%S")
        fs.write.json(self._market_data_path("recommendation.json", market=market), data)

    def _empty_recommendation(self, cache_key=None, market="KS", reason="추천 가능한 종목이 없습니다."):
        defaults = self.us_defaults() if str(market or "KS").upper() == "US" else self.defaults()
        result = self._fallback_recommendation(
            symbol=defaults.get("symbol", ""),
            market=market,
            seed=defaults.get("seed", self.DEFAULT_SEED),
            strategy_id=defaults.get("strategy", "vrev"),
            reason=reason,
        )
        result["leaderboard"] = []
        result["peer_comparison"] = []
        result["quality_guard"] = {
            "block_new_entries": True,
            "issues": [reason],
        }
        if cache_key is not None:
            result["cache_key"] = cache_key
        return result

    def _build_quality_guard(self, leaderboard, training_defaults, market="KS"):
        if len(leaderboard) == 0:
            return {"block_new_entries": True, "issues": ["학습·검증을 통과한 후보가 없습니다."]}
        selected = leaderboard[0]
        trade_ready_count = len([row for row in leaderboard if row.get("trade_ready")])
        if str(market or "KS").upper() == "US":
            issues = list(selected.get("quality_issues", []) or [])
            if trade_ready_count <= 0 and len(issues) == 0:
                issues.append("검증 수익·견고성 기준을 통과한 미장 전략이 없습니다.")
            return {
                "block_new_entries": trade_ready_count <= 0,
                "issues": issues[:5],
                "trade_ready_count": trade_ready_count,
            }
        issues = list(selected.get("quality_issues", []) or [])
        if trade_ready_count <= 0 and len(issues) == 0:
            issues.append("검증 수익·승률 기준을 통과한 국장 전략이 없습니다.")
        return {
            "block_new_entries": trade_ready_count <= 0,
            "issues": issues[:5],
            "trade_ready_count": trade_ready_count,
        }

    def _fallback_recommendation(self, symbol="", market="KS", seed=5000000, strategy_id="", reason="", errors=None):
        fallback_market = str(market or "KS" or "KS").upper()
        defaults = self.us_defaults() if fallback_market == "US" else self.defaults()
        default_symbol = "TQQQ" if fallback_market == "US" else "035420"
        default_strategy = "us_premarket" if fallback_market == "US" else "vrev"
        fallback_symbol = str(symbol or defaults.get("symbol", default_symbol)).strip() or default_symbol
        fallback_strategy = self._normalize_strategy(strategy_id or defaults.get("strategy", default_strategy))
        fallback_name = self._resolve_symbol_name(fallback_symbol)
        fallback_reason = str(reason or "학습 후보가 모두 실패하여 기본 종목으로 유지합니다.")
        cached = self.latest_recommendation(market=fallback_market)
        leaderboard = list(errors or [])[:10]

        if isinstance(cached, dict) and cached.get("selected"):
            result = dict(cached)
            selected = dict(result.get("selected", {}))
            selected["reason"] = fallback_reason
            result["selected"] = selected
            result["training_skipped"] = True
            result["fallback_reason"] = fallback_reason
            if leaderboard:
                result["leaderboard"] = list(result.get("leaderboard", []))[:10] + leaderboard[:5]
            return result

        return {
            "selected": {
                "symbol": fallback_symbol,
                "market": fallback_market,
                "name": fallback_name,
                "strategy_id": fallback_strategy,
                "strategy_name": self.strategy_spec(fallback_strategy).get("name", fallback_strategy),
                "reason": fallback_reason,
            },
            "aggregate": {
                "tested_count": 0,
                "success_rate": 0.0,
                "avg_total_return": 0.0,
                "avg_win_rate": 0.0,
                "avg_score": 0.0,
                "avg_day_range_pct": 0.0,
                "strategies_tested": [fallback_strategy],
            },
            "leaderboard": leaderboard,
            "latest": None,
            "cross_validation": [],
            "training_skipped": True,
            "fallback_reason": fallback_reason,
        }

    def _rolling_mean(self, values, window, default=0.0):
        if window <= 0 or len(values) == 0:
            return default
        sample = values[-window:]
        if len(sample) == 0:
            return default
        return sum(sample) / len(sample)

    def _ema_step(self, prev, price, period):
        if period <= 1:
            return price
        alpha = 2.0 / (period + 1.0)
        if prev is None:
            return price
        return (price * alpha) + (prev * (1 - alpha))

    def _event_filter_snapshot(self, symbol, market="KS"):
        return {
            "symbol": symbol,
            "market": market,
            "provider": "none",
            "blocked": False,
            "reason": "외부 뉴스/공시 필터 미연동",
            "severity": "info",
        }

    def _ensure_numpy_rec_alias(self):
        """WIZ Python 3.14 환경에서 pandas/yfinance가 기대하는 `numpy.rec` 별칭 보정."""
        try:
            import numpy as np
            rec_mod = getattr(np, "rec", None)
            if rec_mod is not None and "numpy.rec" not in sys.modules:
                sys.modules["numpy.rec"] = rec_mod
            if rec_mod is not None:
                setattr(np, "rec", rec_mod)
            orig_getattr = getattr(np, "__getattr__", None)
            if rec_mod is not None and orig_getattr is not None and getattr(np, "_wiz_rec_patched", False) is False:
                def _wiz_numpy_getattr(name):
                    if name == "rec":
                        return rec_mod
                    return orig_getattr(name)
                np.__getattr__ = _wiz_numpy_getattr
                np._wiz_rec_patched = True
        except Exception:
            pass

    def _rows_to_sessions(self, rows, market="KS"):
        rows.sort(key=lambda x: x["timestamp"])
        grouped = {}
        is_us = str(market or "").upper() in ("US", "NYSE", "NASD", "NASDAQ", "AMEX")
        for row in rows:
            if is_us:
                # US 세션은 KST 기준으로 자정을 걸쳐 있으므로 ET 날짜로 그룹핑
                # ET ≈ KST - 13h (EDT 기준). KST 00:00~12:59 → 전날 ET 세션에 속함
                try:
                    import datetime as _dt
                    kst_dt = _dt.datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M")
                    if kst_dt.hour < 13:  # 새벽~낮 = US 전날 오후장
                        et_date = (kst_dt - _dt.timedelta(days=1)).strftime("%Y-%m-%d")
                    else:
                        et_date = kst_dt.strftime("%Y-%m-%d")
                    grouped.setdefault(et_date, []).append(row)
                except Exception:
                    grouped.setdefault(row["date"], []).append(row)
            else:
                grouped.setdefault(row["date"], []).append(row)
        result = []
        prev_close = 0
        for day in sorted(grouped.keys()):
            bars = grouped[day]
            if len(bars) == 0:
                continue
            anchor = prev_close if prev_close > 0 else bars[0]["open"]
            decorated = self._decorate_bars(bars, anchor)
            result.append({"date": day, "prev_close": anchor, "bars": decorated})
            prev_close = decorated[-1]["close"]
        if len(result) == 0:
            raise Exception("사용 가능한 세션 데이터가 없습니다.")
        return result

    def _prepare_dataset_subprocess(self, yf_symbol, period, interval):
        script = r'''
import json, sys
import yfinance as yf

symbol = sys.argv[1]
period = sys.argv[2]
interval = sys.argv[3]
hist = yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=True, prepost=False)
if hist is None or hist.empty:
    print(json.dumps({"ok": False, "message": f"{symbol}의 분봉 데이터를 찾을 수 없습니다."}, ensure_ascii=False))
    raise SystemExit(0)
rows = []
for idx, row in hist.iterrows():
    ts = idx
    try:
        if getattr(ts, "tzinfo", None) is not None:
            ts = ts.tz_convert("Asia/Seoul")
    except Exception:
        pass
    rows.append({
        "timestamp": ts.strftime("%Y-%m-%d %H:%M"),
        "date": ts.strftime("%Y-%m-%d"),
        "time": ts.strftime("%H:%M"),
        "open": float(row.get("Open", 0) or 0),
        "high": float(row.get("High", 0) or 0),
        "low": float(row.get("Low", 0) or 0),
        "close": float(row.get("Close", 0) or 0),
        "volume": int(row.get("Volume", 0) or 0),
    })
print(json.dumps({"ok": True, "rows": rows}, ensure_ascii=False))
'''
        proc = subprocess.run(
            [sys.executable, "-c", script, yf_symbol, period, interval],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode != 0 and not proc.stdout:
            raise Exception((proc.stderr or proc.stdout or "yfinance subprocess failed").strip())
        try:
            payload = json.loads((proc.stdout or "").strip() or "{}")
        except Exception:
            raise Exception((proc.stderr or proc.stdout or "yfinance subprocess parse failed").strip())
        if payload.get("ok") is not True:
            raise Exception(payload.get("message", f"{yf_symbol}의 분봉 데이터를 찾을 수 없습니다."))
        return payload.get("rows", [])

    # =========================================================================
    # Data
    # =========================================================================

    def _prepare_dataset(self, symbol, market="KS", period="5d", interval="1m"):
        cache_key = f"{symbol}:{market}:{period}:{interval}"
        now_ts = _time.time()
        cached = Daytrade._DATASET_CACHE.get(cache_key)
        if cached and (now_ts - cached[0]) < Daytrade._DATASET_CACHE_TTL:
            return cached[1]
        self._ensure_numpy_rec_alias()
        rows = []
        try:
            import yfinance as yf
        except ImportError:
            raise Exception("yfinance 패키지가 설치되지 않았습니다.")
        is_us_market = str(market or "").upper() in ("US", "NYSE", "NASD", "NASDAQ", "AMEX")
        # US도 prepost=False 유지: 정규장(09:30~16:00) 개장가= 갭 기준, aftermarket 오염 방지
        use_prepost = False
        yf_symbol = self._normalize_symbol(symbol, market)
        try:
            hist = yf.Ticker(yf_symbol).history(period=period, interval=interval, auto_adjust=True, prepost=use_prepost)
            if hist is None or hist.empty:
                raise Exception(f"{yf_symbol}의 분봉 데이터를 찾을 수 없습니다.")
            for idx, row in hist.iterrows():
                ts = idx
                try:
                    if getattr(ts, "tzinfo", None) is not None:
                        ts = ts.tz_convert("Asia/Seoul")
                except Exception:
                    pass
                rows.append({
                    "timestamp": ts.strftime("%Y-%m-%d %H:%M"),
                    "date": ts.strftime("%Y-%m-%d"),
                    "time": ts.strftime("%H:%M"),
                    "open": self._safe_float(row.get("Open", 0)),
                    "high": self._safe_float(row.get("High", 0)),
                    "low": self._safe_float(row.get("Low", 0)),
                    "close": self._safe_float(row.get("Close", 0)),
                    "volume": self._safe_int(row.get("Volume", 0)),
                })
        except ModuleNotFoundError as e:
            if "numpy.rec" not in str(e):
                raise
            rows = self._prepare_dataset_subprocess(yf_symbol, period, interval)
        result = self._rows_to_sessions(rows, market=market)
        Daytrade._DATASET_CACHE[cache_key] = (_time.time(), result)
        return result

    def _decorate_bars(self, bars, anchor):
        open_price = self._safe_float(bars[0].get("open", 0))
        cum_pv = 0.0
        cum_vol = 0.0
        above_vol = 0.0
        below_vol = 0.0
        closes = []
        volumes = []
        ema12 = None
        ema26 = None
        signal9 = None
        decorated = []
        for row in bars:
            price = self._safe_float(row.get("close", 0))
            vol = max(self._safe_int(row.get("volume", 0)), 1)
            cum_pv += price * vol
            cum_vol += vol
            vwap = cum_pv / cum_vol if cum_vol > 0 else price
            if price >= vwap:
                above_vol += vol
            else:
                below_vol += vol
            above_ratio = above_vol / cum_vol if cum_vol > 0 else 0
            below_ratio = below_vol / cum_vol if cum_vol > 0 else 0
            ret_anchor = ((price - anchor) / anchor * 100) if anchor > 0 else 0
            gap_open = ((price - open_price) / open_price * 100) if open_price > 0 else 0
            range_pct = ((self._safe_float(row.get("high", 0), 0) - self._safe_float(row.get("low", 0), 0)) / anchor * 100) if anchor > 0 else 0
            closes.append(price)
            volumes.append(vol)
            ma_fast = self._rolling_mean(closes, 5, price)
            ma_slow = self._rolling_mean(closes, 20, price)
            ma_trend = self._rolling_mean(closes, 60, price)
            # 볼린저 밴드 (20봉 이동평균 ±2σ)
            bb_n = min(20, len(closes))
            bb_window = closes[-bb_n:]
            bb_mean20 = sum(bb_window) / bb_n
            bb_variance = sum((x - bb_mean20) ** 2 for x in bb_window) / bb_n
            bb_std = bb_variance ** 0.5
            bb_upper = bb_mean20 + 2.0 * bb_std
            bb_lower = bb_mean20 - 2.0 * bb_std
            prev_closes = closes[-15:]
            gains = []
            losses = []
            for idx in range(1, len(prev_closes)):
                delta = prev_closes[idx] - prev_closes[idx - 1]
                gains.append(max(delta, 0))
                losses.append(abs(min(delta, 0)))
            avg_gain = (sum(gains) / len(gains)) if len(gains) > 0 else 0
            avg_loss = (sum(losses) / len(losses)) if len(losses) > 0 else 0
            if avg_loss == 0:
                rsi14 = 100.0 if avg_gain > 0 else 50.0
            else:
                rs = avg_gain / avg_loss
                rsi14 = 100 - (100 / (1 + rs))
            ema12 = self._ema_step(ema12, price, 12)
            ema26 = self._ema_step(ema26, price, 26)
            macd = (ema12 - ema26) if ema12 is not None and ema26 is not None else 0.0
            signal9 = self._ema_step(signal9, macd, 9)
            macd_hist = macd - (signal9 or 0.0)
            volume_avg = self._rolling_mean(volumes[:-1], 5, vol) if len(volumes) > 1 else vol
            volume_surge = (vol / volume_avg) if volume_avg > 0 else 1.0
            breakout_high = max([self._safe_float(x.get("high", 0), 0) for x in decorated[-20:]], default=self._safe_float(row.get("high", 0), 0))
            breakout_low = min([self._safe_float(x.get("low", 0), 0) for x in decorated[-20:]], default=self._safe_float(row.get("low", 0), 0))
            trend_strength = ((ma_fast - ma_slow) / ma_slow * 100) if ma_slow > 0 else 0
            decorated.append({
                **row,
                "anchor_return_pct": round(ret_anchor, 4),
                "vwap": round(vwap, 4),
                "open_price": open_price,
                "volume_above_ratio": round(above_ratio, 4),
                "volume_below_ratio": round(below_ratio, 4),
                "gap_from_open_pct": round(gap_open, 4),
                "intraday_range_pct": round(range_pct, 4),
                "ma_fast": round(ma_fast, 4),
                "ma_slow": round(ma_slow, 4),
                "ma_trend": round(ma_trend, 4),
                "rsi14": round(rsi14, 4),
                "macd": round(macd, 4),
                "macd_signal": round(signal9 or 0.0, 4),
                "macd_hist": round(macd_hist, 4),
                "volume_avg_5": round(volume_avg, 4),
                "volume_surge_ratio": round(volume_surge, 4),
                "breakout_high_20": round(breakout_high, 4),
                "breakout_low_20": round(breakout_low, 4),
                "trend_strength_pct": round(trend_strength, 4),
                "vwap_gap_pct": round(((price - vwap) / vwap * 100) if vwap > 0 else 0, 4),
                "bb_upper": round(bb_upper, 4),
                "bb_lower": round(bb_lower, 4),
                "bb_mid": round(bb_mean20, 4),
            })
        return decorated

    # =========================================================================
    # Simulation
    # =========================================================================

    def _regime(self, bar, profile):
        dominance = self._safe_float(profile.get("dominance_threshold", 0.55), 0.55)
        price = self._safe_float(bar.get("close", 0))
        open_price = self._safe_float(bar.get("open_price", 0))
        vwap = self._safe_float(bar.get("vwap", 0))
        above = self._safe_float(bar.get("volume_above_ratio", 0))
        below = self._safe_float(bar.get("volume_below_ratio", 0))
        if price >= open_price and price >= vwap and above >= dominance:
            return "STRONG_UP"
        if price <= open_price and price <= vwap and below >= dominance:
            return "STRONG_DOWN"
        return "SIDEWAYS"

    def _bounded(self, value, lower, upper):
        return max(lower, min(upper, value))

    def _trend_alignment_snapshot(self, session, profile=None):
        profile = {**self.DEFAULT_PROFILE, **(profile or {})}
        bars = list(session.get("bars", []) or [])
        if len(bars) == 0:
            return {
                "regime": "UNKNOWN",
                "trend_alignment_score": 0.0,
                "price_vs_vwap_pct": 0.0,
                "price_vs_ma_slow_pct": 0.0,
                "close_strength_pct": 0.0,
            }
        bar = dict(bars[-1] or {})
        price = self._safe_float(bar.get("close", 0), 0)
        open_price = self._safe_float(bar.get("open_price", price), price)
        vwap = self._safe_float(bar.get("vwap", price), price)
        ma_fast = self._safe_float(bar.get("ma_fast", price), price)
        ma_slow = self._safe_float(bar.get("ma_slow", price), price)
        ma_trend = self._safe_float(bar.get("ma_trend", price), price)
        trend_strength = self._safe_float(bar.get("trend_strength_pct", 0), 0)
        macd_hist = self._safe_float(bar.get("macd_hist", 0), 0)
        rsi14 = self._safe_float(bar.get("rsi14", 50), 50)
        volume_surge_ratio = self._safe_float(bar.get("volume_surge_ratio", 1.0), 1.0)
        price_vs_vwap_pct = ((price - vwap) / vwap * 100) if vwap > 0 else 0.0
        price_vs_ma_slow_pct = ((price - ma_slow) / ma_slow * 100) if ma_slow > 0 else 0.0
        close_strength_pct = ((price - open_price) / open_price * 100) if open_price > 0 else 0.0
        regime = self._regime(bar, profile)
        score = 0.0
        score += 0.18 if price >= vwap else -0.18
        score += 0.14 if ma_fast >= ma_slow else -0.14
        score += 0.10 if ma_slow >= ma_trend else -0.10
        if regime == "STRONG_UP":
            score += 0.12
        elif regime == "STRONG_DOWN":
            score -= 0.12
        score += self._bounded(trend_strength / 4.0, -0.16, 0.16)
        score += self._bounded(macd_hist / 0.35, -0.12, 0.12)
        score += self._bounded((rsi14 - 50.0) / 100.0, -0.08, 0.08)
        score += self._bounded((volume_surge_ratio - 1.0) * 0.05, -0.05, 0.08)
        return {
            "regime": regime,
            "trend_alignment_score": round(score, 4),
            "price_vs_vwap_pct": round(price_vs_vwap_pct, 4),
            "price_vs_ma_slow_pct": round(price_vs_ma_slow_pct, 4),
            "close_strength_pct": round(close_strength_pct, 4),
        }

    def _min_trend_alignment_score(self, strategy_id, profile=None):
        profile = {**self.DEFAULT_PROFILE, **(profile or {})}
        sid = self._normalize_strategy(strategy_id)
        profile_key = f"{sid}_min_trend_alignment_score"
        if profile_key in profile:
            return self._safe_float(profile.get(profile_key, 0), 0)
        if sid == "ma_trend":
            return 0.12
        if sid == "volume_breakout":
            return 0.08
        if sid == "rsi_reversion":
            return -0.10
        return -0.18

    def feature_snapshot(self, symbol, market="KS"):
        session = self._prepare_dataset(symbol, market=market, period="2d", interval="1m")[-1]
        bar = dict(session.get("bars", [])[-1]) if session.get("bars") else {}
        trend_snapshot = self._trend_alignment_snapshot(session, profile=self._default_profile_for_market(market=market))
        return {
            "symbol": symbol,
            "market": market,
            "session_date": session.get("date", ""),
            "price": self._safe_float(bar.get("close", 0), 0),
            "anchor_price": self._safe_float(session.get("prev_close", 0), 0),
            "ma_fast": self._safe_float(bar.get("ma_fast", 0), 0),
            "ma_slow": self._safe_float(bar.get("ma_slow", 0), 0),
            "ma_trend": self._safe_float(bar.get("ma_trend", 0), 0),
            "rsi14": self._safe_float(bar.get("rsi14", 0), 0),
            "macd_hist": self._safe_float(bar.get("macd_hist", 0), 0),
            "volume_surge_ratio": self._safe_float(bar.get("volume_surge_ratio", 0), 0),
            "intraday_range_pct": self._safe_float(bar.get("intraday_range_pct", 0), 0),
            "gap_from_open_pct": self._safe_float(bar.get("gap_from_open_pct", 0), 0),
            "vwap_gap_pct": self._safe_float(bar.get("vwap_gap_pct", 0), 0),
            "regime": trend_snapshot.get("regime", "SIDEWAYS"),
            "trend_alignment_score": self._safe_float(trend_snapshot.get("trend_alignment_score", 0), 0),
            "price_vs_vwap_pct": self._safe_float(trend_snapshot.get("price_vs_vwap_pct", 0), 0),
            "price_vs_ma_slow_pct": self._safe_float(trend_snapshot.get("price_vs_ma_slow_pct", 0), 0),
            "close_strength_pct": self._safe_float(trend_snapshot.get("close_strength_pct", 0), 0),
            "event_filter": self._event_filter_snapshot(symbol, market=market),
        }

    def vrev_entry_issues(self, bar, profile=None):
        profile = {**self.DEFAULT_PROFILE, **(profile or {})}
        issues = []
        current_price = self._safe_float(bar.get("close", 0), 0)
        vwap = self._safe_float(bar.get("vwap", 0), 0)
        rsi_live = self._safe_float(bar.get("rsi14", 50), 50)
        min_entry_rsi = self._safe_float(
            profile.get("vrev_entry_min_rsi", profile.get("min_live_entry_rsi", profile.get("rsi_entry", 30))),
            35,
        )
        max_vwap_discount_pct = self._safe_float(
            profile.get("vrev_entry_max_vwap_discount_pct", profile.get("max_live_vwap_discount_pct", 0.8)),
            0.5,
        )
        min_trend_strength_pct = self._safe_float(profile.get("vrev_entry_min_trend_strength_pct", 0), 0)
        require_ma_support = bool(profile.get("vrev_entry_require_ma_support", True))

        if current_price > 0 and vwap > 0:
            vwap_discount_pct = (1 - (current_price / vwap)) * 100
            if vwap_discount_pct > max_vwap_discount_pct:
                issues.append(f"VWAP 대비 하락 과다 ({vwap_discount_pct:.2f}% > 최대 {max_vwap_discount_pct:.1f}%)")

        if current_price > 0 and rsi_live < min_entry_rsi:
            issues.append(f"RSI {rsi_live:.1f} < 최소 {min_entry_rsi:.1f}")

        trend_strength_pct = self._safe_float(bar.get("trend_strength_pct", 0), 0)
        if trend_strength_pct < min_trend_strength_pct:
            issues.append(f"추세 약세 {trend_strength_pct:.2f}% < 최소 {min_trend_strength_pct:.2f}%")

        ma_fast = self._safe_float(bar.get("ma_fast", 0), 0)
        ma_slow = self._safe_float(bar.get("ma_slow", 0), 0)
        if require_ma_support and ma_fast > 0 and ma_slow > 0 and ma_fast < ma_slow:
            issues.append(f"단기 이평 약세 ({ma_fast:.2f} < {ma_slow:.2f})")

        return issues

    def _chunk_qty(self, budget, price):
        if budget <= 0 or price <= 0:
            return 0
        return int(budget / price)

    def _trade_cost(self, notional, profile, is_sell=False):
        notional = self._safe_float(notional, 0)
        commission_bps = self._safe_float(profile.get("commission_bps", 1.5), 1.5)
        slippage_bps = self._safe_float(profile.get("slippage_bps", 2.5), 2.5)
        tax_bps = self._safe_float(profile.get("sell_tax_bps", 18.0), 18.0) if is_sell else 0.0
        return notional * (commission_bps + slippage_bps + tax_bps) / 10000.0

    def _append_buy_lot(self, lots, qty, price, tag, timestamp, trades, profile, reason=""):
        if qty <= 0 or price <= 0:
            return None
        gross = qty * price
        fee = self._trade_cost(gross, profile, is_sell=False)
        unit_cost = (gross + fee) / qty if qty > 0 else price
        lots.append({
            "qty": qty,
            "price": round(unit_cost, 6),
            "entry_price": round(price, 4),
            "tag": tag,
            "timestamp": timestamp,
            "transferred": False,
        })
        trades.append({
            "side": "BUY",
            "timestamp": timestamp,
            "price": round(price, 4),
            "qty": qty,
            "amount": round(gross + fee, 2),
            "gross_amount": round(gross, 2),
            "fee": round(fee, 2),
            "reason": reason or tag,
            "pnl": 0.0,
        })
        return {"amount": gross + fee, "fee": fee}

    def _lifo_sell(self, lots, target_qty, price, timestamp, reason, trades, profile):
        remaining = int(target_qty)
        sold_qty = 0
        sold_cost = 0.0
        while remaining > 0 and len(lots) > 0:
            lot = lots[-1]
            qty = min(remaining, int(lot.get("qty", 0)))
            if qty <= 0:
                lots.pop()
                continue
            sold_qty += qty
            sold_cost += qty * self._safe_float(lot.get("price", 0))
            lot["qty"] = int(lot.get("qty", 0)) - qty
            remaining -= qty
            if lot["qty"] <= 0:
                lots.pop()
        gross = sold_qty * price
        fee = self._trade_cost(gross, profile, is_sell=True)
        proceeds = gross - fee
        pnl = proceeds - sold_cost
        if sold_qty > 0:
            trades.append({
                "side": "SELL",
                "timestamp": timestamp,
                "price": round(price, 4),
                "qty": sold_qty,
                "amount": round(proceeds, 2),
                "gross_amount": round(gross, 2),
                "fee": round(fee, 2),
                "reason": reason,
                "pnl": round(pnl, 2),
            })
        return {"qty": sold_qty, "cost": sold_cost, "proceeds": proceeds, "gross": gross, "fee": fee, "pnl": pnl}

    def _summarize_session(self, session, seed, trades, realized, equity_curve, strategy_id, event_filter, holding_minutes=0, custom_metrics=None):
        total_buys = sum(t.get("amount", 0) for t in trades if t.get("side") == "BUY")
        total_sells = sum(t.get("amount", 0) for t in trades if t.get("side") == "SELL")
        fees = sum(t.get("fee", 0) for t in trades)
        sell_pnls = [self._safe_float(t.get("pnl", 0), 0) for t in trades if t.get("side") == "SELL"]
        gross_profit = sum(x for x in sell_pnls if x > 0)
        gross_loss = sum(x for x in sell_pnls if x < 0)
        wins = len([x for x in sell_pnls if x > 0])
        losses = len([x for x in sell_pnls if x < 0])
        summary = {
            "date": session.get("date"),
            "seed": round(seed, 2),
            "strategy_id": strategy_id,
            "profit": round(realized, 2),
            "net_profit": round(realized, 2),
            "return_pct": round((realized / seed * 100) if seed > 0 else 0, 4),
            "trade_count": len(trades),
            "buy_amount": round(total_buys, 2),
            "sell_amount": round(total_sells, 2),
            "turnover": round(total_buys + total_sells, 2),
            "fees": round(fees, 2),
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "win_trade_count": wins,
            "loss_trade_count": losses,
            "avg_holding_minutes": round(holding_minutes, 2),
            "trades": trades,
            "equity_curve": equity_curve,
            "bar_count": len(session.get("bars", [])),
            "event_filter": event_filter,
        }
        if custom_metrics:
            summary["custom_metrics"] = custom_metrics
        return summary

    def _simulate_vrev_session(self, session, seed, profile=None):
        profile = {**self.DEFAULT_PROFILE, **(profile or {})}
        anchor = self._safe_float(session.get("prev_close", 0))
        bars = session.get("bars", [])
        budget_total = seed * self._safe_float(profile.get("budget_ratio", 0.95))
        buy_budget = budget_total * self._safe_float(profile.get("buy_split_ratio", 1.0))
        lots = []
        trades = []
        realized = 0.0
        equity_curve = []
        buy1_used = False
        buy2_used = False
        holding_minutes = 0
        for bar in bars:
            price = self._safe_float(bar.get("close", 0))
            if price <= 0:
                continue
            regime = self._regime(bar, profile)
            timestamp = bar.get("timestamp", "")
            exec_buy_price = min(price, self._safe_float(bar.get("vwap", price))) if regime == "SIDEWAYS" else price
            entry_issues = self.vrev_entry_issues(bar, profile)
            if buy1_used == False and price <= anchor * (1 + self._safe_float(profile.get("buy_trigger_1_pct", -0.5)) / 100) and len(entry_issues) == 0:
                qty = self._chunk_qty(buy_budget, exec_buy_price)
                if qty > 0:
                    self._append_buy_lot(lots, qty, exec_buy_price, "BUY1", timestamp, trades, profile, reason="Buy dip entry")
                    buy1_used = True
                    buy2_used = True  # 단일 진입 모드: BUY2 비활성화
            total_qty = sum(int(x.get("qty", 0)) for x in lots)
            total_cost = sum(int(x.get("qty", 0)) * self._safe_float(x.get("price", 0)) for x in lots)
            avg_price = total_cost / total_qty if total_qty > 0 else 0
            if total_qty > 0:
                holding_minutes += 1
                jackpot_pct_sim = self._safe_float(profile.get("jackpot_take_profit_pct", 2.0))
                jackpot = avg_price * (1 + jackpot_pct_sim / 100)
                stop_loss_pct_sim = self._safe_float(profile.get("stop_loss_pct", 1.5), 1.5)
                rsi_live = self._safe_float(bar.get("rsi14", 50), 50)
                rsi_exit_overbought = self._safe_float(profile.get("rsi_exit_overbought", 75), 75)
                bb_upper_val = self._safe_float(bar.get("bb_upper", 0), 0)
                if stop_loss_pct_sim > 0 and price < avg_price * (1 - stop_loss_pct_sim / 100):
                    # 자동 손절 (최우선)
                    sold = self._lifo_sell(lots, total_qty, price, timestamp, "Auto stop loss", trades, profile)
                    realized += sold["pnl"]
                    buy1_used = False
                    buy2_used = False
                elif price >= jackpot:
                    # 목표 수익률 도달 → 전량 익절
                    sold = self._lifo_sell(lots, total_qty, price, timestamp, "Jackpot sweep", trades, profile)
                    realized += sold["pnl"]
                    if sum(int(x.get("qty", 0)) for x in lots) == 0:
                        buy1_used = False
                        buy2_used = False
                elif bb_upper_val > 0 and price >= bb_upper_val and price >= avg_price:
                    # BB 상단 저항 도달 → 전량 익절
                    sold = self._lifo_sell(lots, total_qty, price, timestamp, "BB upper exit", trades, profile)
                    realized += sold["pnl"]
                    if sum(int(x.get("qty", 0)) for x in lots) == 0:
                        buy1_used = False
                        buy2_used = False
                elif rsi_live >= rsi_exit_overbought and price >= avg_price:
                    # RSI 과매수 구간 → 전량 익절
                    sold = self._lifo_sell(lots, total_qty, price, timestamp, f"RSI {rsi_live:.0f} overbought exit", trades, profile)
                    realized += sold["pnl"]
                    if sum(int(x.get("qty", 0)) for x in lots) == 0:
                        buy1_used = False
                        buy2_used = False
                else:
                    chunk_budget = budget_total
                    recent_target = anchor * (1 + self._safe_float(profile.get("recent_lot_take_profit_pct", 0.6)) / 100)
                    rescue_target = avg_price * (1 + self._safe_float(profile.get("rescue_take_profit_pct", 0.5)) / 100)
                    if price >= recent_target:
                        sold = self._lifo_sell(lots, self._chunk_qty(chunk_budget, price), price, timestamp, "Take profit", trades, profile)
                        realized += sold["pnl"]
                        if sum(int(x.get("qty", 0)) for x in lots) == 0:
                            buy1_used = False
                            buy2_used = False
                    elif price >= rescue_target and len(lots) >= 2:
                        sold = self._lifo_sell(lots, self._chunk_qty(chunk_budget, price), price, timestamp, "Rescue exit", trades, profile)
                        realized += sold["pnl"]
                        if sum(int(x.get("qty", 0)) for x in lots) == 0:
                            buy1_used = False
                            buy2_used = False
            mtm_qty = sum(int(x.get("qty", 0)) for x in lots)
            mtm_cost = sum(int(x.get("qty", 0)) * self._safe_float(x.get("price", 0), 0) for x in lots)
            equity_curve.append(round(seed + realized + (mtm_qty * price - mtm_cost), 2))
        if len(bars) > 0 and len(lots) > 0:
            last_price = self._safe_float(bars[-1].get("close", 0))
            sold = self._lifo_sell(lots, sum(int(x.get("qty", 0)) for x in lots), last_price, bars[-1].get("timestamp", ""), "End-of-day flat close", trades, profile)
            realized += sold["pnl"]
            equity_curve.append(round(seed + realized, 2))
        return self._summarize_session(session, seed, trades, realized, equity_curve, "vrev", self._event_filter_snapshot("", "KS"), holding_minutes=holding_minutes)

    def _simulate_volume_breakout_session(self, session, seed, profile=None):
        profile = {**self.DEFAULT_PROFILE, **(profile or {})}
        bars = session.get("bars", [])
        budget_total = seed * self._safe_float(profile.get("budget_ratio", 0.95))
        trades = []
        equity_curve = []
        lots = []
        realized = 0.0
        holding_minutes = 0
        
        # Metrics for volume_breakout
        opening_15min_bars = [b for b in bars if b.get("time", "99:99") <= "09:15"]
        opening_high = max([self._safe_float(b.get("high", 0)) for b in opening_15min_bars]) if opening_15min_bars else 0
        opening_low = min([self._safe_float(b.get("low", 0)) for b in opening_15min_bars]) if opening_15min_bars else 0
        anchor = self._safe_float(session.get("prev_close", 0))
        opening_volatility_pct = ((opening_high - opening_low) / anchor * 100) if anchor > 0 and opening_high > 0 else 0.0

        breakout_entry_bar = None
        sustain_ticks = 0
        total_ticks_after_breakout = 0
        volume_after_breakout = 0
        
        entry_rule=lambda bar, _session, p: (
            self._safe_float(bar.get("volume_surge_ratio", 0), 0) >= self._safe_float(p.get("breakout_volume_ratio", 1.2), 1.2)
            and self._safe_float(bar.get("close", 0), 0) >= self._safe_float(bar.get("breakout_high_20", 0), 0) * 0.998
            and self._safe_float(bar.get("close", 0), 0) >= self._safe_float(bar.get("vwap", 0), 0) * 0.995
        )
        exit_rule=lambda bar, _session, p, avg_cost: (
            self._safe_float(bar.get("close", 0), 0) >= avg_cost * (1 + self._safe_float(p.get("breakout_take_profit_pct", 1.4), 1.4) / 100)
            or self._safe_float(bar.get("close", 0), 0) <= avg_cost * (1 - self._safe_float(p.get("breakout_stop_loss_pct", 0.8), 0.8) / 100)
            or self._safe_float(bar.get("close", 0), 0) < self._safe_float(bar.get("breakout_low_20", 0), 0)
            or self._safe_float(bar.get("close", 0), 0) < self._safe_float(bar.get("vwap", 0), 0)
        )

        for bar in bars:
            price = self._safe_float(bar.get("close", 0), 0)
            if price <= 0:
                continue
            timestamp = bar.get("timestamp", "")
            position_qty = sum(int(x.get("qty", 0)) for x in lots)
            avg_cost = (sum(int(x.get("qty", 0)) * self._safe_float(x.get("price", 0), 0) for x in lots) / position_qty) if position_qty > 0 else 0

            if breakout_entry_bar is not None:
                total_ticks_after_breakout += 1
                volume_after_breakout += self._safe_int(bar.get("volume", 0))
                if price >= breakout_entry_bar['breakout_high_20']:
                    sustain_ticks += 1

            if position_qty == 0 and entry_rule(bar, session, profile):
                qty = self._chunk_qty(budget_total, price)
                if qty > 0:
                    self._append_buy_lot(lots, qty, price, "VOLUME_BREAKOUT", timestamp, trades, profile, reason="volume_breakout entry")
                    position_qty = sum(int(x.get("qty", 0)) for x in lots)
                    avg_cost = (sum(int(x.get("qty", 0)) * self._safe_float(x.get("price", 0), 0) for x in lots) / position_qty) if position_qty > 0 else 0
                    breakout_entry_bar = bar
            elif position_qty > 0:
                holding_minutes += 1
                if exit_rule(bar, session, profile, avg_cost):
                    sold = self._lifo_sell(lots, position_qty, price, timestamp, "volume_breakout exit", trades, profile)
                    realized += sold.get("pnl", 0)
                    breakout_entry_bar = None # Reset on exit
            
            mtm_qty = sum(int(x.get("qty", 0)) for x in lots)
            mtm_cost = sum(int(x.get("qty", 0)) * self._safe_float(x.get("price", 0), 0) for x in lots)
            equity_curve.append(round(seed + realized + (mtm_qty * price - mtm_cost), 2))

        if len(bars) > 0 and len(lots) > 0:
            last_price = self._safe_float(bars[-1].get("close", 0), 0)
            sold = self._lifo_sell(lots, sum(int(x.get("qty", 0)) for x in lots), last_price, bars[-1].get("timestamp", ""), "End-of-day flat close", trades, profile)
            realized += sold.get("pnl", 0)
            equity_curve.append(round(seed + realized, 2))

        breakout_sustain_rate = (sustain_ticks / total_ticks_after_breakout * 100) if total_ticks_after_breakout > 0 else 0
        
        entry_vol = self._safe_int(breakout_entry_bar.get("volume", 0)) if breakout_entry_bar else 0
        avg_vol_after = (volume_after_breakout / total_ticks_after_breakout) if total_ticks_after_breakout > 0 else 0
        volume_sustainability = (avg_vol_after / entry_vol) if entry_vol > 0 else 0

        failure_reason = None
        if breakout_entry_bar is None:
            for bar in bars:
                if self._safe_float(bar.get("volume_surge_ratio", 0), 0) < self._safe_float(profile.get("breakout_volume_ratio", 1.2), 1.2):
                    failure_reason = "거래량 부족"
                elif self._safe_float(bar.get("close", 0), 0) < self._safe_float(bar.get("breakout_high_20", 0), 0) * 0.998:
                    failure_reason = "돌파 실패"
                else:
                    failure_reason = "조건 미충족"
                break 
        
        post_breakout_low = 0
        if breakout_entry_bar:
            post_breakout_bars = bars[bars.index(breakout_entry_bar):]
            post_breakout_low = min([self._safe_float(b.get("low", 0)) for b in post_breakout_bars[:3]])
        
        post_breakout_drawdown_pct = 0
        if breakout_entry_bar and post_breakout_low > 0:
            entry_price = self._safe_float(breakout_entry_bar.get("close", 0), 0)
            post_breakout_drawdown_pct = ((post_breakout_low - entry_price) / entry_price * 100) if entry_price > 0 else 0

        sustain_score = min(breakout_sustain_rate / 80, 1.0) * 40 if breakout_sustain_rate else 0
        volume_score = min(volume_sustainability / 1.5, 1.0) * 30 if volume_sustainability else 0
        drawdown_score = max(0, (1 - abs(post_breakout_drawdown_pct) / 3.0)) * 20 if post_breakout_drawdown_pct else 0
        volatility_score = max(0, (1 - opening_volatility_pct / 10.0)) * 10 if opening_volatility_pct else 0
        shadow_mode_score = sustain_score + volume_score + drawdown_score + volatility_score

        custom_metrics = {
            "breakout_sustain_rate": round(breakout_sustain_rate, 2),
            "opening_volatility_pct": round(opening_volatility_pct, 2),
            "volume_sustainability": round(volume_sustainability, 2),
            "failure_reason": failure_reason,
            "post_breakout_drawdown_pct": round(post_breakout_drawdown_pct, 2),
            "shadow_slippage_pct": 0, # Placeholder
            "shadow_mode_score": round(shadow_mode_score, 2)
        }

        return self._summarize_session(session, seed, trades, realized, equity_curve, "volume_breakout", self._event_filter_snapshot("", "KS"), holding_minutes=holding_minutes, custom_metrics=custom_metrics)

    def _simulate_single_position_session(self, session, seed, strategy_id, profile, entry_rule, exit_rule):
        bars = session.get("bars", [])
        budget_total = seed * self._safe_float(profile.get("budget_ratio", 0.95))  # 0.15 → 0.95 수정
        trades = []
        equity_curve = []
        lots = []
        realized = 0.0
        holding_minutes = 0
        for bar in bars:
            price = self._safe_float(bar.get("close", 0), 0)
            if price <= 0:
                continue
            timestamp = bar.get("timestamp", "")
            position_qty = sum(int(x.get("qty", 0)) for x in lots)
            avg_cost = (sum(int(x.get("qty", 0)) * self._safe_float(x.get("price", 0), 0) for x in lots) / position_qty) if position_qty > 0 else 0
            if position_qty == 0 and entry_rule(bar, session, profile):
                qty = self._chunk_qty(budget_total, price)
                if qty > 0:
                    self._append_buy_lot(lots, qty, price, strategy_id.upper(), timestamp, trades, profile, reason=f"{strategy_id} entry")
                    position_qty = sum(int(x.get("qty", 0)) for x in lots)
                    avg_cost = (sum(int(x.get("qty", 0)) * self._safe_float(x.get("price", 0), 0) for x in lots) / position_qty) if position_qty > 0 else 0
            elif position_qty > 0:
                holding_minutes += 1
                if exit_rule(bar, session, profile, avg_cost):
                    sold = self._lifo_sell(lots, position_qty, price, timestamp, f"{strategy_id} exit", trades, profile)
                    realized += sold.get("pnl", 0)
            mtm_qty = sum(int(x.get("qty", 0)) for x in lots)
            mtm_cost = sum(int(x.get("qty", 0)) * self._safe_float(x.get("price", 0), 0) for x in lots)
            equity_curve.append(round(seed + realized + (mtm_qty * price - mtm_cost), 2))
        if len(bars) > 0 and len(lots) > 0:
            last_price = self._safe_float(bars[-1].get("close", 0), 0)
            sold = self._lifo_sell(lots, sum(int(x.get("qty", 0)) for x in lots), last_price, bars[-1].get("timestamp", ""), "End-of-day flat close", trades, profile)
            realized += sold.get("pnl", 0)
            equity_curve.append(round(seed + realized, 2))
        return self._summarize_session(session, seed, trades, realized, equity_curve, strategy_id, self._event_filter_snapshot("", "KS"), holding_minutes=holding_minutes)

    def _simulate_single_position_session_advanced(self, session, seed, strategy_id, profile, entry_rule, exit_rule):
        bars = session.get("bars", [])
        budget_total = seed * self._safe_float(profile.get("budget_ratio", 0.95))
        trades = []
        equity_curve = []
        lots = []
        realized = 0.0
        holding_minutes = 0
        state = {}
        prev_bar = None
        for idx, bar in enumerate(bars):
            price = self._safe_float(bar.get("close", 0), 0)
            if price <= 0:
                prev_bar = bar
                continue
            timestamp = bar.get("timestamp", "")
            position_qty = sum(int(x.get("qty", 0)) for x in lots)
            avg_cost = (sum(int(x.get("qty", 0)) * self._safe_float(x.get("price", 0), 0) for x in lots) / position_qty) if position_qty > 0 else 0
            if position_qty == 0 and entry_rule(bar, prev_bar, idx, session, profile, state):
                qty = self._chunk_qty(budget_total, price)
                if qty > 0:
                    self._append_buy_lot(lots, qty, price, strategy_id.upper(), timestamp, trades, profile, reason=f"{strategy_id} entry")
                    state["entry_price"] = price
                    state["highest_since_entry"] = price
            elif position_qty > 0:
                holding_minutes += 1
                state["highest_since_entry"] = max(self._safe_float(state.get("highest_since_entry", avg_cost), avg_cost), price)
                if exit_rule(bar, prev_bar, idx, session, profile, state, avg_cost):
                    sold = self._lifo_sell(lots, position_qty, price, timestamp, f"{strategy_id} exit", trades, profile)
                    realized += sold.get("pnl", 0)
                    state["entry_price"] = 0.0
                    state["highest_since_entry"] = 0.0
            mtm_qty = sum(int(x.get("qty", 0)) for x in lots)
            mtm_cost = sum(int(x.get("qty", 0)) * self._safe_float(x.get("price", 0), 0) for x in lots)
            equity_curve.append(round(seed + realized + (mtm_qty * price - mtm_cost), 2))
            prev_bar = bar
        if len(bars) > 0 and len(lots) > 0:
            last_price = self._safe_float(bars[-1].get("close", 0), 0)
            sold = self._lifo_sell(lots, sum(int(x.get("qty", 0)) for x in lots), last_price, bars[-1].get("timestamp", ""), "End-of-day flat close", trades, profile)
            realized += sold.get("pnl", 0)
            equity_curve.append(round(seed + realized, 2))
        return self._summarize_session(session, seed, trades, realized, equity_curve, strategy_id, self._event_filter_snapshot("", "US"), holding_minutes=holding_minutes)

    def _simulate_us_breakout_session(self, session, seed, profile):
        tp_pct = self._safe_float(profile.get("breakout_take_profit_pct", 4.0), 4.0)
        sl_pct = self._safe_float(profile.get("breakout_stop_loss_pct", 2.5), 2.5)
        trail_pct = max(2.5, self._safe_float(profile.get("high_stop_pct", 20.0), 20.0) * 0.25)
        vol_thr = self._safe_float(profile.get("breakout_volume_ratio", 2.5), 2.5)
        min_change_pct = self._safe_float(profile.get("min_change_pct", 5.0), 5.0)

        def entry_rule(bar, prev_bar, idx, _session, _profile, state):
            high = self._safe_float(bar.get("high", 0), 0)
            low = self._safe_float(bar.get("low", 0), 0)
            state["opening_high"] = max(self._safe_float(state.get("opening_high", 0), 0), high)
            opening_low = self._safe_float(state.get("opening_low", 0), 0)
            state["opening_low"] = low if opening_low <= 0 else min(opening_low, low)
            if idx < 6 or idx > 18:
                return False
            close = self._safe_float(bar.get("close", 0), 0)
            vwap = self._safe_float(bar.get("vwap", 0), 0)
            prev_close = self._safe_float((prev_bar or {}).get("close", close), close)
            return (
                close > 0
                and self._safe_float(state.get("opening_high", 0), 0) > 0
                and close >= self._safe_float(state.get("opening_high", 0), 0) * 0.999
                and close >= vwap * 0.998
                and self._safe_float(bar.get("volume_surge_ratio", 0), 0) >= vol_thr
                and self._safe_float(bar.get("anchor_return_pct", 0), 0) >= min_change_pct
                and self._safe_float(bar.get("macd_hist", 0), 0) >= 0
                and close >= prev_close
            )

        def exit_rule(bar, _prev_bar, _idx, _session, _profile, state, avg_cost):
            if avg_cost <= 0:
                return False
            close = self._safe_float(bar.get("close", 0), 0)
            vwap = self._safe_float(bar.get("vwap", 0), 0)
            opening_low = self._safe_float(state.get("opening_low", 0), 0)
            highest = max(self._safe_float(state.get("highest_since_entry", avg_cost), avg_cost), close)
            state["highest_since_entry"] = highest
            trail_drawdown = ((highest - close) / highest * 100) if highest > 0 else 0.0
            return (
                close >= avg_cost * (1 + tp_pct / 100)
                or close <= avg_cost * (1 - sl_pct / 100)
                or close < vwap * 0.996
                or (opening_low > 0 and close < opening_low * 0.999)
                or trail_drawdown >= trail_pct
            )

        return self._simulate_single_position_session_advanced(session, seed, "us_breakout", profile, entry_rule, exit_rule)

    def _simulate_us_pullback_session(self, session, seed, profile):
        tp_pct = max(2.5, self._safe_float(profile.get("breakout_take_profit_pct", 3.5), 3.5))
        sl_pct = max(1.5, self._safe_float(profile.get("breakout_stop_loss_pct", 2.2), 2.2))
        min_surge_pct = self._safe_float(profile.get("min_prior_surge_pct", 8.0), 8.0)
        max_pullback_pct = min(10.0, self._safe_float(profile.get("entry_drawdown_max_pct", 6.0), 6.0))
        min_pullback_pct = max(1.5, self._safe_float(profile.get("entry_drawdown_min_pct", 2.0), 2.0))
        vol_cap = max(1.2, self._safe_float(profile.get("breakout_volume_ratio", 2.0), 2.0) * 0.65)

        def entry_rule(bar, prev_bar, idx, _session, _profile, state):
            close = self._safe_float(bar.get("close", 0), 0)
            high = self._safe_float(bar.get("high", 0), 0)
            state["session_high"] = max(self._safe_float(state.get("session_high", 0), 0), high)
            if self._safe_float(bar.get("anchor_return_pct", 0), 0) >= min_surge_pct:
                state["surge_seen"] = True
            if not state.get("surge_seen") or idx < 4 or idx > 42:
                return False
            session_high = self._safe_float(state.get("session_high", 0), 0)
            if session_high <= 0 or close <= 0:
                return False
            drawdown_pct = ((session_high - close) / session_high * 100) if session_high > 0 else 0.0
            prev_close = self._safe_float((prev_bar or {}).get("close", close), close)
            prev_vwap = self._safe_float((prev_bar or {}).get("vwap", close), close)
            vwap = self._safe_float(bar.get("vwap", 0), 0)
            ma_fast = self._safe_float(bar.get("ma_fast", 0), 0)
            ma_slow = self._safe_float(bar.get("ma_slow", 0), 0)
            return (
                min_pullback_pct <= drawdown_pct <= max_pullback_pct
                and self._safe_float(bar.get("volume_surge_ratio", 0), 0) <= vol_cap
                and close >= vwap * 0.995
                and close >= ma_fast * 0.995
                and ma_fast >= ma_slow * 0.995
                and self._safe_float(bar.get("macd_hist", 0), 0) >= -0.05
                and prev_close <= prev_vwap * 1.002
                and close >= prev_close
            )

        def exit_rule(bar, _prev_bar, _idx, _session, _profile, _state, avg_cost):
            if avg_cost <= 0:
                return False
            close = self._safe_float(bar.get("close", 0), 0)
            vwap = self._safe_float(bar.get("vwap", 0), 0)
            ma_fast = self._safe_float(bar.get("ma_fast", 0), 0)
            rsi14 = self._safe_float(bar.get("rsi14", 50), 50)
            return (
                close >= avg_cost * (1 + tp_pct / 100)
                or close <= avg_cost * (1 - sl_pct / 100)
                or close < vwap * 0.994
                or close < ma_fast * 0.994
                or rsi14 >= 78
            )

        return self._simulate_single_position_session_advanced(session, seed, "us_pullback", profile, entry_rule, exit_rule)

    def _simulate_us_vwap_session(self, session, seed, profile):
        tp_pct = max(2.5, self._safe_float(profile.get("breakout_take_profit_pct", 3.5), 3.5))
        sl_pct = max(1.5, self._safe_float(profile.get("breakout_stop_loss_pct", 2.0), 2.0))
        vol_thr = max(1.4, self._safe_float(profile.get("breakout_volume_ratio", 2.0), 2.0) * 0.55)

        def entry_rule(bar, prev_bar, idx, _session, _profile, _state):
            if idx < 2 or idx > 48:
                return False
            close = self._safe_float(bar.get("close", 0), 0)
            vwap = self._safe_float(bar.get("vwap", 0), 0)
            prev_close = self._safe_float((prev_bar or {}).get("close", close), close)
            prev_vwap = self._safe_float((prev_bar or {}).get("vwap", vwap), vwap)
            reclaim = prev_close < prev_vwap * 0.999 and close >= vwap * 1.001
            return (
                reclaim
                and self._safe_float(bar.get("volume_surge_ratio", 0), 0) >= vol_thr
                and self._safe_float(bar.get("macd_hist", 0), 0) >= -0.02
                and self._safe_float(bar.get("anchor_return_pct", 0), 0) >= 0.5
                and close >= self._safe_float(bar.get("ma_fast", 0), close) * 0.995
            )

        def exit_rule(bar, _prev_bar, _idx, _session, _profile, _state, avg_cost):
            if avg_cost <= 0:
                return False
            close = self._safe_float(bar.get("close", 0), 0)
            vwap = self._safe_float(bar.get("vwap", 0), 0)
            return (
                close >= avg_cost * (1 + tp_pct / 100)
                or close <= avg_cost * (1 - sl_pct / 100)
                or close < vwap * 0.997
                or (self._safe_float(bar.get("macd_hist", 0), 0) < -0.03 and self._safe_float(bar.get("vwap_gap_pct", 0), 0) < 0)
            )

        return self._simulate_single_position_session_advanced(session, seed, "us_vwap", profile, entry_rule, exit_rule)

    def _simulate_us_opening_reclaim_session(self, session, seed, profile):
        tp_pct = max(2.5, self._safe_float(profile.get("breakout_take_profit_pct", 3.8), 3.8))
        sl_pct = max(1.2, self._safe_float(profile.get("breakout_stop_loss_pct", 1.8), 1.8))
        vol_thr = max(1.4, self._safe_float(profile.get("breakout_volume_ratio", 1.8), 1.8))
        min_pullback_pct = max(0.5, self._safe_float(profile.get("entry_drawdown_min_pct", 0.8), 0.8))
        max_pullback_pct = max(min_pullback_pct + 0.5, self._safe_float(profile.get("entry_drawdown_max_pct", 3.5), 3.5))

        def entry_rule(bar, prev_bar, idx, _session, _profile, state):
            high = self._safe_float(bar.get("high", 0), 0)
            low = self._safe_float(bar.get("low", 0), 0)
            close = self._safe_float(bar.get("close", 0), 0)
            vwap = self._safe_float(bar.get("vwap", 0), 0)
            if idx <= 3:
                state["opening_high"] = max(self._safe_float(state.get("opening_high", 0), 0), high)
                opening_low = self._safe_float(state.get("opening_low", 0), 0)
                state["opening_low"] = low if opening_low <= 0 else min(opening_low, low)
                return False
            state["pullback_low"] = low if self._safe_float(state.get("pullback_low", 0), 0) <= 0 else min(self._safe_float(state.get("pullback_low", 0), 0), low)
            if idx > 24:
                return False
            opening_high = self._safe_float(state.get("opening_high", 0), 0)
            opening_low = self._safe_float(state.get("opening_low", 0), 0)
            pullback_low = self._safe_float(state.get("pullback_low", 0), 0)
            if opening_high <= 0 or close <= 0 or vwap <= 0 or pullback_low <= 0:
                return False
            pullback_pct = ((opening_high - pullback_low) / opening_high * 100) if opening_high > 0 else 0.0
            prev_close = self._safe_float((prev_bar or {}).get("close", close), close)
            prev_vwap = self._safe_float((prev_bar or {}).get("vwap", vwap), vwap)
            return (
                min_pullback_pct <= pullback_pct <= max_pullback_pct
                and prev_close <= prev_vwap * 1.001
                and close >= vwap * 1.001
                and close >= opening_high * 0.997
                and close >= opening_low * 1.003
                and self._safe_float(bar.get("volume_surge_ratio", 0), 0) >= vol_thr
                and self._safe_float(bar.get("macd_hist", 0), 0) >= 0
                and self._safe_float(bar.get("anchor_return_pct", 0), 0) >= 1.0
            )

        def exit_rule(bar, _prev_bar, _idx, _session, _profile, state, avg_cost):
            if avg_cost <= 0:
                return False
            close = self._safe_float(bar.get("close", 0), 0)
            vwap = self._safe_float(bar.get("vwap", 0), 0)
            opening_low = self._safe_float(state.get("opening_low", 0), 0)
            return (
                close >= avg_cost * (1 + tp_pct / 100)
                or close <= avg_cost * (1 - sl_pct / 100)
                or close < vwap * 0.996
                or (opening_low > 0 and close < opening_low * 0.999)
            )

        return self._simulate_single_position_session_advanced(session, seed, "us_opening_reclaim", profile, entry_rule, exit_rule)

    def _simulate_us_premarket_session(self, session, seed, profile):
        """US 프리마켓 갭업 하따 전략 시뮬레이션.
        - 갭 = (첫 봉 open - prev_close) / prev_close %  (∵ prepost=True 시 프리마켓 첫 봉)
        - 진입 조건: gap >= premarket_gap_min AND entry_drawdown_min <= drawdown_from_day_high <= entry_drawdown_max
        - 청산 조건: +take_profit_pct OR -stop_loss_pct, 또는 장 마감 강제청산
        """
        bars = session.get("bars", [])
        prev_close = session.get("prev_close", 0)
        if not bars:
            return self._summarize_session(session, seed, [], 0.0, [seed], "us_premarket", {}, holding_minutes=0)

        first_open = self._safe_float(bars[0].get("open", 0), 0)
        if prev_close <= 0:
            prev_close = first_open
        gap_pct = (first_open - prev_close) / prev_close * 100 if prev_close > 0 else 0

        premarket_gap_min = self._safe_float(profile.get("premarket_gap_min_pct", 3.0), 3.0)
        entry_drawdown_min = self._safe_float(profile.get("entry_drawdown_min_pct", 2.0), 2.0)
        entry_drawdown_max = self._safe_float(profile.get("entry_drawdown_max_pct", 10.0), 10.0)
        take_profit_pct = self._safe_float(profile.get("jackpot_take_profit_pct", 3.0), 3.0)
        stop_loss_pct = self._safe_float(profile.get("stop_loss_pct", 8.0), 8.0)

        # 클로저로 day high 추적
        state = {"day_high": first_open}

        def entry_rule(bar, _s, p):
            high = self._safe_float(bar.get("high", 0), 0)
            close = self._safe_float(bar.get("close", 0), 0)
            state["day_high"] = max(state["day_high"], high)
            if gap_pct < premarket_gap_min or state["day_high"] <= 0:
                return False
            drawdown = (state["day_high"] - close) / state["day_high"] * 100
            return entry_drawdown_min <= drawdown <= entry_drawdown_max

        def exit_rule(bar, _s, p, avg_cost):
            if avg_cost <= 0:
                return False
            close = self._safe_float(bar.get("close", 0), 0)
            pnl_pct = (close - avg_cost) / avg_cost * 100
            return pnl_pct >= take_profit_pct or pnl_pct <= -stop_loss_pct

        return self._simulate_single_position_session(session, seed, "us_premarket", profile, entry_rule, exit_rule)

    def simulate_session(self, session, seed, profile=None, strategy_id="vrev"):
        strategy_id = self._normalize_strategy(strategy_id)
        profile = {**self._default_profile_for_market("US" if strategy_id.startswith("us_") else "KS", strategy_id=strategy_id), **(profile or {})}
        if strategy_id == "vrev":
            return self._simulate_vrev_session(session, seed, profile=profile)
        if strategy_id == "volume_breakout":
            return self._simulate_volume_breakout_session(session, seed, profile=profile)
        if strategy_id == "us_premarket":
            return self._simulate_us_premarket_session(session, seed, profile)
        if strategy_id == "us_breakout":
            return self._simulate_us_breakout_session(session, seed, profile)
        if strategy_id == "us_pullback":
            return self._simulate_us_pullback_session(session, seed, profile)
        if strategy_id == "us_vwap":
            return self._simulate_us_vwap_session(session, seed, profile)
        if strategy_id == "us_opening_reclaim":
            return self._simulate_us_opening_reclaim_session(session, seed, profile)
        # 알 수 없는 전략 → 홀드만 하는 더미
        return self._summarize_session(session, seed, [], 0.0, [seed], strategy_id, {}, holding_minutes=0)

    def _summarize_backtest(self, session_results, seed, symbol, market, period, interval, profile, strategy_id):
        equity_curve = [round(seed, 2)]
        peak = seed
        max_drawdown = 0.0
        total_profit = 0.0
        wins = 0
        total_trades = 0
        total_turnover = 0.0
        total_fees = 0.0
        total_holding = 0.0
        gross_profit = 0.0
        gross_loss = 0.0
        custom_metrics_agg = {
            "breakout_sustain_rate": [],
            "opening_volatility_pct": [],
            "volume_sustainability": [],
        }

        for result in session_results:
            total_profit += self._safe_float(result.get("net_profit", result.get("profit", 0)), 0)
            total_trades += self._safe_int(result.get("trade_count", 0), 0)
            total_turnover += self._safe_float(result.get("turnover", 0), 0)
            total_fees += self._safe_float(result.get("fees", 0), 0)
            total_holding += self._safe_float(result.get("avg_holding_minutes", 0), 0)
            gross_profit += self._safe_float(result.get("gross_profit", 0), 0)
            gross_loss += self._safe_float(result.get("gross_loss", 0), 0)
            if self._safe_float(result.get("net_profit", result.get("profit", 0)), 0) > 0:
                wins += 1
            
            if "custom_metrics" in result:
                for key in custom_metrics_agg:
                    if key in result["custom_metrics"]:
                        custom_metrics_agg[key].append(result["custom_metrics"][key])

            current_equity = seed + total_profit
            equity_curve.append(round(current_equity, 2))
            peak = max(peak, current_equity)
            if peak > 0:
                dd = (peak - current_equity) / peak * 100
                max_drawdown = max(max_drawdown, dd)
        day_count = len(session_results)
        total_return = (total_profit / seed * 100) if seed > 0 else 0
        avg_profit = total_profit / day_count if day_count > 0 else 0
        win_rate = (wins / day_count * 100) if day_count > 0 else 0
        avg_trades = total_trades / day_count if day_count > 0 else 0
        turnover_ratio = (total_turnover / seed) if seed > 0 else 0
        avg_holding = total_holding / day_count if day_count > 0 else 0
        sell_events = sum(len([t for t in result.get("trades", []) if t.get("side") == "SELL"]) for result in session_results)
        profit_factor = (gross_profit / abs(gross_loss)) if gross_loss < 0 else (gross_profit if gross_profit > 0 else 0)
        avg_win = (gross_profit / sell_events) if sell_events > 0 and gross_profit > 0 else 0
        loss_count = len([1 for result in session_results for t in result.get("trades", []) if t.get("side") == "SELL" and self._safe_float(t.get("pnl", 0), 0) < 0])
        avg_loss = (gross_loss / loss_count) if loss_count > 0 else 0
        
        summary = {
            "symbol": symbol,
            "market": market,
            "period": period,
            "interval": interval,
            "seed": round(seed, 2),
            "strategy_id": strategy_id,
            "strategy_name": self.strategy_spec(strategy_id).get("name", strategy_id),
            "day_count": day_count,
            "total_profit": round(total_profit, 2),
            "net_profit_after_fee": round(total_profit, 2),
            "total_return": round(total_return, 4),
            "avg_profit": round(avg_profit, 2),
            "win_rate": round(win_rate, 2),
            "max_drawdown": round(max_drawdown, 4),
            "avg_trades": round(avg_trades, 2),
            "turnover_ratio": round(turnover_ratio, 4),
            "total_turnover": round(total_turnover, 2),
            "fee_total": round(total_fees, 2),
            "profit_factor": round(profit_factor, 4),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "avg_holding_minutes": round(avg_holding, 2),
            "score": 0, # will be calculated later
            "final_equity": round(seed + total_profit, 2),
        }

        # Calculate score with custom metrics if available
        score = round(total_return - (max_drawdown * 0.8) + (win_rate * 0.12) + (min(profit_factor, 4.0) * 0.6) - (avg_trades * 0.35) - (turnover_ratio * 0.1), 4)
        
        if strategy_id == "volume_breakout":
            avg_sustain_rate = sum(custom_metrics_agg["breakout_sustain_rate"]) / len(custom_metrics_agg["breakout_sustain_rate"]) if custom_metrics_agg["breakout_sustain_rate"] else 0
            avg_opening_volatility = sum(custom_metrics_agg["opening_volatility_pct"]) / len(custom_metrics_agg["opening_volatility_pct"]) if custom_metrics_agg["opening_volatility_pct"] else 0
            avg_volume_sustainability = sum(custom_metrics_agg["volume_sustainability"]) / len(custom_metrics_agg["volume_sustainability"]) if custom_metrics_agg["volume_sustainability"] else 0
            
            summary["custom_metrics"] = {
                "avg_breakout_sustain_rate": round(avg_sustain_rate, 2),
                "avg_opening_volatility_pct": round(avg_opening_volatility, 2),
                "avg_volume_sustainability": round(avg_volume_sustainability, 2),
            }

            # Add custom metrics to score
            score += (avg_sustain_rate * 0.1)
            score -= (avg_opening_volatility * 0.05)
            score += (avg_volume_sustainability * 0.08)

        summary["score"] = round(score, 4)

        return {
            "summary": summary,
            "sessions": session_results,
            "equity_curve": equity_curve,
            "profile": profile,
        }

    def _selection_score(self, summary_score, validation_score, graph_score=0):
        return round(
            (self._safe_float(summary_score, 0) * 0.45)
            + (self._safe_float(validation_score, 0) * 0.35)
            + (self._safe_float(graph_score, 0) * 0.20),
            4,
        )

    def _graph_validation_metrics(self, walk_forward, validation_summary=None):
        folds = [row for row in (walk_forward or []) if isinstance(row, dict)]
        if len(folds) == 0:
            return {
                "fold_count": 0,
                "holdout_folds": 0,
                "holdout_graph": [],
                "positive_fold_ratio": 0.0,
                "negative_fold_ratio": 0.0,
                "return_swing_pct": 0.0,
                "return_stdev_pct": 0.0,
                "holdout_avg_return": 0.0,
                "holdout_positive_ratio": 0.0,
                "stability_score": 0.0,
            }
        returns = [self._safe_float(row.get("validation_return", 0), 0) for row in folds]
        holdout_count = min(
            max(1, self._safe_int(self._config("daytrade_graph_validation_holdout_folds", "2"), 2)),
            len(folds),
        )
        holdout_graph = folds[-holdout_count:]
        holdout_returns = [self._safe_float(row.get("validation_return", 0), 0) for row in holdout_graph]
        positive_ratio = len([x for x in returns if x > 0]) / len(returns) if len(returns) > 0 else 0.0
        negative_ratio = len([x for x in returns if x < 0]) / len(returns) if len(returns) > 0 else 0.0
        holdout_positive_ratio = len([x for x in holdout_returns if x > 0]) / len(holdout_returns) if len(holdout_returns) > 0 else 0.0
        holdout_avg_return = sum(holdout_returns) / len(holdout_returns) if len(holdout_returns) > 0 else 0.0
        return_swing_pct = (max(returns) - min(returns)) if len(returns) > 0 else 0.0
        return_mean = sum(returns) / len(returns) if len(returns) > 0 else 0.0
        return_stdev_pct = math.sqrt(sum((x - return_mean) ** 2 for x in returns) / len(returns)) if len(returns) > 0 else 0.0
        validation_summary = validation_summary or {}
        validation_profit_factor = min(self._safe_float(validation_summary.get("profit_factor", 0), 0), 4.0)
        validation_mdd = abs(self._safe_float(validation_summary.get("max_drawdown", 0), 0))
        stability_score = (
            (holdout_avg_return * 0.55)
            + (positive_ratio * 5.0)
            + (holdout_positive_ratio * 3.0)
            - (negative_ratio * 7.0)
            - (return_swing_pct * 0.32)
            - (return_stdev_pct * 0.45)
            + (validation_profit_factor * 0.15)
            - (validation_mdd * 0.08)
        )
        return {
            "fold_count": len(folds),
            "holdout_folds": holdout_count,
            "holdout_graph": holdout_graph,
            "positive_fold_ratio": round(positive_ratio, 4),
            "negative_fold_ratio": round(negative_ratio, 4),
            "return_swing_pct": round(return_swing_pct, 4),
            "return_stdev_pct": round(return_stdev_pct, 4),
            "holdout_avg_return": round(holdout_avg_return, 4),
            "holdout_positive_ratio": round(holdout_positive_ratio, 4),
            "stability_score": round(stability_score, 4),
        }

    def _validation_report(self, sessions, symbol, market, period, interval, seed, profile, strategy_id):
        if len(sessions) < 3:
            return {
                "split": "insufficient_sessions",
                "train": None,
                "validation": None,
                "walk_forward": [],
                "graph_validation": self._graph_validation_metrics([], None),
                "robustness_score": 0.0,
            }
        split_idx = max(2, len(sessions) // 2)
        train_sessions = sessions[:split_idx]
        valid_sessions = sessions[split_idx:]
        train = self._backtest_sessions(train_sessions, symbol, market=market, period=period, interval=interval, seed=seed, profile=profile, strategy_id=strategy_id, include_validation=False)
        valid = self._backtest_sessions(valid_sessions, symbol, market=market, period=period, interval=interval, seed=seed, profile=profile, strategy_id=strategy_id, include_validation=False)
        walk_forward = []
        for idx in range(split_idx, len(sessions)):
            fold_train = sessions[:idx]
            fold_valid = [sessions[idx]]
            train_fold = self._backtest_sessions(fold_train, symbol, market=market, period=period, interval=interval, seed=seed, profile=profile, strategy_id=strategy_id, include_validation=False)
            valid_fold = self._backtest_sessions(fold_valid, symbol, market=market, period=period, interval=interval, seed=seed, profile=profile, strategy_id=strategy_id, include_validation=False)
            walk_forward.append({
                "fold": len(walk_forward) + 1,
                "train_end": fold_train[-1].get("date", "") if fold_train else "",
                "validation_date": fold_valid[0].get("date", "") if fold_valid else "",
                "train_score": train_fold.get("summary", {}).get("score", 0),
                "validation_score": valid_fold.get("summary", {}).get("score", 0),
                "validation_return": valid_fold.get("summary", {}).get("total_return", 0),
            })
        train_score = self._safe_float(train.get("summary", {}).get("score", 0), 0)
        valid_score = self._safe_float(valid.get("summary", {}).get("score", 0), 0)
        train_return = self._safe_float(train.get("summary", {}).get("total_return", 0), 0)
        valid_return = self._safe_float(valid.get("summary", {}).get("total_return", 0), 0)
        overfit_gap = abs(train_return - valid_return)
        robustness_score = round((valid_score * 0.7) + (train_score * 0.3) - (overfit_gap * 0.45), 4)
        graph_validation = self._graph_validation_metrics(walk_forward, valid.get("summary", {}))
        return {
            "split": f"{len(train_sessions)}:{len(valid_sessions)}",
            "train": train.get("summary", {}),
            "validation": valid.get("summary", {}),
            "walk_forward": walk_forward,
            "graph_validation": graph_validation,
            "robustness_score": robustness_score,
            "overfit_gap": round(overfit_gap, 4),
        }

    def _backtest_sessions(self, sessions, symbol, market="KS", period="5d", interval="1m", seed=5000000, profile=None, strategy_id="vrev", include_validation=True):
        seed = self._normalized_seed(seed, self.DEFAULT_SEED)
        profile = {**self._default_profile_for_market(market=market, strategy_id=strategy_id), **(profile or {})}
        strategy_id = self._normalize_strategy(strategy_id)
        session_results = []
        rolling_seed = seed
        for session in sessions:
            result = self.simulate_session(session, rolling_seed, profile=profile, strategy_id=strategy_id)
            session_results.append(result)
            compound_factor = self._safe_float(profile.get("compound_factor", 0.35), 0.35)
            rolling_seed = max(0, rolling_seed + (result.get("net_profit", result.get("profit", 0)) * compound_factor))
        payload = self._summarize_backtest(session_results, seed, symbol, market, period, interval, profile, strategy_id)
        if include_validation:
            payload["validation"] = self._validation_report(sessions, symbol, market, period, interval, seed, profile, strategy_id)
        return payload

    def backtest(self, symbol, market="KS", period="5d", interval="1m", seed=5000000, profile=None, strategy_id="vrev"):
        seed = self._normalized_seed(seed, self.DEFAULT_SEED)
        sessions = self._prepare_dataset(symbol, market=market, period=period, interval=interval)
        return self._backtest_sessions(sessions, symbol, market=market, period=period, interval=interval, seed=seed, profile=profile, strategy_id=strategy_id)

    # =========================================================================
    # Optimization
    # =========================================================================

    def _profile_grid(self, strategy_id="vrev"):
        strategy_id = self._normalize_strategy(strategy_id)
        if strategy_id == "volume_breakout":
            return {
                "breakout_volume_ratio": [1.5, 1.8, 2.2],
                "breakout_take_profit_pct": [1.0, 1.4, 1.8],
                "breakout_stop_loss_pct": [0.6, 0.8, 1.0],
                "budget_ratio": [1.0],
            }
        if strategy_id == "us_premarket":
            return {
                "premarket_gap_min_pct": [1.5, 2.5, 4.0],
                "entry_drawdown_min_pct": [0.0, 0.3, 0.8],
                "entry_drawdown_max_pct": [3.0, 6.0, 12.0],
                "jackpot_take_profit_pct": [1.5, 2.5, 4.0],
                "stop_loss_pct": [3.0, 6.0, 10.0],
            }
        if strategy_id == "us_breakout":
            return {
                "breakout_volume_ratio": [2.0, 2.5, 3.0],
                "breakout_take_profit_pct": [2.5, 4.0, 5.5],
                "breakout_stop_loss_pct": [1.8, 2.5, 3.5],
                "budget_ratio": [1.0],
            }
        if strategy_id == "us_pullback":
            return {
                "breakout_volume_ratio": [1.2, 1.5, 1.8],
                "breakout_take_profit_pct": [2.5, 3.5, 4.5],
                "breakout_stop_loss_pct": [1.5, 2.2, 3.0],
                "min_prior_surge_pct": [6.0, 8.0, 10.0],
                "entry_drawdown_min_pct": [1.5, 2.0, 2.5],
                "entry_drawdown_max_pct": [4.0, 6.0, 8.0],
                "budget_ratio": [1.0],
            }
        if strategy_id == "us_vwap":
            return {
                "breakout_volume_ratio": [1.4, 1.8, 2.2],
                "breakout_take_profit_pct": [2.5, 3.5, 4.5],
                "breakout_stop_loss_pct": [1.5, 2.0, 2.5],
                "budget_ratio": [1.0],
            }
        if strategy_id == "us_opening_reclaim":
            return {
                "breakout_volume_ratio": [1.5, 1.8, 2.2],
                "breakout_take_profit_pct": [3.0, 3.8, 4.5],
                "breakout_stop_loss_pct": [1.2, 1.8, 2.2],
                "entry_drawdown_min_pct": [0.8, 1.2, 1.8],
                "entry_drawdown_max_pct": [2.5, 3.5, 4.5],
                "budget_ratio": [1.0],
            }
        # vrev 기본 그리드
        return {
            "buy_trigger_1_pct": [0.0, -0.1, -0.2],
            "jackpot_take_profit_pct": [1.5, 2.0, 2.5],
            "stop_loss_pct": [1.2, 1.5, 2.0],
            "rsi_exit_overbought": [70, 75, 80],
            "budget_ratio": [1.0],
        }

    def _optimize_payload(self, symbol, market="KS", period="5d", interval="1m", seed=5000000, strategy_id="vrev"):
        seed = self._normalized_seed(seed, self.DEFAULT_SEED)
        strategy_id = self._normalize_strategy(strategy_id)
        grid = self._profile_grid(strategy_id)
        keys = list(grid.keys())
        results = []
        sessions = self._prepare_dataset(symbol, market=market, period=period, interval=interval)
        base_profile = self._default_profile_for_market(market=market, strategy_id=strategy_id)
        baseline = self._backtest_sessions(sessions, symbol, market=market, period=period, interval=interval, seed=seed, profile=base_profile, strategy_id=strategy_id)
        for values in itertools.product(*[grid[k] for k in keys]):
            profile = {**base_profile, **dict(zip(keys, values))}
            result = self._backtest_sessions(sessions, symbol, market=market, period=period, interval=interval, seed=seed, profile=profile, strategy_id=strategy_id)
            summary = result.get("summary", {})
            validation = result.get("validation", {})
            validation_score = self._safe_float(validation.get("robustness_score", summary.get("score", 0)), summary.get("score", 0))
            graph_validation = validation.get("graph_validation", {}) or {}
            graph_score = self._safe_float(graph_validation.get("stability_score", 0), 0)
            results.append({
                "strategy_id": strategy_id,
                "profile": profile,
                "summary": summary,
                "validation": validation,
                "selection_score": self._selection_score(summary.get("score", 0), validation_score, graph_score),
            })
        results.sort(key=lambda x: x.get("selection_score", -999999), reverse=True)
        baseline_summary = baseline.get("summary", {}) or {}
        baseline_validation = baseline.get("validation", {}) or {}
        baseline_validation_score = self._safe_float(baseline_validation.get("robustness_score", baseline_summary.get("score", 0)), baseline_summary.get("score", 0))
        baseline_graph_score = self._safe_float((baseline_validation.get("graph_validation", {}) or {}).get("stability_score", 0), 0)
        best = results[0] if len(results) > 0 else {"strategy_id": strategy_id, "profile": base_profile, "summary": baseline_summary, "validation": baseline_validation, "selection_score": self._selection_score(baseline_summary.get("score", 0), baseline_validation_score, baseline_graph_score)}
        payload = {
            "generated_at": self._now().strftime("%Y-%m-%d %H:%M:%S"),
            "symbol": symbol, "market": market, "period": period, "interval": interval, "strategy_id": strategy_id,
            "seed": seed,
            "criteria": {"score_formula": "summary_score*0.45 + robustness_score*0.35 + graph_stability_score*0.20", "focus": ["순수익률", "MDD", "승률", "회전율", "보유시간", "수수료 차감 순이익", "그래프 홀드아웃 안정성"]},
            "baseline": baseline, "best": best, "top_candidates": results[:5],
            "strategy_spec": self.strategy_spec(strategy_id),
        }
        return payload

    def optimize(self, symbol, market="KS", period="5d", interval="1m", seed=5000000, strategy_id="vrev"):
        seed = self._normalized_seed(seed, self.DEFAULT_SEED)
        payload = self._optimize_payload(symbol, market=market, period=period, interval=interval, seed=seed, strategy_id=strategy_id)
        self._write_training_artifacts(payload)
        return payload

    # =========================================================================
    # Auto Train + Recommend
    # =========================================================================

    def recommend(self, seed=5000000, force=False, strategy_id="", price_cap=0, max_age_sec=0, market="KS"):
        requested_seed = self._normalized_seed(seed, self.DEFAULT_SEED)
        training_seed = self._normalized_seed(requested_seed, requested_seed)
        price_cap = self._safe_float(price_cap, self._recommendation_price_cap(requested_seed))
        market = str(market or "KS").upper()
        if not force:
            cached = self.latest_recommendation(seed=requested_seed, strategy_id=strategy_id, price_cap=price_cap, max_age_sec=max_age_sec, market=market)
            cached_strategy = cached.get("selected", {}).get("strategy_id") if cached else None
            cached_market = str(cached.get("selected", {}).get("market", "KS") if cached else "KS").upper()
            if cached and cached_strategy and cached_market == market and (strategy_id == "" or cached_strategy == self._normalize_strategy(strategy_id)):
                return cached
            relaxed_cached = self.latest_recommendation(allow_stale_day=True, market=market)
            if relaxed_cached:
                return self._recommendation_price_filter(relaxed_cached, strategy_id=strategy_id, price_cap=price_cap, market=market)
        try:
            return self.auto_train(seed=training_seed, requested_seed=requested_seed, strategy_id=strategy_id, price_cap=price_cap, market=market)
        except Exception as e:
            result = self._fallback_recommendation(seed=requested_seed, strategy_id=strategy_id, market=market, reason=f"학습 실패로 기본 종목을 유지합니다: {str(e)}")
            result["cache_key"] = self._recommendation_cache_key(seed=requested_seed, strategy_id=strategy_id, price_cap=price_cap, market=market)
            result["requested_seed"] = round(requested_seed, 2)
            result["training_seed"] = round(training_seed, 2)
            result["price_cap_krw"] = round(price_cap, 2)
            result["market"] = market
            self._save_recommendation(result, market=market)
            return result

    def auto_train(self, seed=0, requested_seed=0, strategy_id="", price_cap=0, market="KS"):
        """
        단타 추천 모델 자동 훈련 및 최적화
        - market: "KS" (기본값) 또는 "US"
        """
        is_us_market = str(market).upper() == "US"
        defaults = self.us_defaults() if is_us_market else self.defaults()
        seed = self._normalized_seed(seed, defaults.get("seed"))
        requested_seed = self._normalized_seed(requested_seed or seed, seed)
        candidates = self.candidate_universe(market=market)
        training_defaults = self.recommendation_training_defaults()
        period = training_defaults.get("period", "10d")
        interval = training_defaults.get("interval", "5m")
        min_sessions = training_defaults.get("min_session_count", 6)
        effective_price_cap = self._safe_float(price_cap, self._recommendation_price_cap(seed))
        allowed_strategies = []
        for sid, spec in self.STRATEGIES.items():
            if not spec.get("live_supported"):
                continue
            strategy_market = spec.get("market", "KS").upper()
            if is_us_market:
                if strategy_market == "US":
                    allowed_strategies.append(sid)
            else:
                if strategy_market == "KS":
                    allowed_strategies.append(sid)

        if strategy_id:
            normalized_strategy = self._normalize_strategy(strategy_id)
            if normalized_strategy in allowed_strategies:
                allowed_strategies = [normalized_strategy]

        if not allowed_strategies:
            return self._empty_recommendation(cache_key=self._recommendation_cache_key(seed=seed, strategy_id=strategy_id, price_cap=effective_price_cap, market=market))
        cache_key = self._recommendation_cache_key(seed=seed, strategy_id=strategy_id, price_cap=effective_price_cap, market=market)
        leaderboard = []
        errors = []
        profile_book_updates = {}
        best_payload = None
        ks_min_live_win_rate = max(0.0, self._safe_float(self._config("daytrade_ks_min_live_win_rate", "40"), 40))
        ks_min_validation_win_rate = max(0.0, self._safe_float(self._config("daytrade_ks_min_validation_win_rate", "50"), 50))
        ks_min_avg_trades = max(0.0, self._safe_float(self._config("daytrade_ks_min_avg_trades", "3.0"), 3.0))
        ks_min_validation_avg_trades = max(0.0, self._safe_float(self._config("daytrade_ks_min_validation_avg_trades", "2.0"), 2.0))
        ks_max_drawdown = max(0.0, self._safe_float(self._config("daytrade_ks_max_drawdown_pct", "18"), 18))
        ks_max_overfit_gap = max(0.0, self._safe_float(self._config("daytrade_ks_max_overfit_gap_pct", "15"), 15))
        ks_min_profit_factor = max(0.0, self._safe_float(self._config("daytrade_ks_min_profit_factor", "1.25"), 1.25))
        ks_min_validation_profit_factor = max(0.0, self._safe_float(self._config("daytrade_ks_min_validation_profit_factor", "1.25"), 1.25))
        ks_min_avg_profit_krw = max(0.0, self._safe_float(self._config("daytrade_ks_min_avg_profit_krw", "25000"), 25000))
        ks_min_validation_avg_profit_krw = max(0.0, self._safe_float(self._config("daytrade_ks_min_validation_avg_profit_krw", "20000"), 20000))
        ks_min_graph_holdout_return = self._safe_float(self._config("daytrade_ks_min_graph_holdout_return_pct", "0.5"), 0.5)
        ks_max_graph_negative_fold_ratio = min(1.0, max(0.0, self._safe_float(self._config("daytrade_ks_max_graph_negative_fold_ratio", "0.34"), 0.34)))
        ks_max_graph_return_swing = max(0.0, self._safe_float(self._config("daytrade_ks_max_graph_return_swing_pct", "8.0"), 8.0))
        us_min_live_win_rate = max(0.0, self._safe_float(self._config("daytrade_us_min_live_win_rate", "35"), 35))
        us_min_validation_win_rate = max(0.0, self._safe_float(self._config("daytrade_us_min_validation_win_rate", "40"), 40))
        us_min_avg_trades = max(0.0, self._safe_float(self._config("daytrade_us_min_avg_trades", "0.8"), 0.8))
        us_min_validation_avg_trades = max(0.0, self._safe_float(self._config("daytrade_us_min_validation_avg_trades", "0.8"), 0.8))
        us_min_validation_return = self._safe_float(self._config("daytrade_us_min_validation_return_pct", "1.5"), 1.5)
        us_max_drawdown = max(0.0, self._safe_float(self._config("daytrade_us_max_drawdown_pct", "14"), 14))
        us_max_overfit_gap = max(0.0, self._safe_float(self._config("daytrade_us_max_overfit_gap_pct", "10"), 10))
        us_min_profit_factor = max(0.0, self._safe_float(self._config("daytrade_us_min_profit_factor", "1.15"), 1.15))
        us_min_validation_profit_factor = max(0.0, self._safe_float(self._config("daytrade_us_min_validation_profit_factor", "1.2"), 1.2))
        us_min_liquidity_score = max(0.0, self._safe_float(self._config("daytrade_us_min_liquidity_score", "0.8"), 0.8))
        us_min_tradability_score = max(0.0, self._safe_float(self._config("daytrade_us_min_tradability_score", "6.0"), 6.0))
        us_min_graph_holdout_return = self._safe_float(self._config("daytrade_us_min_graph_holdout_return_pct", "0.0"), 0.0)
        us_max_graph_negative_fold_ratio = min(1.0, max(0.0, self._safe_float(self._config("daytrade_us_max_graph_negative_fold_ratio", "0.5"), 0.5)))
        us_max_graph_return_swing = max(0.0, self._safe_float(self._config("daytrade_us_max_graph_return_swing_pct", "12.0"), 12.0))

        for candidate in candidates:
            symbol = str(candidate.get("symbol", "") or "").strip().upper()
            if symbol == "":
                continue
            try:
                sessions = self._prepare_dataset(symbol, market=market, period=period, interval=interval)
            except Exception as e:
                errors.append({"symbol": symbol, "name": candidate.get("name", ""), "market": market, "error": str(e)})
                continue
            if len(sessions) < min_sessions:
                errors.append({"symbol": symbol, "name": candidate.get("name", ""), "market": market, "error": f"학습 세션 부족 ({len(sessions)} < {min_sessions})"})
                continue
            try:
                volatility = self._volatility_from_sessions(sessions)
                if sessions and sessions[-1].get("bars"):
                    volatility["last_price"] = self._safe_float(sessions[-1]["bars"][-1].get("close", 0), 0)
            except Exception as e:
                errors.append({"symbol": symbol, "name": candidate.get("name", ""), "market": market, "error": f"변동성 계산 실패: {str(e)}"})
                continue
            last_price = self._safe_float(volatility.get("last_price", 0), 0)
            if not is_us_market and effective_price_cap > 0 and last_price > 0 and last_price > effective_price_cap:
                continue
            if last_price <= 0:
                errors.append({"symbol": symbol, "name": candidate.get("name", ""), "market": market, "error": "현재가 계산 실패"})
                continue
            for sid in allowed_strategies:
                try:
                    payload = self._optimize_payload(symbol, market=market, period=period, interval=interval, seed=seed, strategy_id=sid)
                    best = payload.get("best", {}) or {}
                    summary = best.get("summary", {}) or {}
                    validation = best.get("validation", {}) or {}
                    selection_score = self._safe_float(best.get("selection_score", summary.get("score", 0)), 0)
                    total_return = self._safe_float(summary.get("total_return", 0), 0)
                    win_rate = self._safe_float(summary.get("win_rate", 0), 0)
                    max_drawdown = self._safe_float(summary.get("max_drawdown", 0), 0)
                    avg_trades = self._safe_float(summary.get("avg_trades", 0), 0)
                    profit_factor = self._safe_float(summary.get("profit_factor", 0), 0)
                    robustness = self._safe_float(validation.get("robustness_score", 0), 0)
                    validation_summary = validation.get("validation", {}) or {}
                    validation_return = self._safe_float(validation_summary.get("total_return", 0), 0)
                    validation_win_rate = self._safe_float(validation_summary.get("win_rate", 0), 0)
                    validation_avg_trades = self._safe_float(validation_summary.get("avg_trades", 0), 0)
                    validation_profit_factor = self._safe_float(validation_summary.get("profit_factor", 0), 0)
                    avg_profit = self._safe_float(summary.get("avg_profit", 0), 0)
                    validation_avg_profit = self._safe_float(validation_summary.get("avg_profit", 0), 0)
                    overfit_gap = self._safe_float(validation.get("overfit_gap", 0), 0)
                    graph_validation = validation.get("graph_validation", {}) or {}
                    graph_stability = self._safe_float(graph_validation.get("stability_score", 0), 0)
                    graph_holdout_return = self._safe_float(graph_validation.get("holdout_avg_return", 0), 0)
                    graph_negative_fold_ratio = self._safe_float(graph_validation.get("negative_fold_ratio", 0), 0)
                    graph_return_swing = self._safe_float(graph_validation.get("return_swing_pct", 0), 0)
                    best_profile = dict(best.get("profile", {}) or {})
                    trend_snapshot = self._trend_alignment_snapshot(sessions[-1], profile=best_profile)
                    trend_alignment_score = self._safe_float(trend_snapshot.get("trend_alignment_score", 0), 0)
                    min_trend_alignment_score = self._min_trend_alignment_score(sid, profile=best_profile)
                    rank_score = selection_score
                    if is_us_market:
                        rank_score = (
                            (validation_return * 0.34)
                            + (total_return * 0.12)
                            + (validation_win_rate * 0.12)
                            + (win_rate * 0.06)
                            - (abs(max_drawdown) * 0.10)
                            + (robustness * 0.16)
                            - (abs(overfit_gap) * 0.10)
                            + (selection_score * 0.04)
                            + (min(validation_profit_factor, 4.0) * 0.08)
                            + (min(profit_factor, 4.0) * 0.04)
                            + (min(validation_avg_profit / 10000.0, 5.0) * 0.10)
                            + (min(avg_profit / 10000.0, 5.0) * 0.05)
                            + (self._safe_float(volatility.get("liquidity_score", 0), 0) * 0.05)
                            + (self._safe_float(volatility.get("tradability_score", 0), 0) * 0.12)
                            + (trend_alignment_score * 2.5)
                            + (graph_stability * 0.45)
                        )
                    else:
                        rank_score = (
                            (validation_return * 0.34)
                            + (total_return * 0.18)
                            + (validation_win_rate * 0.18)
                            + (win_rate * 0.08)
                            + (robustness * 0.12)
                            + (min(validation_profit_factor, 4.0) * 0.05)
                            + (min(profit_factor, 4.0) * 0.03)
                            + (min(avg_trades, 12.0) * 0.05)
                            + (min(validation_avg_trades, 12.0) * 0.05)
                            + (min(validation_avg_profit / 10000.0, 5.0) * 0.18)
                            + (min(avg_profit / 10000.0, 5.0) * 0.08)
                            - (abs(max_drawdown) * 0.08)
                            - (abs(overfit_gap) * 0.06)
                            + (self._safe_float(volatility.get("tradability_score", 0), 0) * 0.04)
                            + (trend_alignment_score * 6.0)
                            + (graph_stability * 0.70)
                        )
                    quality_issues = []
                    if is_us_market:
                        if validation_return < us_min_validation_return:
                            quality_issues.append(f"검증 수익률 {validation_return:.2f}%")
                        if robustness <= 0:
                            quality_issues.append(f"견고성 {robustness:.2f}")
                        if abs(overfit_gap) > us_max_overfit_gap:
                            quality_issues.append(f"과최적화 격차 {overfit_gap:.2f}")
                        if abs(max_drawdown) > us_max_drawdown:
                            quality_issues.append(f"MDD {max_drawdown:.2f}%")
                        if profit_factor < us_min_profit_factor:
                            quality_issues.append(f"손익비 {profit_factor:.2f}")
                        if validation_profit_factor < us_min_validation_profit_factor:
                            quality_issues.append(f"검증 손익비 {validation_profit_factor:.2f}")
                        if win_rate < us_min_live_win_rate:
                            quality_issues.append(f"승률 {win_rate:.2f}%")
                        if validation_win_rate < us_min_validation_win_rate:
                            quality_issues.append(f"검증 승률 {validation_win_rate:.2f}%")
                        if avg_trades < us_min_avg_trades:
                            quality_issues.append(f"거래빈도 {avg_trades:.2f}/day")
                        if validation_avg_trades < us_min_validation_avg_trades:
                            quality_issues.append(f"검증 거래빈도 {validation_avg_trades:.2f}/day")
                        if self._safe_float(volatility.get("liquidity_score", 0), 0) < us_min_liquidity_score:
                            quality_issues.append(f"유동성 {self._safe_float(volatility.get('liquidity_score', 0), 0):.2f}")
                        if self._safe_float(volatility.get("tradability_score", 0), 0) < us_min_tradability_score:
                            quality_issues.append(f"체결성 {self._safe_float(volatility.get('tradability_score', 0), 0):.2f}")
                        if trend_alignment_score < min_trend_alignment_score:
                            quality_issues.append(f"현재 추세정합 {trend_alignment_score:.2f}")
                        if graph_holdout_return < us_min_graph_holdout_return:
                            quality_issues.append(f"그래프 검증 수익률 {graph_holdout_return:.2f}%")
                        if graph_negative_fold_ratio > us_max_graph_negative_fold_ratio:
                            quality_issues.append(f"그래프 음수 비중 {graph_negative_fold_ratio * 100:.1f}%")
                        if graph_return_swing > us_max_graph_return_swing:
                            quality_issues.append(f"그래프 변동폭 {graph_return_swing:.2f}%")
                    else:
                        if validation_return <= 0:
                            quality_issues.append(f"검증 수익률 {validation_return:.2f}%")
                        if robustness <= 0:
                            quality_issues.append(f"견고성 {robustness:.2f}")
                        if abs(overfit_gap) > ks_max_overfit_gap:
                            quality_issues.append(f"과최적화 격차 {overfit_gap:.2f}")
                        if abs(max_drawdown) > ks_max_drawdown:
                            quality_issues.append(f"MDD {max_drawdown:.2f}%")
                        if profit_factor < ks_min_profit_factor:
                            quality_issues.append(f"손익비 {profit_factor:.2f}")
                        if validation_profit_factor < ks_min_validation_profit_factor:
                            quality_issues.append(f"검증 손익비 {validation_profit_factor:.2f}")
                        if win_rate < ks_min_live_win_rate:
                            quality_issues.append(f"승률 {win_rate:.2f}%")
                        if validation_win_rate < ks_min_validation_win_rate:
                            quality_issues.append(f"검증 승률 {validation_win_rate:.2f}%")
                        if avg_trades < ks_min_avg_trades:
                            quality_issues.append(f"거래빈도 {avg_trades:.2f}/day")
                        if validation_avg_trades < ks_min_validation_avg_trades:
                            quality_issues.append(f"검증 거래빈도 {validation_avg_trades:.2f}/day")
                        if avg_profit < ks_min_avg_profit_krw:
                            quality_issues.append(f"일평균 수익 ₩{avg_profit:,.0f}")
                        if validation_avg_profit < ks_min_validation_avg_profit_krw:
                            quality_issues.append(f"검증 일평균 수익 ₩{validation_avg_profit:,.0f}")
                        if trend_alignment_score < min_trend_alignment_score:
                            quality_issues.append(f"현재 추세정합 {trend_alignment_score:.2f}")
                        if graph_holdout_return < ks_min_graph_holdout_return:
                            quality_issues.append(f"그래프 검증 수익률 {graph_holdout_return:.2f}%")
                        if graph_negative_fold_ratio > ks_max_graph_negative_fold_ratio:
                            quality_issues.append(f"그래프 음수 비중 {graph_negative_fold_ratio * 100:.1f}%")
                        if graph_return_swing > ks_max_graph_return_swing:
                            quality_issues.append(f"그래프 변동폭 {graph_return_swing:.2f}%")
                    row = {
                        "symbol": symbol,
                        "market": market,
                        "name": candidate.get("name", self._resolve_symbol_name(symbol)),
                        "strategy_id": sid,
                        "strategy_name": self.strategy_spec(sid).get("name", sid),
                        "score": round(selection_score, 4),
                        "rank_score": round(rank_score, 4),
                        "selection_score": round(selection_score, 4),
                        "total_return": round(total_return, 4),
                        "avg_profit": round(avg_profit, 2),
                        "win_rate": round(win_rate, 2),
                        "avg_trades": round(avg_trades, 2),
                        "max_drawdown": round(max_drawdown, 4),
                        "profit_factor": round(profit_factor, 4),
                        "avg_day_range_pct": round(self._safe_float(volatility.get("avg_day_range_pct", 0), 0), 4),
                        "avg_intraday_move_pct": round(self._safe_float(volatility.get("avg_intraday_move_pct", 0), 0), 4),
                        "avg_turnover_krw": round(self._safe_float(volatility.get("avg_turnover_krw", 0), 0), 2),
                        "liquidity_score": round(self._safe_float(volatility.get("liquidity_score", 0), 0), 4),
                        "tradability_score": round(self._safe_float(volatility.get("tradability_score", 0), 0), 4),
                        "last_price": round(last_price, 4),
                        "validation_robustness": round(self._safe_float(validation.get("robustness_score", 0), 0), 4),
                        "validation_return": round(validation_return, 4),
                        "validation_avg_profit": round(validation_avg_profit, 2),
                        "validation_profit_factor": round(validation_profit_factor, 4),
                        "validation_win_rate": round(validation_win_rate, 2),
                        "validation_avg_trades": round(validation_avg_trades, 2),
                        "graph_stability_score": round(graph_stability, 4),
                        "graph_holdout_return": round(graph_holdout_return, 4),
                        "graph_negative_fold_ratio": round(graph_negative_fold_ratio, 4),
                        "graph_return_swing_pct": round(graph_return_swing, 4),
                        "overfit_gap": round(overfit_gap, 4),
                        "trend_alignment_score": round(trend_alignment_score, 4),
                        "trend_snapshot": trend_snapshot,
                        "trade_ready": len(quality_issues) == 0,
                        "quality_issues": quality_issues,
                        "summary": summary,
                        "validation": validation,
                    }
                    leaderboard.append(row)
                    profile_book_updates[f"{symbol}:{sid}"] = {
                        "symbol": symbol,
                        "market": market,
                        "strategy_id": sid,
                        "updated_at": self._now().strftime("%Y-%m-%d %H:%M:%S"),
                        "profile": dict(best.get("profile", {}) or {}),
                        "summary": summary,
                        "validation": validation,
                    }
                    if best_payload is None or selection_score > self._safe_float(best_payload.get("best", {}).get("selection_score", -999999), -999999):
                        best_payload = payload
                        best_payload["best"]["selection_score"] = selection_score
                except Exception as e:
                    errors.append({"symbol": symbol, "name": candidate.get("name", ""), "market": market, "strategy_id": sid, "error": str(e)})

        leaderboard.sort(
            key=lambda x: (
                1 if x.get("trade_ready") else 0,
                self._safe_float(x.get("rank_score", x.get("selection_score", 0)), 0),
                self._safe_float(x.get("validation_robustness", 0), 0),
                self._safe_float(x.get("validation_return", 0), 0),
                self._safe_float(x.get("total_return", 0), 0),
                self._safe_float(x.get("win_rate", 0), 0),
            ),
            reverse=True,
        )

        if len(leaderboard) == 0:
            result = self._empty_recommendation(cache_key=cache_key, market=market, reason="학습 가능한 추천 후보가 없습니다.")
            result["requested_seed"] = round(requested_seed, 2)
            result["training_seed"] = round(seed, 2)
            result["price_cap_krw"] = round(effective_price_cap, 2)
            result["market"] = market
            result["errors"] = errors[:20]
            self._save_recommendation(result, market=market)
            return result

        selected_pool = leaderboard
        trade_ready_rows = [row for row in leaderboard if row.get("trade_ready")]
        if len(trade_ready_rows) > 0:
            selected_pool = trade_ready_rows
        selected = dict(selected_pool[0])
        quality_guard = self._build_quality_guard(leaderboard, training_defaults, market=market)
        tested_count = len(leaderboard)
        success_count = len([row for row in leaderboard if self._safe_float(row.get("total_return", 0), 0) > 0])
        aggregate = {
            "tested_count": tested_count,
            "success_rate": round((success_count / tested_count) * 100, 2) if tested_count > 0 else 0.0,
            "avg_total_return": round(sum(self._safe_float(row.get("total_return", 0), 0) for row in leaderboard) / tested_count, 4) if tested_count > 0 else 0.0,
            "avg_validation_return": round(sum(self._safe_float(row.get("validation_return", 0), 0) for row in leaderboard) / tested_count, 4) if tested_count > 0 else 0.0,
            "avg_avg_profit_krw": round(sum(self._safe_float(row.get("avg_profit", 0), 0) for row in leaderboard) / tested_count, 2) if tested_count > 0 else 0.0,
            "avg_validation_avg_profit_krw": round(sum(self._safe_float(row.get("validation_avg_profit", 0), 0) for row in leaderboard) / tested_count, 2) if tested_count > 0 else 0.0,
            "avg_win_rate": round(sum(self._safe_float(row.get("win_rate", 0), 0) for row in leaderboard) / tested_count, 2) if tested_count > 0 else 0.0,
            "avg_validation_win_rate": round(sum(self._safe_float(row.get("validation_win_rate", 0), 0) for row in leaderboard) / tested_count, 2) if tested_count > 0 else 0.0,
            "avg_trades": round(sum(self._safe_float(row.get("avg_trades", 0), 0) for row in leaderboard) / tested_count, 2) if tested_count > 0 else 0.0,
            "avg_validation_trades": round(sum(self._safe_float(row.get("validation_avg_trades", 0), 0) for row in leaderboard) / tested_count, 2) if tested_count > 0 else 0.0,
            "avg_graph_stability_score": round(sum(self._safe_float(row.get("graph_stability_score", 0), 0) for row in leaderboard) / tested_count, 4) if tested_count > 0 else 0.0,
            "avg_graph_holdout_return": round(sum(self._safe_float(row.get("graph_holdout_return", 0), 0) for row in leaderboard) / tested_count, 4) if tested_count > 0 else 0.0,
            "avg_graph_negative_fold_ratio": round(sum(self._safe_float(row.get("graph_negative_fold_ratio", 0), 0) for row in leaderboard) / tested_count, 4) if tested_count > 0 else 0.0,
            "avg_score": round(sum(self._safe_float(row.get("score", 0), 0) for row in leaderboard) / tested_count, 4) if tested_count > 0 else 0.0,
            "avg_day_range_pct": round(sum(self._safe_float(row.get("avg_day_range_pct", 0), 0) for row in leaderboard) / tested_count, 4) if tested_count > 0 else 0.0,
            "trade_ready_count": len([row for row in leaderboard if row.get("trade_ready")]),
            "strategies_tested": sorted(list(set([str(row.get("strategy_id", "") or "") for row in leaderboard]))),
        }
        if is_us_market:
            selected["reason"] = f"{selected.get('strategy_name', selected.get('strategy_id', ''))} 검증수익 {selected.get('validation_return', 0):.2f}% · 그래프홀드아웃 {selected.get('graph_holdout_return', 0):.2f}% · 안정성 {selected.get('graph_stability_score', 0):.2f} · 기대수익 {selected.get('total_return', 0):.2f}% · 최대낙폭 {selected.get('max_drawdown', 0):.2f}%"
        else:
            selected["reason"] = f"{selected.get('strategy_name', selected.get('strategy_id', ''))} 검증수익 {selected.get('validation_return', 0):.2f}% · 검증 일평균 ₩{selected.get('validation_avg_profit', 0):,.0f} · 그래프홀드아웃 {selected.get('graph_holdout_return', 0):.2f}% · 안정성 {selected.get('graph_stability_score', 0):.2f} · 기대수익 {selected.get('total_return', 0):.2f}%"
        result = {
            "selected": {
                "symbol": selected.get("symbol", ""),
                "market": selected.get("market", market),
                "name": selected.get("name", ""),
                "strategy_id": selected.get("strategy_id", strategy_id or defaults.get("strategy", "vrev")),
                "strategy_name": selected.get("strategy_name", ""),
                "reason": selected.get("reason", ""),
            },
            "aggregate": aggregate,
            "leaderboard": leaderboard[:12],
            "peer_comparison": leaderboard[1:6],
            "latest": best_payload.get("best", {}) if isinstance(best_payload, dict) else None,
            "cross_validation": [row.get("validation", {}) for row in leaderboard[:5]],
            "quality_guard": quality_guard,
            "training_skipped": False,
            "fallback_reason": "",
            "requested_seed": round(requested_seed, 2),
            "training_seed": round(seed, 2),
            "price_cap_krw": round(effective_price_cap, 2),
            "market": market,
            "cache_key": cache_key,
            "errors": errors[:20],
        }
        if isinstance(best_payload, dict):
            self._write_training_artifacts(best_payload)
        self._save_profile_book_entries(profile_book_updates, market=market)
        self._save_recommendation(result, market=market)
        return result

    def _recommendation_request_payload(self, candidates, seed, period, interval, min_sessions, price_cap, allowed_strategies, market="KS"):
        profile = self._default_profile_for_market(market=market)
        return {
            "candidates": candidates,
            "seed": seed,
            "period": period,
            "interval": interval,
            "min_sessions": min_sessions,
            "price_cap": price_cap,
            "allowed_strategies": allowed_strategies,
            "profile": profile,
        }

    # =========================================================================
    # Artifacts
    # =========================================================================

    def _write_training_artifacts(self, payload):
        fs = self._fs()
        market = str(payload.get("market", "KS") or "KS").upper()
        fs.makedirs(self._market_data_path(market=market))
        fs.makedirs(self._market_docs_path(market=market))
        fs.write.json(self._market_data_path("latest_training.json", market=market), payload)
        best = payload.get("best", {})
        summary = best.get("summary", {})
        profile = best.get("profile", {})
        validation = best.get("validation", {})
        strategy_spec = payload.get("strategy_spec", self.strategy_spec(payload.get("strategy_id", "vrev")))
        lines = [
            "# Domestic Daytrade Optimization Report", "",
            f"- Generated: {payload.get('generated_at', '')}", f"- Symbol: {payload.get('symbol', '')}",
            f"- Market: {payload.get('market', '')}", f"- Strategy: {strategy_spec.get('name', payload.get('strategy_id', 'vrev'))}", f"- Period/Interval: {payload.get('period', '')} / {payload.get('interval', '')}",
            f"- Seed: {payload.get('seed', 0):,.0f}", "",
            "## Selection Criteria", f"- Score: {payload.get('criteria', {}).get('score_formula', '')}",
            "- Objective: maximize net return while controlling drawdown, turnover, fee drag, and overfitting.", "",
            "## Strategy State Machine",
            f"- Summary: {strategy_spec.get('summary', '')}",
        ]
        for item in strategy_spec.get("entry", []):
            lines.append(f"- Entry: {item}")
        for item in strategy_spec.get("exit", []):
            lines.append(f"- Exit: {item}")
        lines += [
            "",
            "## Best Candidate",
            f"- Total Return: {summary.get('total_return', 0)}%", f"- Total Profit: {summary.get('total_profit', 0)}",
            f"- Win Rate: {summary.get('win_rate', 0)}%", f"- Max Drawdown: {summary.get('max_drawdown', 0)}%",
            f"- Avg Trades/Day: {summary.get('avg_trades', 0)}", f"- Profit Factor: {summary.get('profit_factor', 0)}",
            f"- Fee Total: {summary.get('fee_total', 0)}", f"- Avg Holding Minutes: {summary.get('avg_holding_minutes', 0)}",
            f"- Score: {summary.get('score', 0)}", "",
            "## Validation",
            f"- Train/Test Split: {validation.get('split', '')}",
            f"- Robustness Score: {validation.get('robustness_score', 0)}",
            f"- Overfit Gap: {validation.get('overfit_gap', 0)}",
            f"- Graph Stability Score: {(validation.get('graph_validation', {}) or {}).get('stability_score', 0)}",
            f"- Graph Holdout Avg Return: {(validation.get('graph_validation', {}) or {}).get('holdout_avg_return', 0)}%",
            f"- Graph Negative Fold Ratio: {(validation.get('graph_validation', {}) or {}).get('negative_fold_ratio', 0)}",
            "",
            "## Best Parameters",
        ]
        for key in sorted(profile.keys()):
            lines.append(f"- {key}: {profile[key]}")
        lines.append("")
        lines.append("## Top Candidates")
        for idx, item in enumerate(payload.get("top_candidates", []), start=1):
            s = item.get("summary", {})
            v = item.get("validation", {})
            lines.append(f"{idx}. strategy={payload.get('strategy_id', 'vrev')} selection={item.get('selection_score', 0)}, score={s.get('score', 0)}, return={s.get('total_return', 0)}%, mdd={s.get('max_drawdown', 0)}%, robust={v.get('robustness_score', 0)}")
        fs.write(self._market_docs_path("optimization-report.md", market=market), "\n".join(lines))
        symbol = str(payload.get("symbol", "") or "").strip().upper()
        strategy_id = self._normalize_strategy(payload.get("strategy_id", "vrev"))
        if symbol:
            self._save_profile_book_entries({
                f"{symbol}:{strategy_id}": {
                    "symbol": symbol,
                    "market": market,
                    "strategy_id": strategy_id,
                    "updated_at": self._now().strftime("%Y-%m-%d %H:%M:%S"),
                    "profile": dict(profile or {}),
                    "summary": summary,
                    "validation": validation,
                }
            }, market=market)


Model = Daytrade
