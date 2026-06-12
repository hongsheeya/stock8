# FN-20260429-0006: 헤더 네비게이션 구조 및 배치 정리

## 작업 번호
- **ID**: FN-20260429-0006
- **날짜**: 2026-04-29
- **유형**: UX/UI 재구성

## 목표
헤더 메뉴 재배치: 주요 기능과 계정/설정 영역 분리

## 현재 헤더 구조 (추정)

```
┌────────────────────────────────────────────────────────────────┐
│ [Logo] 대시보드 | 무한매수 | 단타연구실 | 시뮬레이션 | 거래이력  │
└────────────────────────────────────────────────────────────────┘
```

## 목표 헤더 구조

```
┌─────────────────────────────────────────────────┬─────────────────┐
│ [Logo] 대시보드 | 무한매수 | 단타연구실        │ [설정] [계정⊕]   │
│                 | 시뮬레이션 | 거래이력         │                 │
├─────────────────────────────────────────────────┴─────────────────┤
│ (드롭다운 메뉴 열릴 때)                                            │
│ • 설정   → /settings                                             │
│ • 로그아웃  → /logout                                            │
└──────────────────────────────────────────────────────────────────┘
```

## 구현 상세

### 1. 메뉴 순서 변경

#### Before
1. 대시보드 `/`
2. 무한매수 `/infinitebuy`
3. 단타연구실 `/daytrade`
4. 시뮬레이션 `/simulation`
5. 거래이력 `/history`
6. 설정 (또는 미표시)

#### After
**좌측 메뉴 (주요 기능)**:
1. 대시보드 `/`
2. 무한매수 `/infinitebuy`
3. 단타연구실 `/daytrade`
4. 시뮬레이션 `/simulation`
5. 거래이력 `/history`

**우측 영역 (계정/설정)**:
- 아이콘 버튼 조합
- 드롭다운 메뉴 제공

### 2. 레이아웃 수정 (주요 레이아웃 파일)

#### 파일 위치
- **위치**: `src/app/layout.trading/view.pug` (또는 `layout.*.view.pug`)
- **구조**: Angular의 `<router-outlet>` 포함
- **메뉴**: 반복문으로 렌더링되는 네비게이션

#### Pug 템플릿 구조 (예상)

```pug
//- layout.trading/view.pug

header.trading-header
    .header-left
        .logo
            img(src="/assets/logo.svg")
        nav.header-nav
            a(href="/", routerLink="/", [routerLinkActive]="'active'")
                span 대시보드
            a(href="/infinitebuy", routerLink="/infinitebuy", [routerLinkActive]="'active'")
                span 무한매수
            a(href="/daytrade", routerLink="/daytrade", [routerLinkActive]="'active'")
                span 단타연구실
            a(href="/simulation", routerLink="/simulation", [routerLinkActive]="'active'")
                span 시뮬레이션
            a(href="/history", routerLink="/history", [routerLinkActive]="'active'")
                span 거래이력
    
    .header-right
        .header-actions
            // 설정 아이콘 버튼
            button.icon-button(
                (click)="toggleUserMenu()",
                title="계정 및 설정"
            )
                i.icon-gear  // 또는 svg 아이콘
            
            // 계정 아이콘 + 드롭다운
            .user-menu-container
                button.user-avatar(
                    (click)="toggleUserMenu()",
                    [class.active]="userMenuOpen"
                )
                    i.icon-user
                
                .user-menu-dropdown(*ngIf="userMenuOpen", [@slideDown])
                    a.menu-item(href="/settings", routerLink="/settings")
                        i.icon-cog
                        span 설정
                    a.menu-item(href="/account", routerLink="/account")
                        i.icon-user
                        span 계정정보
                    .menu-divider
                    button.menu-item.logout-item(
                        (click)="handleLogout()"
                    )
                        i.icon-logout
                        span 로그아웃

main.trading-content
    router-outlet

footer.trading-footer
    p © 2026 Trading Platform
```

### 3. 스타일링 (Header SCSS)

```scss
// layout.trading/view.scss 추가

.trading-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 16px 24px;
    background: linear-gradient(135deg, rgba(31, 41, 55, 0.95), rgba(17, 24, 39, 0.95));
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
    backdrop-filter: blur(10px);
    position: sticky;
    top: 0;
    z-index: 100;
    
    .header-left {
        display: flex;
        align-items: center;
        gap: 24px;
        
        .logo {
            img {
                height: 36px;
            }
        }
        
        .header-nav {
            display: flex;
            gap: 8px;
            
            a {
                padding: 8px 16px;
                color: rgba(255, 255, 255, 0.7);
                text-decoration: none;
                font-size: 13px;
                font-weight: 500;
                border-radius: 4px;
                transition: all 0.3s;
                
                &:hover {
                    color: rgba(255, 255, 255, 0.9);
                    background: rgba(255, 255, 255, 0.05);
                }
                
                &.active {
                    color: #FFFFFF;
                    background: rgba(79, 70, 229, 0.2);
                    border-left: 2px solid #4F46E5;
                }
            }
        }
    }
    
    .header-right {
        display: flex;
        align-items: center;
        gap: 16px;
        
        .header-actions {
            display: flex;
            align-items: center;
            gap: 8px;
        }
    }
}

// 모바일 반응형
@media (max-width: 768px) {
    .trading-header {
        padding: 12px 16px;
        
        .header-left {
            gap: 12px;
            
            .logo img {
                height: 28px;
            }
            
            .header-nav {
                gap: 4px;
                
                a {
                    padding: 6px 10px;
                    font-size: 12px;
                }
            }
        }
    }
}
```

### 4. TypeScript 로직 (Layout 컴포넌트)

```typescript
// layout.trading/view.ts

export class Component implements OnInit {
    public userMenuOpen: boolean = false;
    
    public menuItems = [
        { label: '대시보드', link: '/', icon: 'dashboard' },
        { label: '무한매수', link: '/infinitebuy', icon: 'infinite' },
        { label: '단타연구실', link: '/daytrade', icon: 'daytrade' },
        { label: '시뮬레이션', link: '/simulation', icon: 'chart' },
        { label: '거래이력', link: '/history', icon: 'history' }
    ];
    
    constructor(public service: Service) {}
    
    async ngOnInit() {
        await this.service.init();
    }
    
    toggleUserMenu() {
        this.userMenuOpen = !this.userMenuOpen;
    }
    
    async handleLogout() {
        try {
            // LogOut 호출
            let res = await wiz.call("logout", {});
            if (res.code === 200) {
                // 로그인 페이지로 리다이렉트
                this.service.href("/login");
            }
        } catch (e) {
            // 에러 처리
            console.error("로그아웃 실패", e);
        }
    }
}
```

### 5. 반응형 디자인

#### 데스크톱 (1200px 이상)
```
[Logo] 메뉴메뉴메뉴메뉴메뉴          [설정아콘] [계정아이콘⊕]
```

#### 태블릿 (768px ~ 1200px)
```
[Logo] 메뉴메뉴메뉴                [설정] [계정⊕]
```

#### 모바일 (768px 이하)
```
[Logo] [☰ 메뉴]                    [설정] [계정⊕]

// 햄버거 메뉴 클릭 시
├── 대시보드
├── 무한매수
├── 단타연구실
├── 시뮬레이션
└── 거래이력
```

## 구현 계획

### Phase 1: 레이아웃 구조 수정 (1시간)
- [ ] 현재 layout 파일 분석 (위치 확인)
- [ ] 헤더 영역 수정 (좌/우 분할)
- [ ] 메뉴 순서 재배치

### Phase 2: 스타일링 (1.5시간)
- [ ] 헤더 배경 + glassmorphism 효과
- [ ] 메뉴 아이템 호버 상태
- [ ] 드롭다운 메뉴 스타일
- [ ] 모바일 반응형 테스트

### Phase 3: 상호작용 로직 (1시간)
- [ ] 드롭다운 토글 함수
- [ ] 로그아웃 호출
- [ ] 라우터 네비게이션 통합

### Phase 4: 테스트 (1시간)
- [ ] 데스크톱 레이아웃 테스트
- [ ] 태블릿 반응형 테스트
- [ ] 모바일 반응형 테스트
- [ ] 드롭다운 메뉴 동작 테스트
- [ ] 다른 페이지와의 호환성 확인

## 예상 결과
- ✅ 헤더 메뉴 정렬: 대시보드/무한매수/단타연구실/시뮬레이션/거래이력
- ✅ 계정/설정 영역 분리 (우측)
- ✅ 드롭다운 메뉴로 설정 진입
- ✅ 모바일에서도 레이아웃 유지

## FN-0005와의 연계
- **FN-0005**: 설정 페이지 회원정보/비밀번호 개선
- **FN-0006**: 헤더 메뉴에서 설정 진입 경로 추가
- **연계점**: 헤더의 설정 버튼 → page.settings로 네비게이션

**총 투입 시간**: 약 4.5시간
