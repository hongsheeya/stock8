# 인프라 설정 - database.py 및 trading 패키지 초기 구성

- **ID**: 001
- **날짜**: 2026-04-07
- **유형**: 설정 변경

## 작업 요약
프로젝트 DB 설정 파일(`config/database.py`)을 생성하고, trading 패키지를 초기화했다. SQLite 기반 base/trading 두 개의 DB 네임스페이스를 설정하고, trading 패키지의 Composite Struct 및 placeholder Sub-Struct(kis_api, engine)을 구성했다.

## 변경 파일 목록

### Config
- `config/database.py` (신규): base, trading DB 네임스페이스 (SQLite)
- `config/season.py` (신규): Season 패키지 기본 설정

### Portal/Trading 패키지
- `src/portal/trading/portal.json`: 패키지 메타데이터 (자동 생성)
- `src/portal/trading/README.md` (수정): 패키지 문서
- `src/portal/trading/model/struct.py` (신규): Composite Struct (싱글톤)
- `src/portal/trading/model/struct/kis_api.py` (신규): 한투 API placeholder
- `src/portal/trading/model/struct/engine.py` (신규): 엔진 placeholder

### 프로젝트 루트
- `src/model/struct.py` (수정): trading 패키지 연동 주석 추가
- `data/db/` (신규 디렉토리): SQLite DB 파일 저장 위치
