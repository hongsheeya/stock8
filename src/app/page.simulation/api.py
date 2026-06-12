import json
import math
import datetime

struct = wiz.model("struct")
_TIME = wiz.model("portal/trading/kst")


def _safe_int(v, default=0):
    try:
        text = str(v if v is not None else "").strip()
        if text == "":
            return int(default)
        return int(float(text))
    except Exception:
        return int(default)

def _safe_float(v, default=0):
    """NaN/Infinity를 안전한 값으로 치환"""
    try:
        if v is None:
            return default
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return default
        text = str(v).strip()
        if text == "":
            return default
        value = float(text)
        if math.isnan(value) or math.isinf(value):
            return default
        return value
    except Exception:
        return default

def _sanitize(obj):
    """재귀적으로 dict/list 내 모든 float NaN/Infinity를 null로 치환"""
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    return obj

def _get_config(key, default=""):
    trading = struct.trading
    getter = getattr(trading, "get_config", None)
    if callable(getter):
        return getter(key, default)

    config_db = trading.db("trading_config")
    row = config_db.get(key=key)
    if row:
        return row.get("value", default)
    return default

def _get_partial_sell_stages():
    try:
        trading = struct.trading
        strategy_mod = trading.strategy
        defaults = strategy_mod.get("DEFAULT_PARAMS", {})
        return defaults.get("partial_sell_stages", [])
    except Exception:
        return []

def load_watchlist():
    """워치리스트 조회 + 수수료 설정 + 전략 설정"""
    try:
        trading = struct.trading
        watchlist_db = trading.db("etf_watchlist")
        watchlist = watchlist_db.rows(orderby="created", order="ASC") or []

        buy_commission_rate = _safe_float(_get_config("buy_commission_rate", "0.25"), 0.25)
        sell_commission_rate = _safe_float(_get_config("sell_commission_rate", "0.25"), 0.25)
        tax_rate = _safe_float(_get_config("tax_rate", "0"), 0)
        division_count = _safe_int(_get_config("default_division_count", "40"), 40)
        target_profit = _safe_float(_get_config("default_target_profit", "10"), 10)

        # 전략 설정도 함께 반환
        sell_strategy = _get_config("sell_strategy", "full")
        crash_buy_enabled = str(_get_config("crash_buy_enabled", "false")).lower() == "true"
        crash_buy_drop_pct = _safe_float(_get_config("crash_buy_drop_pct", "5"), 5)
        crash_buy_ma_drop_pct = _safe_float(_get_config("crash_buy_ma_drop_pct", "10"), 10)
        crash_buy_ratio = _safe_float(_get_config("crash_buy_ratio", "10"), 10)
        crash_buy_max_per_cycle = _safe_int(_get_config("crash_buy_max_per_cycle", "3"), 3)
    except Exception as e:
        wiz.response.status(500, message=f"load_watchlist failed: {e}")

    wiz.response.status(200,
        watchlist=watchlist,
        buy_commission_rate=buy_commission_rate,
        sell_commission_rate=sell_commission_rate,
        tax_rate=tax_rate,
        division_count=division_count,
        target_profit=target_profit,
        sell_strategy=sell_strategy,
        partial_sell_stages=_get_partial_sell_stages(),
        crash_buy_enabled=crash_buy_enabled,
        crash_buy_drop_pct=crash_buy_drop_pct,
        crash_buy_ma_drop_pct=crash_buy_ma_drop_pct,
        crash_buy_ratio=crash_buy_ratio,
        crash_buy_max_per_cycle=crash_buy_max_per_cycle,
    )

def validate_symbol():
    """종목코드 유효성 검증 (yfinance)"""
    symbol = wiz.request.query("symbol", True).strip().upper()

    try:
        import yfinance as yf
    except ImportError:
        wiz.response.status(500, message="yfinance 패키지가 설치되지 않았습니다.")

    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}
        name = info.get("shortName") or info.get("longName") or ""
        exchange = info.get("exchange", "")
        market_cap = info.get("marketCap", 0)
        currency = info.get("currency", "")
        quote_type = info.get("quoteType", "")

        # 실제 유효한 종목인지 확인: shortName이 있거나, 최근 시세가 있어야 유효
        hist = ticker.history(period="5d")
        has_data = not hist.empty
        last_price = float(hist["Close"].iloc[-1]) if has_data else 0

        valid = bool(name and has_data)
    except Exception as e:
        wiz.response.status(200, valid=False, symbol=symbol, message=str(e))

    wiz.response.status(200,
        valid=valid,
        symbol=symbol,
        name=name,
        exchange=exchange,
        currency=currency,
        quote_type=quote_type,
        market_cap=market_cap,
        last_price=round(last_price, 2),
        message="" if valid else f"'{symbol}' 종목을 찾을 수 없습니다.",
    )

def _fetch_daily_prices(symbol, start_date, end_date):
    """Yahoo Finance에서 과거 시세 데이터 조회"""
    daily_prices = []
    error_msg = None

    try:
        import yfinance as yf
    except ImportError:
        wiz.response.status(500, message="yfinance 패키지가 설치되지 않았습니다. 터미널에서 pip install yfinance 를 실행하세요.")

    try:
        ticker = yf.Ticker(symbol)
        end_dt = datetime.datetime.strptime(end_date, "%Y-%m-%d") + datetime.timedelta(days=1)
        hist = ticker.history(start=start_date, end=end_dt.strftime("%Y-%m-%d"), auto_adjust=True)

        if hist.empty:
            error_msg = f"{symbol}의 시세 데이터를 찾을 수 없습니다. 종목코드가 올바른지 확인하세요."
        else:
            for date_idx, row in hist.iterrows():
                daily_prices.append({
                    "date": date_idx.strftime("%Y-%m-%d"),
                    "open": _safe_float(float(row["Open"])),
                    "high": _safe_float(float(row["High"])),
                    "low": _safe_float(float(row["Low"])),
                    "close": _safe_float(float(row["Close"])),
                    "volume": int(row["Volume"]),
                })
    except Exception as e:
        error_msg = f"시세 데이터 조회 실패: {str(e)}"

    if error_msg:
        wiz.response.status(400, message=error_msg)

    if not daily_prices:
        wiz.response.status(400, message="해당 기간의 시세 데이터가 없습니다")

    daily_prices.sort(key=lambda x: x.get("date", ""))
    return daily_prices

def run_simulation():
    """
    백테스트 시뮬레이션 실행 — strategy.py의 backtest_strategy() 사용
    use_my_strategy=true 시 Settings에서 설정한 전략 파라미터를 자동 적용
    """
    symbol = wiz.request.query("symbol", True).strip().upper()
    start_date = wiz.request.query("start_date", True)
    end_date = wiz.request.query("end_date", True)
    investment = float(wiz.request.query("investment", "10000"))
    division_count = int(wiz.request.query("division_count", "40"))
    target_profit = float(wiz.request.query("target_profit", "10"))
    buy_commission_rate = float(wiz.request.query("buy_commission_rate", "0.25")) / 100
    sell_commission_rate = float(wiz.request.query("sell_commission_rate", "0.25")) / 100
    tax_rate = float(wiz.request.query("tax_rate", "0")) / 100
    allow_extension_str = wiz.request.query("allow_extension", "false")
    allow_extension = allow_extension_str in ["true", "1", "True"]
    use_my_strategy_str = wiz.request.query("use_my_strategy", "false")
    use_my_strategy = use_my_strategy_str in ["true", "1", "True"]

    trading = struct.trading

    # 시세 데이터 조회
    daily_prices = _fetch_daily_prices(symbol, start_date, end_date)

    # 전략 결정
    sell_strategy = "full"
    strategy_params = {}

    if use_my_strategy:
        # Settings에서 저장된 전략 파라미터 로드
        sell_strategy = _get_config("sell_strategy", "full")
        strategy_params = {
            "sell_strategy": sell_strategy,
            "partial_sell_stages": _get_partial_sell_stages(),
            "crash_buy_enabled": _get_config("crash_buy_enabled", "false") == "true",
            "crash_buy_drop_pct": float(_get_config("crash_buy_drop_pct", "5")),
            "crash_buy_ma_drop_pct": float(_get_config("crash_buy_ma_drop_pct", "10")),
            "crash_buy_ratio": float(_get_config("crash_buy_ratio", "10")),
            "crash_buy_max_per_cycle": int(_get_config("crash_buy_max_per_cycle", "3")),
        }
    else:
        # 프론트엔드에서 전달된 파라미터 사용
        sell_strategy_param = wiz.request.query("sell_strategy", "full")
        sell_strategy = sell_strategy_param

        if sell_strategy == "partial":
            strategy_params = {
                "sell_strategy": "partial",
                "partial_sell_stages": _get_partial_sell_stages(),
            }

        crash_buy_enabled_str = wiz.request.query("crash_buy_enabled", "false")
        if crash_buy_enabled_str in ["true", "1", "True"]:
            strategy_params["crash_buy_enabled"] = True
            strategy_params["crash_buy_drop_pct"] = float(wiz.request.query("crash_buy_drop_pct", "5"))
            strategy_params["crash_buy_ma_drop_pct"] = float(wiz.request.query("crash_buy_ma_drop_pct", "10"))
            strategy_params["crash_buy_ratio"] = float(wiz.request.query("crash_buy_ratio", "10"))
            strategy_params["crash_buy_max_per_cycle"] = int(wiz.request.query("crash_buy_max_per_cycle", "3"))

    # strategy.py의 backtest_strategy 호출
    strategy_mod = trading.strategy
    backtest_fn = strategy_mod["backtest_strategy"]

    try:
        result = backtest_fn(
            daily_prices=daily_prices,
            investment=investment,
            division_count=division_count,
            target_profit=target_profit,
            buy_commission_rate=buy_commission_rate,
            sell_commission_rate=sell_commission_rate,
            tax_rate=tax_rate,
            sell_strategy=sell_strategy,
            strategy_params=strategy_params,
            allow_extension=allow_extension,
        )
    except Exception as e:
        wiz.response.status(500, message=f"Simulation failed: {str(e)}")

    # NaN/Infinity 안전 치환
    result = _sanitize(result)

    summary = result["summary"]
    summary["symbol"] = symbol
    summary["period"] = f"{start_date} ~ {end_date}"
    summary["trading_days"] = len(daily_prices)
    summary["buy_commission_rate"] = round(buy_commission_rate * 100, 3)
    summary["sell_commission_rate"] = round(sell_commission_rate * 100, 3)
    summary["tax_rate"] = round(tax_rate * 100, 3)
    summary["allow_extension"] = allow_extension
    summary["use_my_strategy"] = use_my_strategy
    summary["sell_strategy"] = sell_strategy

    # DB 기록
    try:
        run_db = trading.db("simulation_run")
        now = _TIME.now()
        run_data = {
            "symbol": symbol,
            "start_date": start_date,
            "end_date": end_date,
            "initial_investment": investment,
            "division_count": division_count,
            "target_profit": target_profit,
            "buy_commission_rate": round(buy_commission_rate * 100, 3),
            "sell_commission_rate": round(sell_commission_rate * 100, 3),
            "tax_rate": round(tax_rate * 100, 3),
            "total_cycles": summary.get("total_cycles", 0),
            "total_profit": round(_safe_float(summary.get("final_asset", 0)) - investment, 2),
            "total_profit_rate": _safe_float(summary.get("total_return", 0)),
            "total_commission": _safe_float(summary.get("total_commission", 0)),
            "win_rate": _safe_float(summary.get("win_rate", 0)),
            "avg_cycle_days": _safe_float(summary.get("avg_cycle_days", 0)),
            "max_drawdown": _safe_float(summary.get("max_drawdown", 0)),
            "final_asset": _safe_float(summary.get("final_asset", 0)),
            "created": now,
        }
        run_db.insert(run_data)
    except Exception:
        pass

    wiz.response.status(200,
        summary=summary,
        trades=result.get("trades", []),
        cycles=result.get("cycles", []),
    )

def run_comparison():
    """전략 비교 시뮬레이션 — 기본 전략 vs 내 전략 비교"""
    symbol = wiz.request.query("symbol", True).strip().upper()
    start_date = wiz.request.query("start_date", True)
    end_date = wiz.request.query("end_date", True)
    investment = float(wiz.request.query("investment", "10000"))
    division_count = int(wiz.request.query("division_count", "40"))
    target_profit = float(wiz.request.query("target_profit", "10"))
    buy_commission_rate = float(wiz.request.query("buy_commission_rate", "0.25")) / 100
    sell_commission_rate = float(wiz.request.query("sell_commission_rate", "0.25")) / 100
    tax_rate = float(wiz.request.query("tax_rate", "0")) / 100
    allow_extension_str = wiz.request.query("allow_extension", "false")
    allow_extension = allow_extension_str in ["true", "1", "True"]

    # Crash buy params
    crash_buy_enabled_str = wiz.request.query("crash_buy_enabled", "false")
    crash_buy_enabled = crash_buy_enabled_str in ["true", "1", "True"]
    crash_buy_drop_pct = float(wiz.request.query("crash_buy_drop_pct", "5"))
    crash_buy_ma_drop_pct = float(wiz.request.query("crash_buy_ma_drop_pct", "10"))
    crash_buy_ratio = float(wiz.request.query("crash_buy_ratio", "10"))
    crash_buy_max_per_cycle = int(wiz.request.query("crash_buy_max_per_cycle", "3"))

    # 시세 데이터 조회
    daily_prices = _fetch_daily_prices(symbol, start_date, end_date)

    trading = struct.trading
    strategy_mod = trading.strategy
    backtest_fn = strategy_mod["backtest_strategy"]

    common = dict(
        daily_prices=daily_prices,
        investment=investment,
        division_count=division_count,
        target_profit=target_profit,
        buy_commission_rate=buy_commission_rate,
        sell_commission_rate=sell_commission_rate,
        tax_rate=tax_rate,
        allow_extension=allow_extension,
    )

    strategy_params = {
        "sell_strategy": "partial",
        "partial_sell_stages": _get_partial_sell_stages(),
        "crash_buy_enabled": crash_buy_enabled,
        "crash_buy_drop_pct": crash_buy_drop_pct,
        "crash_buy_ma_drop_pct": crash_buy_ma_drop_pct,
        "crash_buy_ratio": crash_buy_ratio,
        "crash_buy_max_per_cycle": crash_buy_max_per_cycle,
    }

    try:
        # 기본 전략 (전량 매도, crash buy 없음)
        full_result = backtest_fn(**common, sell_strategy="full", strategy_params={})

        # 사용자 전략 (전달된 파라미터 적용)
        my_result = backtest_fn(**common, sell_strategy="partial", strategy_params=strategy_params)
    except Exception as e:
        wiz.response.status(500, message=f"Comparison failed: {str(e)}")

    # NaN/Infinity 안전 치환
    full_result = _sanitize(full_result)
    my_result = _sanitize(my_result)

    wiz.response.status(200,
        full_sell=full_result.get("summary", {}),
        partial_sell=my_result.get("summary", {}),
        full_sell_trades=full_result.get("trades", []),
        partial_sell_trades=my_result.get("trades", []),
        full_sell_cycles=full_result.get("cycles", []),
        partial_sell_cycles=my_result.get("cycles", []),
    )
