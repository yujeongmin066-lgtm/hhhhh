"""마음모지 — Python 3.11 이상.
Streamlit Secrets에 DATABASE_URL을 설정하세요.
방 코드를 아는 사람은 참가할 수 있는 간단한 가족용 앱입니다.
"""
import base64
import hashlib
import html
import re
import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import certifi
import psycopg
from psycopg.rows import dict_row
import streamlit as st


st.set_page_config(
    page_title="마음모지",
    page_icon="😊",
    layout="centered",
    initial_sidebar_state="collapsed",
)

KST = ZoneInfo("Asia/Seoul")

MOODS = {
    "happy": ("😊", "행복해요", "#FFF0B8"),
    "calm": ("😌", "편안해요", "#DAEEDC"),
    "sad": ("😢", "속상해요", "#DDE9FA"),
    "angry": ("😠", "화가 나요", "#F9DDD7"),
    "tired": ("😴", "피곤해요", "#E9DFF4"),
    "talk": ("🥰", "이야기하고 싶어요", "#F8DFE7"),
}

st.markdown(
    """
    <style>
    .stApp {
        background: #FCF8F0;
        color: #35372F;
    }
    .block-container {
        max-width: 620px;
        padding: 1.4rem 1rem 3rem;
    }
    header[data-testid="stHeader"], #MainMenu, footer {
        display: none !important;
    }
    h1 { font-size: 1.65rem !important; }
    h2, h3 { font-size: 1.15rem !important; }
    .stButton button, .stFormSubmitButton button {
        min-height: 52px;
        border-radius: 17px;
        font-weight: 650;
        border: 1px solid #DEDACD;
    }
    .stButton button[kind="primary"],
    .stFormSubmitButton button[kind="primary"] {
        background: #526D55;
        border-color: #526D55;
        color: white;
    }
    [data-testid="stTextInput"] input,
    [data-testid="stTextArea"] textarea {
        background: #FFFDFA;
        border-radius: 14px;
    }
    [data-testid="stExpander"] {
        border-radius: 18px;
        background: #FFFDFA;
    }
    .card {
        border-radius: 22px;
        padding: 16px;
        margin: 10px 0;
        border: 1px solid #E6DECD;
        overflow-wrap: anywhere;
    }
    .muted {
        font-size: .83rem;
        color: #66685B;
    }
    .copy {
        white-space: pre-wrap;
        overflow-wrap: anywhere;
        margin: 8px 0;
    }
    [data-testid="stHorizontalBlock"] { gap: .5rem; }
    @media(max-width:640px) {
        [data-testid="stHorizontalBlock"] {
            flex-wrap: nowrap !important;
        }
        [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
            min-width: 0 !important;
            flex: 1 1 0 !important;
        }
        .stButton button { padding: .4rem .15rem; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

SVG = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 280 300">
  <circle cx="140" cy="143" r="124" fill="#F3E8D4"/>
  <ellipse cx="140" cy="277" rx="64" ry="10" fill="#E8DDC9"/>
  <path d="M140 223V270" stroke="#6E7962"
        stroke-width="17" stroke-linecap="round"/>
  <path d="M111 276H169" stroke="#6E7962"
        stroke-width="14" stroke-linecap="round"/>
  <rect x="86" y="32" width="108" height="202" rx="44"
        fill="#63765D"/>
  <rect x="96" y="40" width="88" height="182" rx="36"
        fill="#75886B"/>
  <circle cx="140" cy="78" r="27" fill="#F2A79B"/>
  <circle cx="140" cy="132" r="27" fill="#F9DC7B"/>
  <circle cx="140" cy="186" r="27" fill="#B5D8A4"/>
  <circle cx="131" cy="76" r="3" fill="#594F3D"/>
  <circle cx="149" cy="76" r="3" fill="#594F3D"/>
  <path d="M133 85Q140 91 147 85" fill="none"
        stroke="#594F3D" stroke-width="3" stroke-linecap="round"/>
  <path d="M130 132Q134 126 138 132M145 132Q149 126 153 132"
        fill="none" stroke="#594F3D"
        stroke-width="3" stroke-linecap="round"/>
  <path d="M132 142Q140 149 148 142" fill="none"
        stroke="#594F3D" stroke-width="3" stroke-linecap="round"/>
  <circle cx="131" cy="183" r="3" fill="#594F3D"/>
  <circle cx="149" cy="183" r="3" fill="#594F3D"/>
  <path d="M131 193Q140 203 149 193" fill="none"
        stroke="#594F3D" stroke-width="3" stroke-linecap="round"/>
  <ellipse cx="119" cy="189" rx="5" ry="3" fill="#E9A99B"/>
  <ellipse cx="161" cy="189" rx="5" ry="3" fill="#E9A99B"/>
  <path d="M85 161Q57 143 52 162M195 161Q223 143 228 162"
        fill="none" stroke="#75886B"
        stroke-width="12" stroke-linecap="round"/>
  <path d="M218 55C202 37 187 61 218 80C249 61 234 37 218 55"
        fill="#DCA397"/>
</svg>
"""


def esc(value):
    return html.escape(str(value), quote=True)


def code_hash(code):
    return hashlib.sha256(code.strip().upper().encode()).hexdigest()


def valid_name(name):
    if not 1 <= len(name.strip()) <= 20:
        raise ValueError("내 이름을 1~20자로 입력해 주세요.")


def valid_code(code):
    if not re.fullmatch(r"[A-Za-z0-9]{6,24}", code.strip()):
        raise ValueError(
            "방 코드는 영문·숫자 6~24자로 입력해 주세요. "
            "대소문자는 구분하지 않아요."
        )


def raw_db():
    try:
        url = str(st.secrets.get("DATABASE_URL", "")).strip()
    except Exception:
        url = ""

    if not url.startswith(("postgresql://", "postgres://")):
        raise ValueError(
            "공유 저장소를 먼저 연결해 주세요. "
            "Streamlit의 Settings → Secrets에 DATABASE_URL을 설정하면 됩니다."
        )

    return psycopg.connect(
        url,
        sslmode="verify-full",
        sslrootcert=certifi.where(),
        connect_timeout=12,
        row_factory=dict_row,
        prepare_threshold=None,
    )


@st.cache_resource(show_spinner=False)
def init_database(fingerprint):
    with raw_db() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS ms_rooms(
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                code_hash TEXT UNIQUE NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS ms_people(
                id TEXT PRIMARY KEY,
                room_id TEXT NOT NULL
                    REFERENCES ms_rooms(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                UNIQUE(room_id, name),
                UNIQUE(id, room_id)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS ms_moods(
                person_id TEXT PRIMARY KEY,
                room_id TEXT NOT NULL,
                mood TEXT NOT NULL CHECK(
                    mood IN ('happy','calm','sad','angry','tired','talk')
                ),
                reason TEXT NOT NULL CHECK(length(reason)<=150),
                relief TEXT NOT NULL CHECK(length(relief)<=150),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                FOREIGN KEY(person_id, room_id)
                    REFERENCES ms_people(id, room_id) ON DELETE CASCADE
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS ms_custom_emojis(
                id TEXT PRIMARY KEY,
                room_id TEXT NOT NULL
                    REFERENCES ms_rooms(id) ON DELETE CASCADE,
                emoji TEXT NOT NULL CHECK(length(emoji)<=32),
                label TEXT NOT NULL CHECK(length(label)<=20),
                color TEXT NOT NULL,
                UNIQUE(room_id, emoji, label)
            )
        """)
        c.execute(
            "ALTER TABLE ms_moods "
            "ADD COLUMN IF NOT EXISTS custom_id TEXT"
        )
        c.execute("""
            CREATE TABLE IF NOT EXISTS ms_limits(
                scope TEXT PRIMARY KEY,
                since TIMESTAMPTZ NOT NULL DEFAULT now(),
                n INTEGER NOT NULL DEFAULT 0
            )
        """)


def db():
    try:
        url = str(st.secrets.get("DATABASE_URL", ""))
    except Exception:
        url = ""

    init_database(hashlib.sha256(url.encode()).hexdigest())
    return raw_db()


def allowed(scope, limit):
    with db() as c:
        c.execute(
            "INSERT INTO ms_limits(scope) VALUES (%s) "
            "ON CONFLICT DO NOTHING",
            (scope,),
        )
        row = c.execute(
            "SELECT *, now() AS clock FROM ms_limits "
            "WHERE scope=%s FOR UPDATE",
            (scope,),
        ).fetchone()

        if (row["clock"] - row["since"]).total_seconds() >= 300:
            c.execute(
                "UPDATE ms_limits SET since=now(), n=1 WHERE scope=%s",
                (scope,),
            )
            return True

        if row["n"] >= limit:
            return False

        c.execute(
            "UPDATE ms_limits SET n=n+1 WHERE scope=%s",
            (scope,),
        )
        return True


def enter(room, person, code):
    st.session_state.clear()
    st.session_state.update(
        started=True,
        room=room,
        person=person,
        invite=code.strip().upper(),
        until=time.time() + 12 * 3600,
    )
    st.rerun()


def create_room(title, name, code):
    valid_name(name)
    valid_code(code)

    if not 1 <= len(title.strip()) <= 30:
        raise ValueError("방 이름은 1~30자로 입력해 주세요.")

    if not allowed("create", 30):
        raise ValueError("방 생성 요청이 많아요. 5분 뒤 다시 시도해 주세요.")

    rid = uuid.uuid4().hex
    pid = uuid.uuid4().hex

    try:
        with db() as c:
            c.execute(
                "INSERT INTO ms_rooms(id,title,code_hash) "
                "VALUES (%s,%s,%s)",
                (rid, title.strip(), code_hash(code)),
            )
            c.execute(
                "INSERT INTO ms_people(id,room_id,name) "
                "VALUES (%s,%s,%s)",
                (pid, rid, name.strip()),
            )
    except psycopg.errors.UniqueViolation:
        raise ValueError(
            "이미 사용 중인 방 코드예요. 다른 코드를 정해 주세요."
        ) from None

    return rid, pid


def join_room(name, code):
    valid_name(name)
    valid_code(code)
    hashed = code_hash(code)

    if (
        not allowed("join-global", 120)
        or not allowed("join:" + hashed, 20)
    ):
        raise ValueError("참가 시도가 많아요. 5분 뒤 다시 시도해 주세요.")

    with db() as c:
        room = c.execute(
            "SELECT id FROM ms_rooms WHERE code_hash=%s FOR UPDATE",
            (hashed,),
        ).fetchone()

        if not room:
            raise ValueError("일치하는 방이 없어요. 코드를 다시 확인해 주세요.")

        duplicate = c.execute(
            "SELECT id FROM ms_people WHERE room_id=%s AND name=%s",
            (room["id"], name.strip()),
        ).fetchone()

        if duplicate:
            raise ValueError(
                "이미 같은 이름이 있어요. "
                "구분되는 이름을 입력해 주세요. 예: 민수2"
            )

        total = c.execute(
            "SELECT count(*) AS n FROM ms_people WHERE room_id=%s",
            (room["id"],),
        ).fetchone()["n"]

        if total >= 30:
            raise ValueError("이 방은 참가 인원 30명이 가득 찼어요.")

        pid = uuid.uuid4().hex
        c.execute(
            "INSERT INTO ms_people(id,room_id,name) VALUES (%s,%s,%s)",
            (pid, room["id"], name.strip()),
        )

    return room["id"], pid


def me():
    ss = st.session_state

    if time.time() >= ss.get("until", 0):
        raise PermissionError()

    with db() as c:
        person = c.execute(
            """
            SELECT p.id, p.room_id, p.name, r.title
            FROM ms_people p
            JOIN ms_rooms r ON r.id=p.room_id
            WHERE p.id=%s AND p.room_id=%s
            """,
            (ss.get("person"), ss.get("room")),
        ).fetchone()

    if not person:
        raise PermissionError()

    return person


def all_moods():
    person = me()

    with db() as c:
        return c.execute(
            """
            SELECT
                p.id,
                p.name,
                COALESCE(m.custom_id,m.mood) AS mood,
                m.reason,
                m.relief,
                m.updated_at
            FROM ms_people p
            LEFT JOIN ms_moods m
                ON m.person_id=p.id AND m.room_id=p.room_id
            WHERE p.room_id=%s
            ORDER BY p.name
            """,
            (person["room_id"],),
        ).fetchall()


def room_emojis():
    person = me()
    catalog = dict(MOODS)

    with db() as c:
        added = c.execute(
            "SELECT id,emoji,label,color FROM ms_custom_emojis "
            "WHERE room_id=%s ORDER BY label,id",
            (person["room_id"],),
        ).fetchall()

    catalog.update({
        row["id"]: (row["emoji"], row["label"], row["color"])
        for row in added
    })
    return catalog


def add_emoji(emoji, label, color):
    person = me()
    emoji = emoji.strip()
    label = label.strip()

    has_emoji = any(
        0x1F000 <= ord(ch) <= 0x1FAFF
        or 0x2600 <= ord(ch) <= 0x27BF
        or ord(ch) == 0x20E3
        or ord(ch) in (
            0x00A9, 0x00AE, 0x203C, 0x2049, 0x2122,
            0x2139, 0x3030, 0x303D, 0x3297, 0x3299,
        )
        for ch in emoji
    )

    if not 1 <= len(emoji) <= 32 or not has_emoji:
        raise ValueError(
            "휴대폰 이모티콘 키보드에서 이모티콘을 골라 넣어 주세요. "
            "예: 🤩, 🥹, 🫶"
        )

    if not 1 <= len(label) <= 20:
        raise ValueError("기분 이름은 1~20자로 입력해 주세요.")

    if color not in (
        "#FFF0B8", "#DAEEDC", "#DDE9FA",
        "#F9DDD7", "#E9DFF4", "#F8DFE7",
    ):
        raise ValueError("목록에 있는 배경색을 골라 주세요.")

    key = uuid.uuid4().hex

    try:
        with db() as c:
            c.execute(
                "SELECT id FROM ms_rooms WHERE id=%s FOR UPDATE",
                (person["room_id"],),
            )
            count = c.execute(
                "SELECT count(*) AS n FROM ms_custom_emojis "
                "WHERE room_id=%s",
                (person["room_id"],),
            ).fetchone()["n"]

            if count >= 24:
                raise ValueError(
                    "한 방에 직접 추가하는 이모티콘은 24개까지예요."
                )

            c.execute(
                "INSERT INTO ms_custom_emojis"
                "(id,room_id,emoji,label,color) VALUES (%s,%s,%s,%s,%s)",
                (key, person["room_id"], emoji, label, color),
            )
    except psycopg.errors.UniqueViolation:
        raise ValueError(
            "이미 같은 이모티콘과 기분 이름이 있어요."
        ) from None

    return key


def save_mood(mood, reason, relief):
    person = me()

    if (
        mood not in room_emojis()
        or len(reason) > 150
        or len(relief) > 150
    ):
        raise ValueError("입력 내용을 확인해 주세요.")

    with db() as c:
        c.execute(
            """
            INSERT INTO ms_moods(
                person_id,room_id,mood,reason,relief,custom_id
            )
            VALUES (%s,%s,%s,%s,%s,%s)
            ON CONFLICT(person_id) DO UPDATE SET
                mood=EXCLUDED.mood,
                custom_id=EXCLUDED.custom_id,
                reason=EXCLUDED.reason,
                relief=EXCLUDED.relief,
                updated_at=clock_timestamp()
            """,
            (
                person["id"],
                person["room_id"],
                mood if mood in MOODS else "happy",
                reason.strip(),
                relief.strip(),
                None if mood in MOODS else mood,
            ),
        )


def leave():
    st.session_state.clear()
    st.session_state.started = True


def start():
    st.session_state.started = True


def lobby():
    st.title("마음모지 😊")
    st.caption("방을 만들거나 가족에게 받은 코드로 참가하세요.")

    make, join = st.tabs(["＋ 방 만들기", "🔑 코드로 참가"])

    with make:
        with st.form("make", clear_on_submit=False):
            title = st.text_input(
                "방 이름",
                placeholder="예: 우리 가족 마음방",
                max_chars=30,
            )
            name = st.text_input(
                "자기 이름",
                placeholder="예: 민수",
                max_chars=20,
            )
            code = st.text_input(
                "사용할 방 코드",
                placeholder="영문·숫자 6~24자",
                max_chars=24,
                type="password",
            )
            submit = st.form_submit_button(
                "방 만들고 입장하기",
                type="primary",
                use_container_width=True,
            )

        if submit:
            rid, pid = create_room(title, name, code)
            enter(rid, pid, code)

    with join:
        with st.form("join", clear_on_submit=False):
            name = st.text_input(
                "자기 이름",
                placeholder="가족에게 보일 이름",
                max_chars=20,
            )
            code = st.text_input(
                "방 코드",
                placeholder="가족에게 받은 코드를 입력하세요",
                max_chars=24,
                type="password",
            )
            submit = st.form_submit_button(
                "이 방에 참가하기",
                type="primary",
                use_container_width=True,
            )

        if submit:
            rid, pid = join_room(name, code)
            enter(rid, pid, code)

    st.caption(
        "코드를 아는 사람은 참가할 수 있어요. "
        "추측하기 어려운 코드를 정하고 가족에게만 알려 주세요."
    )


@st.fragment(run_every="10s")
def family_panel():
    try:
        person = me()
        data = all_moods()
        catalog = room_emojis()

        st.subheader(f"함께 있는 가족 · {len(data)}명")

        if st.button("↻ 새로고침", use_container_width=True):
            st.rerun(scope="fragment")

        for row in data:
            name = esc(row["name"])
            if row["id"] == person["id"]:
                name += " · 나"

            if not row["mood"]:
                st.markdown(
                    f'<div class="card" style="background:#F3EFE5">'
                    f'<b>{name}</b>'
                    '<p class="muted">'
                    '아직 마음을 등록하지 않았어요 🌱'
                    '</p></div>',
                    unsafe_allow_html=True,
                )
                continue

            emoji, label, color = catalog.get(
                row["mood"],
                ("🙂", "등록한 마음", "#DAEEDC"),
            )
            dt = row["updated_at"].astimezone(KST)
            old = (
                " · 지난 상태"
                if dt.date() != datetime.now(KST).date()
                else ""
            )

            reason = ""
            if row["reason"]:
                reason = (
                    '<div class="copy">'
                    '<span class="muted">이런 일이 있었어요</span><br>'
                    f'{esc(row["reason"])}</div>'
                )

            relief = ""
            if row["relief"]:
                relief = (
                    '<div class="copy">'
                    '<span class="muted">'
                    '이렇게 하면 기분이 풀려요</span><br>'
                    f'{esc(row["relief"])}</div>'
                )

            st.markdown(
                f'<div class="card" style="background:{color}">'
                f'<b>{name}</b>'
                f'<p><span style="font-size:1.8rem">{esc(emoji)}</span> '
                f'{esc(label)}{old}</p>'
                f'{reason}{relief}'
                f'<div class="muted">{dt:%m/%d %H:%M} 변경</div>'
                '</div>',
                unsafe_allow_html=True,
            )

        st.caption("10초마다 가족의 마음을 새로 확인해요.")

    except PermissionError:
        st.info("접속이 만료됐어요. 페이지를 새로고침해 주세요.")
    except psycopg.Error:
        st.warning("가족 상태를 불러오지 못했어요. 잠시 뒤 다시 시도해 주세요.")


def room_screen():
    person = me()

    left, right = st.columns([4, 1])
    left.subheader("🏡 " + person["title"])

    if right.button("나가기", use_container_width=True):
        leave()
        st.rerun()

    with st.expander("🔑 가족에게 방 코드 알려주기"):
        st.code(st.session_state.invite, language=None)
        st.caption(
            "다른 가족은 시작 → 코드로 참가에서 "
            "자기 이름과 이 코드를 입력하면 돼요."
        )

    st.subheader(person["name"] + "님, 지금 기분은 어떤가요?")

    own = next(
        (row for row in all_moods() if row["id"] == person["id"]),
        None,
    )

    if "mood" not in st.session_state:
        st.session_state.mood = (
            own["mood"] if own and own["mood"] else None
        )

    catalog = room_emojis()
    items = list(catalog.items())

    for offset in range(0, len(items), 3):
        cols = st.columns(3)

        for col, (key, (emoji, label, color)) in zip(
            cols, items[offset:offset + 3]
        ):
            if col.button(
                emoji + " " + label,
                key="mood_" + key,
                type=(
                    "primary"
                    if st.session_state.mood == key
                    else "secondary"
                ),
                use_container_width=True,
            ):
                st.session_state.mood = key
                st.rerun()

    with st.expander("＋ 우리 가족 이모티콘 추가"):
        st.caption(
            "추가한 이모티콘은 이 방의 가족이 함께 사용할 수 있어요."
        )
        with st.form("add_custom", clear_on_submit=True):
            custom_emoji = st.text_input(
                "이모티콘",
                placeholder="예: 🤩",
                max_chars=32,
            )
            custom_label = st.text_input(
                "기분 이름",
                placeholder="예: 설레요",
                max_chars=20,
            )
            colors = {
                "노랑": "#FFF0B8",
                "초록": "#DAEEDC",
                "파랑": "#DDE9FA",
                "주황": "#F9DDD7",
                "보라": "#E9DFF4",
                "분홍": "#F8DFE7",
            }
            selected_color = st.selectbox(
                "카드 배경색", list(colors)
            )
            add = st.form_submit_button(
                "이모티콘 추가하기",
                use_container_width=True,
            )

        if add:
            key = add_emoji(
                custom_emoji,
                custom_label,
                colors[selected_color],
            )
            st.session_state.mood = key
            st.rerun()

    if st.session_state.mood:
        emoji, label, _ = catalog[st.session_state.mood]
        st.caption("선택한 마음: " + emoji + " " + label)
    else:
        st.caption("위의 이모티콘을 하나 눌러 주세요.")

    with st.form("editor", clear_on_submit=False):
        reason = st.text_area(
            "이런 기분이 든 이유 · 선택",
            value=(own["reason"] or "") if own else "",
            placeholder="예: 오늘 친구와 다퉜어요",
            max_chars=150,
            height=90,
            key="reason",
        )
        relief = st.text_input(
            "기분이 풀리는 방법 · 선택",
            value=(own["relief"] or "") if own else "",
            placeholder="예: 잠깐 쉬거나 이야기를 들어주면 좋아요",
            max_chars=150,
            key="relief",
        )
        sent = st.form_submit_button(
            (
                "내 마음 수정하기"
                if own and own["mood"]
                else "내 마음 등록하기"
            ),
            type="primary",
            use_container_width=True,
        )

    if sent:
        if not st.session_state.mood:
            st.warning("이모티콘을 먼저 하나 골라 주세요.")
        else:
            save_mood(st.session_state.mood, reason, relief)
            st.session_state.notice = "마음을 전했어요 🌿"
            st.rerun()

    if st.session_state.pop("notice", None):
        st.success("마음을 전했어요 🌿")

    family_panel()

    st.caption(
        "이름만으로는 본인 확인이 안 돼요. "
        "이 간단 버전은 접속이 유지되는 동안 내 마음을 수정할 수 있어요. "
        "나가거나 연결이 끊긴 뒤 재입장할 때는 새 이름이 필요할 수 있어요. "
        "기존 기록은 방에 남습니다."
    )


def run():
    if not st.session_state.get("started"):
        image = base64.b64encode(SVG.encode()).decode()

        st.markdown(
            '<div style="height:12vh"></div>'
            '<div style="text-align:center">'
            '<img alt="웃는 귀여운 신호등" '
            f'src="data:image/svg+xml;base64,{image}" width="230">'
            '</div>',
            unsafe_allow_html=True,
        )
        _, center, _ = st.columns([1, 2, 1])
        center.button(
            "시작",
            type="primary",
            on_click=start,
            use_container_width=True,
        )
        return

    if (
        st.session_state.get("person")
        and time.time() < st.session_state.get("until", 0)
    ):
        room_screen()
    else:
        if st.session_state.get("person"):
            leave()
        lobby()


try:
    run()
except ValueError as error:
    st.warning(str(error))
except PermissionError:
    leave()
    st.rerun()
except psycopg.Error:
    st.error(
        "저장소에 연결하지 못했어요. 잠시 후 다시 시도해 주세요. "
        "관리자는 Streamlit Secrets의 Neon 연결 주소와 "
        "테이블 생성 권한을 확인해 주세요."
    )
    if st.button("다시 시도", use_container_width=True):
        st.rerun()
