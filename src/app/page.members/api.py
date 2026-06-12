struct = wiz.model("struct")

def list():
    text = wiz.request.query("text", "")
    role = wiz.request.query("role", "")

    members = struct.user.list(text=text, role=role)

    # 아바타 컬러 추가
    colors = [
        "bg-indigo-100 text-indigo-700",
        "bg-pink-100 text-pink-700",
        "bg-green-100 text-green-700",
        "bg-amber-100 text-amber-700",
        "bg-cyan-100 text-cyan-700",
        "bg-violet-100 text-violet-700",
    ]
    for i, m in enumerate(members):
        m["avatarColor"] = colors[i % len(colors)]
        m["joined"] = str(m.get("created", ""))[:10]

    wiz.response.status(200, members)

def invite():
    email = str(wiz.request.query("email", "") or "").strip().lower()
    role = wiz.request.query("role", "user")

    if not email:
        wiz.response.status(400, message="이메일을 입력해주세요.")

    if role not in ["admin", "user"]:
        wiz.response.status(400, message="허용되지 않은 역할입니다.")

    # 이미 존재하는지 확인
    existing = struct.user.db.get(email=email)
    if existing:
        wiz.response.status(400, message="이미 등록된 사용자입니다.")

    # 기본 비밀번호로 사용자 생성
    struct.user.create(dict(
        email=email,
        password="welcome1",
        name=email.split("@")[0],
        role=role
    ))

    wiz.response.status(200)

def remove():
    id = wiz.request.query("id", "")
    if not id:
        wiz.response.status(400, message="ID가 필요합니다.")

    struct.user.db.delete(id=id)
    wiz.response.status(200)
