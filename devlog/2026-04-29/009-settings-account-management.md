# FN-20260429-0005: 설정 페이지 회원정보/계정관리 기능 확장

## 작업 번호
- **ID**: FN-20260429-0005
- **날짜**: 2026-04-29
- **유형**: UX/기능 확장

## 목표
설정 페이지에 회원 기본정보 + 비밀번호 변경 기능 추가

## 현재 상태

### 설정 페이지 구조 (page.settings)
- 위치: `/settings`
- 컨트롤러: `user` (로그인 필수)
- 현재 기능: [확인 필요 - view.pug 분석]

## 구현 범위

### 1. UI 섹션 추가 (page.settings/view.pug)

#### Section 1: 계정정보 (Account Information)
```
┌─ 계정정보
│  ├─ 회원 아이디: _________ (읽기 전용)
│  ├─ 가입 이메일: _________ (읽기 전용)
│  └─ 가입일: _________ (읽기 전용)
```

#### Section 2: 보안설정 (Security Settings)
```
┌─ 보안설정
│  ├─ 현재 비밀번호: [입력필드] (마스크)
│  ├─ 새 비밀번호: [입력필드] (마스크)
│  ├─ 비밀번호 확인: [입력필드] (마스크)
│  └─ [비밀번호 변경] 버튼
```

### 2. 데이터 API (page.settings/api.py)

#### 기존 API 확인
- `get_account_info()`: 회원 기본정보 조회 (새 추가)
- `update_password()`: 비밀번호 변경 (새 추가)

#### 구현 코드

```python
# page.settings/api.py에 추가

def get_account_info():
    """
    현재 로그인 사용자의 계정정보 조회
    
    Returns: {
        "user_id": "user123",
        "email": "user@example.com",
        "joined_date": "2025-12-15",
        "last_login": "2026-04-29 10:30:00"
    }
    """
    user_id = wiz.session.get("id")
    if not user_id:
        wiz.response.status(401)
    
    # season 패키지 회원 정보 조회
    try:
        user_info = wiz.model("portal/season/struct/user").get(user_id)
        wiz.response.status(200, data={
            "user_id": user_info.get("user_id", ""),
            "email": user_info.get("email", ""),
            "joined_date": user_info.get("created_at", "").split(" ")[0],
            "last_login": wiz.session.get("last_login", ""),
        })
    except Exception as e:
        wiz.response.status(400, message=str(e))


def update_password():
    """
    현재 사용자의 비밀번호 변경
    
    Query params:
        current_password: 현재 비밀번호
        new_password: 새 비밀번호 (8자 이상, 영+숫+특수)
        confirm_password: 비밀번호 확인
    
    Returns: {
        "message": "비밀번호가 변경되었습니다"
    }
    """
    user_id = wiz.session.get("id")
    if not user_id:
        wiz.response.status(401)
    
    current_pwd = wiz.request.query("current_password", True)
    new_pwd = wiz.request.query("new_password", True)
    confirm_pwd = wiz.request.query("confirm_password", True)
    
    # 검증 1: 비밀번호 일치
    if new_pwd != confirm_pwd:
        wiz.response.status(400, message="새 비밀번호와 확인 비밀번호가 일치하지 않습니다")
    
    # 검증 2: 최소 길이
    if len(new_pwd) < 8:
        wiz.response.status(400, message="비밀번호는 8자 이상이어야 합니다")
    
    # 검증 3: 복잡도 (영문, 숫자, 특수문자 포함)
    import re
    if not re.search(r"[a-zA-Z]", new_pwd) or \
       not re.search(r"[0-9]", new_pwd) or \
       not re.search(r"[!@#$%^&*]", new_pwd):
        wiz.response.status(400, message="비밀번호는 영문, 숫자, 특수문자를 포함해야 합니다")
    
    # 기존 비밀번호와 비교
    try:
        season_user = wiz.model("portal/season/struct/user").get(user_id)
        if not season_user.verify_password(current_pwd):
            wiz.response.status(400, message="현재 비밀번호가 일치하지 않습니다")
        
        # 비밀번호 변경 실행
        season_user.update_password(new_pwd)
        
        wiz.response.status(200, message="비밀번호가 변경되었습니다")
    
    except Exception as e:
        wiz.response.status(400, message=f"비밀번호 변경 실패: {str(e)}")
```

### 3. TypeScript 로직 (page.settings/view.ts)

```typescript
// view.ts에 추가

public accountInfo: any = null;
public passwordForm = {
    currentPassword: '',
    newPassword: '',
    confirmPassword: ''
};
public passwordLoading: boolean = false;
public passwordMessage: string = '';

// 계정정보 로드
async loadAccountInfo() {
    try {
        let res = await wiz.call("get_account_info", {});
        if (res.code === 200) {
            this.accountInfo = res.data;
        } else {
            this.errorMessage = res.data?.message || "계정정보 로드 실패";
        }
    } catch (e) {
        this.errorMessage = "계정정보 로드 중 오류: " + e.toString();
    }
    await this.service.render();
}

// 비밀번호 변경
async updatePassword() {
    // 프론트엔드 검증
    if (!this.passwordForm.currentPassword) {
        this.passwordMessage = "현재 비밀번호를 입력하세요";
        return;
    }
    if (!this.passwordForm.newPassword) {
        this.passwordMessage = "새 비밀번호를 입력하세요";
        return;
    }
    if (this.passwordForm.newPassword !== this.passwordForm.confirmPassword) {
        this.passwordMessage = "새 비밀번호가 일치하지 않습니다";
        return;
    }

    this.passwordLoading = true;
    try {
        let res = await wiz.call("update_password", {
            current_password: this.passwordForm.currentPassword,
            new_password: this.passwordForm.newPassword,
            confirm_password: this.passwordForm.confirmPassword
        });
        
        if (res.code === 200) {
            this.passwordMessage = "비밀번호가 변경되었습니다";
            this.passwordForm = { currentPassword: '', newPassword: '', confirmPassword: '' };
        } else {
            this.passwordMessage = res.data?.message || "비밀번호 변경 실패";
        }
    } catch (e) {
        this.passwordMessage = "비밀번호 변경 중 오류: " + e.toString();
    } finally {
        this.passwordLoading = false;
    }
    await this.service.render();
}
```

### 4. 스타일링 (page.settings/view.scss)

```scss
// 계정정보 섹션
.settings-account-section {
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 8px;
    padding: 20px;
    margin-bottom: 20px;
    background: rgba(255, 255, 255, 0.05);
    
    .info-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 12px 0;
        border-bottom: 1px solid rgba(255, 255, 255, 0.05);
        
        &:last-child {
            border-bottom: none;
        }
        
        .label {
            font-weight: 600;
            color: rgba(255, 255, 255, 0.7);
            min-width: 120px;
        }
        
        .value {
            color: rgba(255, 255, 255, 0.9);
        }
    }
}

// 비밀번호 변경 폼
.settings-password-form {
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 8px;
    padding: 20px;
    background: rgba(255, 255, 255, 0.05);
    
    .form-group {
        margin-bottom: 16px;
        
        label {
            display: block;
            margin-bottom: 8px;
            font-weight: 600;
            color: rgba(255, 255, 255, 0.7);
            font-size: 13px;
        }
        
        input {
            width: 100%;
            padding: 10px 12px;
            border: 1px solid rgba(255, 255, 255, 0.2);
            border-radius: 4px;
            background: rgba(255, 255, 255, 0.05);
            color: rgba(255, 255, 255, 0.9);
            font-size: 13px;
            
            &:focus {
                outline: none;
                border-color: #4F46E5;
                background: rgba(255, 255, 255, 0.08);
            }
        }
    }
    
    .form-message {
        margin-bottom: 16px;
        padding: 12px;
        border-radius: 4px;
        font-size: 12px;
        
        &.error {
            background: rgba(239, 68, 68, 0.1);
            color: #FCA5A5;
        }
        
        &.success {
            background: rgba(34, 197, 94, 0.1);
            color: #A7F3D0;
        }
    }
    
    .form-button {
        display: inline-flex;
        padding: 10px 24px;
        background: #4F46E5;
        color: white;
        border: none;
        border-radius: 4px;
        font-size: 13px;
        font-weight: 600;
        cursor: pointer;
        transition: background 0.3s;
        
        &:hover:not(:disabled) {
            background: #4338CA;
        }
        
        &:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
    }
}
```

## 구현 계획

### Phase 1: UI 개발 (1시간)
- [ ] view.pug에 2개 섹션 추가
- [ ] 입력필드 + 버튼 마크업
- [ ] 기본 스타일링

### Phase 2: API 개발 (1.5시간)
- [ ] `get_account_info()` 구현
- [ ] `update_password()` 구현 + 검증
- [ ] 에러 핸들링

### Phase 3: 로직 통합 (1시간)
- [ ] view.ts에 메서드 추가
- [ ] 폼 바인딩 + 이벤트 핸들러
- [ ] 로딩 상태 관리

### Phase 4: 테스트 (1시간)
- [ ] 계정정보 로드 테스트
- [ ] 비밀번호 변경 성공 케이스
- [ ] 검증 실패 케이스 (길이, 형식, 일치도)

## 보안 고려사항
- ✅ 현재 비밀번호 검증 (중복 변경 방지)
- ✅ 비밀번호 복잡도 검증 (영+숫+특수)
- ✅ 최소 길이 8자
- ✅ HTTPS 전송 (기존 프레임워크 보장)
- ✅ 서버 해시 저장 (기존 구조 재사용)

## 예상 결과
- ✅ 설정 페이지에서 회원 기본정보 확인 가능
- ✅ 비밀번호 변경 기능 제공
- ✅ 보안 검증 (복잡도, 확인)

**총 투입 시간**: 약 4.5시간
