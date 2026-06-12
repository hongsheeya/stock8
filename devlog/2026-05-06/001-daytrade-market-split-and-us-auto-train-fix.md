# 단타 KS/US 모델 분리 및 미장 자동매매·재훈련 복구

- **ID**: 001
- **날짜**: 2026-05-06
- **유형**: 버그 수정

## 작업 요약
국장/미장 단타가 같은 추천·학습 산출물을 공유하던 구조를 시장별 파일로 분리했다.
미장 자동매매가 실제 BUY 대신 shadow mode/HOLD로만 남던 원인을 프로필 병합 오류로 수정했고, 재훈련이 즉시 실패하던 `requested_seed`/중복 `_optimize_payload()` 문제도 함께 복구했다.

## 원문 요청사항
```text
국장 모델이랑 미장 모델을 구분해야지.
또 지금 미장을 한번도 자동구매가 안되고 있는데 그 원인을 찾아서 설명하고 고쳐봐.
자동매매 온 해놨는데 자동으로 안되잖아.
그리고 요즘 승률 너무 안좋은데 원인 분석해서 해결해봐.
모델 개편필요하면 새로 만들어서 검증하고 진행해.
지금 종목 재훈련시 학습실패가 뜨는데 원인 찾아서 고쳐
```

## 변경 파일 목록
- `src/portal/trading/model/struct/daytrade.py`
	- KS/US별 추천/훈련/프로필 산출물 경로를 분리
	- `recommend()`/`auto_train()`을 로컬 최적화 기반으로 복구
	- US 학습/백테스트가 KS 기본 프로필을 쓰던 문제 수정
	- 시장별 `profile_book` 저장 및 조회 추가
- `src/portal/trading/model/struct/daytrade_engine.py`
	- 라이브 프로필 로딩 시 시장별 기본값과 학습 프로필을 병합하도록 수정
	- US 전략이 누락 필드 때문에 암묵적으로 shadow mode로 떨어지던 문제 수정
- `src/app/page.daytrade/api.py`
	- 시장별 `latest_training()`/`latest_recommendation()` 조회로 분리
- `build/src/model/portal/trading/struct/daytrade.py`
	- 소스 변경 미러링
- `build/src/model/portal/trading/struct/daytrade_engine.py`
	- 소스 변경 미러링
- `build/src/app/page.daytrade/api.py`
	- 소스 변경 미러링
- `bundle/src/model/portal/trading/struct/daytrade.py`
	- 소스 변경 미러링
- `bundle/src/model/portal/trading/struct/daytrade_engine.py`
	- 소스 변경 미러링
- `bundle/src/app/page.daytrade/api.py`
	- 소스 변경 미러링

## 검증
- `python3 -m py_compile src/portal/trading/model/struct/daytrade.py src/portal/trading/model/struct/daytrade_engine.py src/app/page.daytrade/api.py`
- `python3 -m py_compile build/src/model/portal/trading/struct/daytrade.py build/src/model/portal/trading/struct/daytrade_engine.py build/src/app/page.daytrade/api.py bundle/src/model/portal/trading/struct/daytrade.py bundle/src/model/portal/trading/struct/daytrade_engine.py bundle/src/app/page.daytrade/api.py`
