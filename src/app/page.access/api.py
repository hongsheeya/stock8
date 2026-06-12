import re

session = wiz.model("portal/season/session").use()
struct = wiz.model("struct")

def _normalize_email(email):
    return str(email or "").strip().lower()

def _normalize_mobile(mobile):
    return re.sub(r"[^0-9]", "", str(mobile or ""))

def _mask_email(email):
    email = _normalize_email(email)
    if "@" not in email:
        return email
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        local_masked = local[:1] + "*" * max(len(local) - 1, 1)
    else:
        local_masked = local[:2] + "*" * max(len(local) - 2, 1)
    return f"{local_masked}@{domain}"

def _validate_email(email):
    return re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email or "") is not None

def login():
    email = _normalize_email(wiz.request.query("email", ""))
    password = wiz.request.query("password", "")

    if not email or not password:
        wiz.response.status(400, message="이메일과 비밀번호를 입력해주세요.")

    if _validate_email(email) == False:
        wiz.response.status(400, message="올바른 이메일 형식을 입력해주세요.")

    user = struct.user.authenticate(email, password)
    if user is None:
        wiz.response.status(401, message="이메일 또는 비밀번호가 올바르지 않습니다.")

    session.set(id=user['id'], email=user['email'], name=user['name'], role=user['role'])
    wiz.response.status(200, user=user)

def signup():
    email = _normalize_email(wiz.request.query("email", ""))
    password = wiz.request.query("password", "")
    name = wiz.request.query("name", "").strip()
    mobile = _normalize_mobile(wiz.request.query("mobile", ""))

    if not email or not password or not name:
        wiz.response.status(400, message="모든 필드를 입력해주세요.")

    if _validate_email(email) == False:
        wiz.response.status(400, message="올바른 이메일 형식을 입력해주세요.")

    # 이메일 중복 체크
    orm = struct.orm
    db = orm.use("user")
    existing = db.get(email=email)
    if existing is not None:
        wiz.response.status(409, message="이미 사용 중인 이메일입니다.")

    # 비밀번호 길이 체크
    if len(password) < 8:
        wiz.response.status(400, message="비밀번호는 8자 이상이어야 합니다.")

    role = "admin" if struct.user.count() == 0 else "user"

    try:
        user_id = struct.user.create(dict(
            email=email,
            password=password,
            name=name,
            mobile=mobile,
            role=role
        ))
    except Exception as e:
        wiz.response.status(500, message="회원가입 중 오류가 발생했습니다.")

    # 자동 로그인
    user = struct.user.get(id=user_id)
    if user:
        session.set(id=user['id'], email=user['email'], name=user['name'], role=user['role'])

    wiz.response.status(200, message="회원가입이 완료되었습니다.", user=user)

def logout():
    session.clear()
    wiz.response.status(200, message="로그아웃되었습니다.")


def find_id():
    name = wiz.request.query("name", "").strip()
    mobile = _normalize_mobile(wiz.request.query("mobile", ""))

    if not name or not mobile:
        wiz.response.status(400, message="이름과 휴대폰 번호를 입력해주세요.")

    email = struct.user.find_email(name, mobile)
    if not email:
        wiz.response.status(404, message="일치하는 회원 정보를 찾지 못했습니다.")

    wiz.response.status(200, email=email, masked_email=_mask_email(email), message="가입된 아이디를 찾았습니다.")


def reset_password():
    email = _normalize_email(wiz.request.query("email", ""))
    name = wiz.request.query("name", "").strip()
    mobile = _normalize_mobile(wiz.request.query("mobile", ""))
    new_password = wiz.request.query("new_password", "")

    if not email or not name or not mobile or not new_password:
        wiz.response.status(400, message="모든 필드를 입력해주세요.")

    if _validate_email(email) == False:
        wiz.response.status(400, message="올바른 이메일 형식을 입력해주세요.")

    if len(new_password) < 8:
        wiz.response.status(400, message="비밀번호는 8자 이상이어야 합니다.")

    ok = struct.user.reset_password_by_identity(email, name, mobile, new_password)
    if ok == False:
        wiz.response.status(404, message="일치하는 회원 정보를 찾지 못했습니다.")

    wiz.response.status(200, message="비밀번호를 재설정했습니다. 새 비밀번호로 로그인해주세요.")
