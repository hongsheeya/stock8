# 한글 모드 (다국어 UI)

- **ID**: 018
- **날짜**: 2026-04-07
- **유형**: 기능 추가

## 작업 요약
전체 UI를 한국어/영어 전환 가능하도록 경량 i18n 서비스를 구현하고, 4개 페이지 + 네비게이션의 모든 하드코딩 텍스트를 번역 키로 교체했다. localStorage 기반 언어 설정 유지, 네비게이션에 언어 토글 버튼 추가.

## 변경 파일 목록

### 신규 생성
| 파일 | 내용 |
|------|------|
| `src/portal/trading/libs/i18n.ts` | I18nService 클래스 — en/ko 딕셔너리 (~350 키), `t(key)`, `setLang()`, `toggleLang()`, `isKo` getter. localStorage `infinitystock-lang` 키로 언어 설정 유지 |

### 네비게이션
| 파일 | 변경 |
|------|------|
| `src/app/component.nav.trading/view.ts` | i18n import, `t()` 메서드, `toggleLang()` 메서드 추가 |
| `src/app/component.nav.trading/view.pug` | 메뉴 라벨 번역 키로 교체, 🇰🇷/🇺🇸 언어 토글 버튼 추가 |

### 대시보드
| 파일 | 변경 |
|------|------|
| `src/app/page.dashboard/view.ts` | i18n import, `t()` 메서드 추가, toast 메시지 번역 |
| `src/app/page.dashboard/view.pug` | 전체 리라이트 — 요약 카드, 엔진 컨트롤, 사이클 테이블, 보유 종목, 활동 기록, extension 모달, 사이클 상세 패널 등 모든 텍스트를 `{{t('dash.*')}}` 키로 교체 |

### 설정
| 파일 | 변경 |
|------|------|
| `src/app/page.settings/view.ts` | i18n import, `t()` 메서드 추가, `showSecret` boolean 추가, `toggleSymbol()` 메서드 추가, `updateWatchlistItem`에 `is_active` 필드 추가 |
| `src/app/page.settings/view.pug` | 전체 리라이트 — API 탭, Watchlist 탭, Parameters 탭의 모든 라벨/플레이스홀더를 `{{t('set.*')}}` 키로 교체 |

### 이력
| 파일 | 변경 |
|------|------|
| `src/app/page.history/view.ts` | i18n import, `t()` 메서드 추가 |
| `src/app/page.history/view.pug` | 전체 리라이트 — 3탭(Cycles/Logs/Snapshots) 테이블 헤더, 필터, 페이지네이션, 빈 상태, 사이클 상세 패널 등 `{{t('hist.*')}}` 키로 교체 |

### 시뮬레이션
| 파일 | 변경 |
|------|------|
| `src/app/page.simulation/view.ts` | i18n import, `t()` 메서드 추가 |
| `src/app/page.simulation/view.pug` | 전체 리라이트 — 폼 라벨, 버튼, 결과 카드, 회차 테이블 등 `{{t('sim.*')}}` 키로 교체 |

## i18n 키 구조
- `nav.*` — 네비게이션 메뉴
- `dash.*` — 대시보드 (profit.*, engine.*, cycle.*, ext.*, detail.*, holdings.*, activity.*)
- `set.*` — 설정 페이지
- `hist.*` — 이력 페이지
- `sim.*` — 시뮬레이션 페이지
- `common.*` — 공통 (confirm, cancel, close, save 등)
