# 미장 단타 복합 랭킹 최적화

- **ID**: 006
- **날짜**: 2026-05-06
- **유형**: 기능 추가

## 작업 요약
미장 단타 추천 리더보드가 기존 `selection_score` 중심 정렬에 치우쳐 있던 부분을 보강했다.
이제 미장(`US`) 추천은 기대수익률, 승률, 최대낙폭, 검증 강도, 기존 선택 점수를 함께 반영한 `rank_score` 복합 점수로 정렬되어 자동매매가 실제로 더 좋은 전략을 우선 선택하도록 조정했다.

## 원문 요청사항
```text
미장 매매 알고리즘도 승률 수익률 전부 비교해서 제일 좋은걸로 진행해.
```

## 변경 파일 목록
### 추천/랭킹 로직
- `src/portal/trading/model/struct/daytrade.py`
  - 미장 추천 row 생성 시 `rank_score` 복합 점수 추가
  - 미장 리더보드 정렬 기준을 `rank_score` 우선으로 변경
  - 선택 사유 문구에 복합점수/수익률/승률/최대낙폭 반영

### 빌드 반영
- `build/src/model/portal/trading/struct/daytrade.py`
  - 소스와 동일한 랭킹 최적화 반영
- `bundle/src/model/portal/trading/struct/daytrade.py`
  - 런타임 반영용 동일 수정 적용
