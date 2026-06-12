# 단타 트리거 중복정의 덮어쓰기 수정

- **ID**: 008
- **날짜**: 2026-05-06
- **유형**: 버그 수정

## 작업 요약
단타 매도 트리거가 계속 오작동하던 원인을 재점검한 결과, `daytrade_engine.py` 내부에 중복 정의된 메서드가 존재했고 뒤쪽 구현이 앞쪽 수정을 덮어쓰고 있었다.
실제 유효 구현인 뒤쪽 `update_trade_settings()`까지 시장별 트리거 가격 정규화를 적용하고, build/bundle 계층도 함께 동기화하여 국장/미장 트리거 저장값이 런타임에 일관되게 반영되도록 수정했다.

## 원문 요청사항
```text
아니 ㅅㅂ 지금 국장 매도 트리거도 작동하지 않는다니까? 점검하면서 모든 트리거들도 같이 점검 들어가
```

## 변경 파일 목록
### 단타 엔진
- `src/portal/trading/model/struct/daytrade_engine.py`
  - 중복 정의된 뒤쪽 `update_trade_settings()`에 시장별 가격 정규화 적용
  - 국장/미장 공통 트리거 저장값이 실제 런타임 구현에 반영되도록 수정

### 런타임 동기화
- `build/src/model/portal/trading/struct/daytrade_engine.py`
  - 동일 수정 반영
- `bundle/src/model/portal/trading/struct/daytrade_engine.py`
  - 동일 수정 반영
