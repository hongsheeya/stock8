# V-REV 알고리즘 분석 및 모델 문서화

- **ID**: 002
- **날짜**: 2026-04-10
- **유형**: 문서 업데이트

## 작업 요약
사용자가 제공한 V-REV 설명을 상태 머신으로 해석하고, 전일종가 앵커·VWAP·거래량 지배력·LIFO 청킹 매도 규칙으로 모델링했다. 해당 내용을 문서 파일로 만들어 페이지에서 직접 열람할 수 있도록 구성했다.

## 변경 파일 목록
- `docs/daytrade/vrev-model.md` — V-REV 모델 해석 문서 생성
- `src/app/page.daytrade/view.pug` — 문서 열람 UI 추가
- `src/app/page.daytrade/api.py` — 문서 로드 API 추가
