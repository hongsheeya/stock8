# daytrade_engine.py SyntaxError 3건 수정 (Package 'trading' not found 해결)

- **ID**: 013
- **날짜**: 2026-04-27
- **유형**: 버그 수정

## 작업 요약
`Package 'trading' not found` 오류의 근본 원인인 `daytrade_engine.py` SyntaxError 3건을 수정했다.
이전 세션에서 shadow mode 코드를 삽입하는 과정 및 기타 수정 중 코드 잘림/들여쓰기 오류가 발생해 패키지 로드가 전면 차단되고 있었다.

## 변경 파일 목록

### `src/portal/trading/model/struct/daytrade_engine.py`

| 위치 | 내용 |
|------|------|
| Line 1211 | `for x` 잘린 리스트 컴프리헨션 → `for x in excluded_by_price[:3]])` 복구 (이전 세션) |
| Line 2645 | `except Exception as e:` 들여쓰기 12칸 → 8칸으로 수정 (`try:` 레벨 불일치) |
| Line 3547 | `self._append_runtime_log(...)` 괄호 미닫힘 → `)` 추가 |
| Lines 2017, 2033 | 존재하지 않는 `self._buy_budget(seed, profile)` 호출 → `buy_budget` 변수 참조로 교체 |
