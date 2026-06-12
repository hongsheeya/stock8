# =============================================================================
# User Sub-Struct (사용자 비즈니스 로직)
# =============================================================================
# 사용 패턴:
#   struct = wiz.model("struct")
#   struct.user.authenticate("email@example.com", "hashed_password")
#   struct.user.get("user_id")
#   struct.user.list(text="검색어", role="admin")
#   struct.user.update_profile(user_id, name="새이름", mobile="010-...")
# =============================================================================

import datetime
import bcrypt

_TIME = wiz.model("portal/trading/kst")

class User:
    def __init__(self, core):
        self.core = core
        self.db = core.orm.use("user")

    def _hash_password(self, password):
        """비밀번호 bcrypt 해시"""
        if isinstance(password, str):
            password = password.encode('utf-8')
        return bcrypt.hashpw(password, bcrypt.gensalt()).decode('utf-8')

    def _check_password(self, password, hashed):
        """비밀번호 검증"""
        if isinstance(password, str):
            password = password.encode('utf-8')
        if isinstance(hashed, str):
            hashed = hashed.encode('utf-8')
        return bcrypt.checkpw(password, hashed)

    def authenticate(self, email, password):
        """이메일/비밀번호 인증

        Args:
            email: 이메일
            password: 평문 비밀번호

        Returns:
            dict (사용자 정보) 또는 None (인증 실패)
        """
        user = self.db.get(email=email)
        if user is None:
            return None
        if not self._check_password(password, user.get('password', '')):
            return None
        # 비밀번호 필드 제거 후 반환
        user.pop('password', None)
        return user

    def get(self, id=None):
        """사용자 단건 조회 (비밀번호 제외)

        Args:
            id: 사용자 ID

        Returns:
            dict 또는 None
        """
        user = self.db.get(id=id)
        if user:
            user.pop('password', None)
        return user

    def get_by_email(self, email=None):
        user = self.db.get(email=email)
        if user:
            user.pop('password', None)
        return user

    def find_email(self, name, mobile):
        user = self.db.get(name=name, mobile=mobile)
        if user is None:
            return None
        return user.get('email', '')

    def list(self, text="", role=""):
        """사용자 목록 조회

        Args:
            text: 이름/이메일 검색어
            role: 역할 필터

        Returns:
            list[dict]
        """
        kwargs = dict()
        like = None

        if role:
            kwargs['role'] = role
        if text:
            kwargs['name'] = text
            like = "name"

        rows = self.db.rows(
            orderby="created", order="ASC",
            like=like,
            **kwargs
        )
        # 비밀번호 필드 제거
        for r in rows:
            r.pop('password', None)
        return rows

    def create(self, data):
        """사용자 생성

        Args:
            data: {"email", "password", "name", "role"} dict

        Returns:
            생성된 사용자 ID
        """
        now = _TIME.normalize(_TIME.now())
        data['password'] = self._hash_password(data['password'])
        data['created'] = now
        data['updated'] = now
        if not data.get('role'):
            data['role'] = 'user'
        if not data.get('mobile'):
            data['mobile'] = ''
        return self.db.insert(data)

    def update_profile(self, id, **fields):
        """프로필 업데이트 (name, mobile 등)

        Args:
            id: 사용자 ID
            **fields: 업데이트할 필드
        """
        fields['updated'] = _TIME.normalize(_TIME.now())
        self.db.update(fields, id=id)

    def change_password(self, id, current_password, new_password):
        """비밀번호 변경

        Args:
            id: 사용자 ID
            current_password: 현재 비밀번호 (평문)
            new_password: 새 비밀번호 (평문)

        Returns:
            bool (성공 여부)
        """
        user = self.db.get(id=id)
        if user is None:
            return False
        if not self._check_password(current_password, user.get('password', '')):
            return False
        hashed = self._hash_password(new_password)
        self.db.update(dict(
            password=hashed,
            updated=_TIME.normalize(_TIME.now())
        ), id=id)
        return True

    def reset_password_by_identity(self, email, name, mobile, new_password):
        user = self.db.get(email=email, name=name, mobile=mobile)
        if user is None:
            return False
        self.db.update(dict(
            password=self._hash_password(new_password),
            updated=_TIME.normalize(_TIME.now())
        ), id=user.get('id'))
        return True

    def count(self, **kwargs):
        """사용자 수 조회"""
        return self.db.count(**kwargs) or 0

Model = User
