"""가족 마음 신호등 | Python 3.11+.
Streamlit Secrets: DATABASE_URL="Neon PostgreSQL 연결 문자열"
선택: APP_URL="배포 주소". 비밀번호와 PIN은 앱에서 만들며 솔트 해시로 저장합니다.
기존 fm_* 테이블은 건드리지 않습니다. 새 mh_* 테이블로 방별 데이터를 저장합니다.
"""
import base64
import hashlib
import hmac
import html
import io
import re
import secrets
import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
import certifi
import psycopg
from psycopg.rows import dict_row
import qrcode
import streamlit as st

st.set_page_config(page_title="가족 마음 신호등", page_icon="🏡", layout="centered", initial_sidebar_state="collapsed")
KST = ZoneInfo("Asia/Seoul")
TTL = 7200
STATES = {"green": ("🟢", "초록불", "대화하고 싶어요.", "#DDEDE0"), "yellow": ("🟡", "노란불", "위로가 필요해요. 먼저 다정하게 물어봐 주세요.", "#FFF0C2"), "red": ("🔴", "빨간불", "지금은 혼자 쉬고 싶어요.", "#F6DFD9")}
CARES = ["선택 안 함", "이야기 들어주기", "응원해 주기", "잠시 기다려 주기"]
SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 260 260">\n    <circle cx="130" cy="130" r="120" fill="#F3E8D5"/>\n    <path d="M45 125 L130 52 L215 125" fill="none" stroke="#B87660" stroke-width="19" stroke-linecap="round" stroke-linejoin="round"/>\n    <path d="M63 120V207Q63 218 76 218H184Q197 218 197 205V120L130 66Z" fill="#FFFDF5"/>\n    <rect x="89" y="135" width="82" height="90" rx="24" fill="#5A6959"/>\n    <circle cx="130" cy="153" r="12" fill="#EDAAA0"/><circle cx="130" cy="181" r="12" fill="#F3D578"/><circle cx="130" cy="209" r="12" fill="#A6CDA8"/>\n    <circle cx="88" cy="114" r="5" fill="#665244"/><circle cx="172" cy="114" r="5" fill="#665244"/>\n    <path d="M116 113Q130 126 144 113" fill="none" stroke="#665244" stroke-width="4" stroke-linecap="round"/>\n    <ellipse cx="80" cy="125" rx="9" ry="5" fill="#EAC2AF"/><ellipse cx="180" cy="125" rx="9" ry="5" fill="#EAC2AF"/>\n    <path d="M211 64C197 48 179 70 211 89C243 70 225 48 211 64" fill="#CF8F7B"/></svg>'
st.markdown('''<style>
.stApp {background:#FBF7EF;color:#35352F;}
.block-container{max-width:660px;padding:1.1rem 1rem 2.4rem;}
header[data-testid="stHeader"], [data-testid="stToolbar"], #MainMenu, footer {display:none!important;}
h1{font-size:1.55rem!important;} h2,h3{font-size:1.12rem!important;}
.stButton button,.stFormSubmitButton button{min-height:48px;border-radius:17px;border:1px solid #DED8CA;font-weight:650;}
.stButton button[kind="primary"],.stFormSubmitButton button[kind="primary"]{background:#435F4D;color:white;border:0;}
[data-testid="stTextInput"] input,[data-baseweb="select"]>div{border-radius:14px;background:#FFFDFA;}
[data-testid="stExpander"]{background:#FFFDFA;border-radius:18px;}
[data-testid="stHorizontalBlock"]{gap:.55rem;}
.card{border-radius:20px;padding:14px 16px 10px;margin-top:8px;border:1px solid #E3DDCF;overflow-wrap:anywhere;}
.card strong{font-size:1.03rem;} .meta{font-size:.78rem;color:#5F6058;margin-top:9px;}
.msg{background:#ffffff99;border-radius:12px;padding:8px 10px;margin:8px 0;white-space:pre-wrap;}
.small{font-size:.85rem;color:#53554B;} .stCaption{color:#5D6055;}
@media(max-width:640px){[data-testid="stHorizontalBlock"]{flex-wrap:nowrap!important;} [data-testid="stHorizontalBlock"]>[data-testid="stColumn"]{min-width:0!important;flex:1 1 0!important;} .stButton button{padding:.35rem .25rem;font-size:.88rem;}}
</style>''', unsafe_allow_html=True)

def esc(text):
    return html.escape(str(text), quote=True)

def secret_hash(value, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(value.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1, dklen=32).hex()
    return salt + ":" + digest

def verify(value, stored):
    salt, _ = stored.split(":", 1)
    return hmac.compare_digest(secret_hash(value, salt), stored)

def db():
    return psycopg.connect(DB_URL, sslmode="verify-full", sslrootcert=certifi.where(), connect_timeout=12, row_factory=dict_row, prepare_threshold=None)

@st.cache_resource(show_spinner=False)
def init_db(fingerprint):
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS mh_rooms (
            id TEXT PRIMARY KEY, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
            password_hash TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
        c.execute("""CREATE TABLE IF NOT EXISTS mh_members (
            id TEXT PRIMARY KEY, room_id TEXT NOT NULL REFERENCES mh_rooms(id) ON DELETE CASCADE,
            name TEXT NOT NULL, pin_hash TEXT NOT NULL, UNIQUE(room_id,name), UNIQUE(id,room_id))""")
        c.execute("""CREATE TABLE IF NOT EXISTS mh_status (
            member_id TEXT PRIMARY KEY, room_id TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('green','yellow','red')),
            message TEXT NOT NULL CHECK(length(message)<=100), care TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            FOREIGN KEY(member_id,room_id) REFERENCES mh_members(id,room_id) ON DELETE CASCADE)""")
        c.execute("""CREATE TABLE IF NOT EXISTS mh_reactions (
            target_id TEXT NOT NULL REFERENCES mh_status(member_id) ON DELETE CASCADE,
            actor_id TEXT NOT NULL REFERENCES mh_members(id) ON DELETE CASCADE,
            kind TEXT NOT NULL CHECK(kind IN ('응원해요','기다릴게요')),
            PRIMARY KEY(target_id,actor_id), CHECK(target_id<>actor_id))""")
        c.execute("""CREATE TABLE IF NOT EXISTS mh_limits (
            scope TEXT PRIMARY KEY, started_at TIMESTAMPTZ NOT NULL DEFAULT now(), attempts INTEGER NOT NULL DEFAULT 0)""")

def allowed(scope, limit):
    # Persistent shared limits, including across app restarts. No browser-only counters.
    with db() as c:
        c.execute("INSERT INTO mh_limits(scope) VALUES (%s) ON CONFLICT DO NOTHING", (scope,))
        row = c.execute("SELECT *,now() AS clock FROM mh_limits WHERE scope=%s FOR UPDATE", (scope,)).fetchone()
        if (row['clock']-row['started_at']).total_seconds()>=300:
            c.execute("UPDATE mh_limits SET attempts=1,started_at=now() WHERE scope=%s", (scope,)); return True
        if row['attempts']>=limit: return False
        c.execute("UPDATE mh_limits SET attempts=attempts+1 WHERE scope=%s", (scope,)); return True

def identity():
    ss = st.session_state
    if time.time()>=ss.get('until',0): raise PermissionError()
    with db() as c:
        row=c.execute("""SELECT m.id,m.name,m.room_id,r.name AS room_name,r.code
            FROM mh_members m JOIN mh_rooms r ON r.id=m.room_id
            WHERE m.id=%s AND m.room_id=%s""", (ss.get('actor'),ss.get('room'))).fetchone()
    if not row: raise PermissionError()
    return row

def enter(room, member):
    st.session_state.clear()
    st.session_state.update(started=True, room=room, actor=member, until=time.time()+TTL)
    st.rerun()

def logout():
    st.session_state.clear(); st.session_state.started=True

def validate(name, pin):
    if not name.strip() or len(name.strip())>20: raise ValueError('이름은 1~20자로 입력해 주세요.')
    if not re.fullmatch(r'[0-9]{6,12}',pin): raise ValueError('개인 PIN은 숫자 6~12자리로 입력해 주세요.')

def create_room(title, password, name, pin):
    validate(name,pin)
    if not title.strip() or len(title.strip())>30: raise ValueError('방 이름은 1~30자로 입력해 주세요.')
    if not 12<=len(password)<=128: raise ValueError('방 비밀번호는 12~128자로 설정해 주세요.')
    if not allowed('create:global',20): raise ValueError('방 생성 요청이 많아요. 5분 뒤 다시 시도해 주세요.')
    rid,mid=uuid.uuid4().hex,uuid.uuid4().hex
    alphabet='ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    code=''.join(secrets.choice(alphabet) for _ in range(10))
    ph,nh=secret_hash(password),secret_hash(pin)
    with db() as c:
        c.execute('INSERT INTO mh_rooms(id,code,name,password_hash) VALUES (%s,%s,%s,%s)',(rid,code,title.strip(),ph))
        c.execute('INSERT INTO mh_members(id,room_id,name,pin_hash) VALUES (%s,%s,%s,%s)',(mid,rid,name.strip(),nh))
    return rid,mid

def room_gate(code, password):
    code=re.sub(r'[\s-]','',code).upper()
    # One global ceiling plus per-code ceiling limits arbitrary-code brute force.
    if not allowed('gate:global',100) or not allowed('gate:'+hashlib.sha256(code.encode()).hexdigest(),12):
        raise ValueError('입장 시도가 많아요. 5분 뒤 다시 시도해 주세요.')
    with db() as c: row=c.execute('SELECT id,password_hash FROM mh_rooms WHERE code=%s',(code,)).fetchone()
    if not row:
        verify(password,DUMMY_HASH)
        raise ValueError('방 코드 또는 방 비밀번호를 확인해 주세요.')
    if not verify(password,row['password_hash']): raise ValueError('방 코드 또는 방 비밀번호를 확인해 주세요.')
    return row['id']

def join_member(rid, name, pin, new):
    validate(name,pin)
    if not allowed('member:'+rid,15): raise ValueError('확인 시도가 많아요. 5분 뒤 다시 시도해 주세요.')
    with db() as c:
        # Lock the room to serialize new member registrations and capacity checks.
        c.execute('SELECT id FROM mh_rooms WHERE id=%s FOR UPDATE',(rid,)).fetchone()
        row=c.execute('SELECT id,pin_hash FROM mh_members WHERE room_id=%s AND name=%s',(rid,name.strip())).fetchone()
        if new:
            if row: raise ValueError('이미 등록된 이름이에요. 다른 이름을 쓰거나 기존 구성원으로 로그인해 주세요.')
            total=c.execute('SELECT count(*) AS n FROM mh_members WHERE room_id=%s',(rid,)).fetchone()['n']
            if total>=20: raise ValueError('한 방에는 최대 20명까지 등록할 수 있어요.')
            mid=uuid.uuid4().hex
            c.execute('INSERT INTO mh_members(id,room_id,name,pin_hash) VALUES (%s,%s,%s,%s)',(mid,rid,name.strip(),secret_hash(pin)))
            return mid
        if not row or not verify(pin,row['pin_hash']): raise ValueError('이름 또는 개인 PIN을 확인해 주세요.')
        return row['id']

def save(state,message,care):
    me=identity()
    if state not in STATES or len(message)>100 or care not in CARES: raise ValueError('입력값을 확인해 주세요.')
    with db() as c:
        c.execute('''INSERT INTO mh_status(member_id,room_id,state,message,care) VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT(member_id) DO UPDATE SET state=EXCLUDED.state,message=EXCLUDED.message,care=EXCLUDED.care,updated_at=clock_timestamp()''',
            (me['id'],me['room_id'],state,message,'' if care==CARES[0] else care))
        c.execute('DELETE FROM mh_reactions WHERE target_id=%s',(me['id'],))

def delete():
    me=identity()
    with db() as c: c.execute('DELETE FROM mh_status WHERE member_id=%s AND room_id=%s',(me['id'],me['room_id']))

def react(target,kind,revision):
    me=identity()
    if target==me['id'] or kind not in ('응원해요','기다릴게요'): return False
    with db() as c:
        row=c.execute('SELECT updated_at FROM mh_status WHERE member_id=%s AND room_id=%s FOR UPDATE',(target,me['room_id'])).fetchone()
        if not row or row['updated_at']!=revision or revision.astimezone(KST).date()!=datetime.now(KST).date(): return False
        c.execute('''INSERT INTO mh_reactions(target_id,actor_id,kind) VALUES (%s,%s,%s)
            ON CONFLICT(target_id,actor_id) DO UPDATE SET kind=EXCLUDED.kind''',(target,me['id'],kind))
    return True

def rows():
    me=identity()
    with db() as c:
        return c.execute('''SELECT m.id,m.name,s.state,s.message,s.care,s.updated_at,
          (SELECT count(*) FROM mh_reactions r WHERE r.target_id=m.id AND r.kind='응원해요') AS cheers,
          (SELECT count(*) FROM mh_reactions r WHERE r.target_id=m.id AND r.kind='기다릴게요') AS waits,
          (SELECT kind FROM mh_reactions r WHERE r.target_id=m.id AND r.actor_id=%s) AS mine
          FROM mh_members m LEFT JOIN mh_status s ON s.member_id=m.id AND s.room_id=m.room_id
          WHERE m.room_id=%s ORDER BY m.name''',(me['id'],me['room_id'])).fetchall()

DUMMY_HASH=secret_hash('invalid-password', '0'*32)

def start(): st.session_state.started=True

def login_screen():
    st.title('우리 가족 로그인')
    st.caption('작은 신호로, 서로의 마음을 더 다정하게.')
    create_tab,join_tab=st.tabs(['🏡 방 만들기','🔑 방 코드로 입장'])
    with create_tab:
        with st.form('create',clear_on_submit=True):
            title=st.text_input('방 이름',placeholder='예: 우리 집',max_chars=30)
            password=st.text_input('새 방 비밀번호',type='password',help='가족끼리만 공유할 12자 이상의 비밀번호',max_chars=128)
            name=st.text_input('내 이름',max_chars=20,placeholder='가족에게 보일 이름')
            pin=st.text_input('새 개인 PIN',type='password',max_chars=12,help='숫자 6~12자리. 내 상태를 수정할 때 나를 확인하는 번호예요.')
            confirm=st.text_input('개인 PIN 확인',type='password',max_chars=12)
            submitted=st.form_submit_button('우리 가족 방 만들기',type='primary',use_container_width=True)
        if submitted:
            if pin!=confirm: st.error('개인 PIN 확인이 일치하지 않아요.')
            else:
                rid,mid=create_room(title,password,name,pin)
                enter(rid,mid)
    with join_tab:
        with st.form('join',clear_on_submit=True):
            code=st.text_input('방 코드',max_chars=24,placeholder='가족에게 받은 영문·숫자 코드')
            password=st.text_input('방 비밀번호',type='password',max_chars=128)
            mode=st.radio('구성원 확인',['기존 구성원 로그인','처음 참여해요'],horizontal=True)
            name=st.text_input('내 이름',max_chars=20,placeholder='기존 구성원은 처음 등록한 이름')
            pin=st.text_input('내 개인 PIN',type='password',max_chars=12)
            confirm=st.text_input('처음 참여할 때만 PIN 확인',type='password',max_chars=12)
            submitted=st.form_submit_button('우리 가족 방에 들어가기',type='primary',use_container_width=True)
        if submitted:
            new=mode=='처음 참여해요'
            if new and pin!=confirm: st.error('개인 PIN 확인이 일치하지 않아요.')
            else:
                rid=room_gate(code,password)
                mid=join_member(rid,name,pin,new)
                enter(rid,mid)
    st.caption('방 코드만으로는 입장할 수 없어요. 방 비밀번호와 내 PIN도 필요해요.')

@st.fragment(run_every='20s')
def family_cards():
    try:
        me=identity()
        st.subheader('가족의 마음')
        data=rows()
        for row in data:
            mine=row['id']==me['id']
            name=esc(row['name'])+(' · 나' if mine else '')
            if not row['state']:
                st.markdown(f'<div class="card" style="background:#F0EDE5"><strong>{name}</strong><p class="small">아직 등록하지 않았어요</p></div>',unsafe_allow_html=True)
                continue
            emoji,label,desc,color=STATES[row['state']]
            updated=row['updated_at'].astimezone(KST)
            stale=updated.date()!=datetime.now(KST).date()
            badge=' · 지난 상태' if stale else ''
            msg=f'<div class="msg">{esc(row["message"])}</div>' if row['message'] else ''
            care=f'<div class="small">원하는 배려 · {esc(row["care"])}</div>' if row['care'] else ''
            reminder='<div class="small">지금은 대화나 답장을 재촉하지 말아 주세요.</div>' if row['state']=='red' else ''
            st.markdown(f'<div class="card" style="background:{"#EEECE6" if stale else color}"><strong>{name}</strong><p>{emoji} {label}{badge}<br><span class="small">{desc}</span></p>{msg}{care}{reminder}<div class="meta">마지막 변경 {updated:%m/%d %H:%M} · 응원 {row["cheers"]} · 기다림 {row["waits"]}</div></div>',unsafe_allow_html=True)
            if not mine and not stale:
                cols=st.columns(2)
                for col,kind in zip(cols,['응원해요','기다릴게요']):
                    if col.button(('✓ ' if row['mine']==kind else '')+kind,key=row['id']+kind,use_container_width=True):
                        if react(row['id'],kind,row['updated_at']): st.rerun(scope='fragment')
                        else: st.info('상태가 바뀌었어요. 새로고침해 주세요.')
        st.caption('20초마다 새로 확인해요. 지난 상태는 오늘의 기분이 아닐 수 있어요.')
    except PermissionError:
        st.warning('로그인이 만료됐어요. 화면을 새로고침해 주세요.')
    except psycopg.Error:
        st.warning('가족 상태를 불러오지 못했어요. 잠시 후 다시 시도해 주세요.')

def main_screen():
    me=identity()
    head,exitcol=st.columns([4,1])
    head.subheader('🏡 '+me['room_name'])
    if exitcol.button('나가기',use_container_width=True): logout(); st.rerun()
    st.caption(me['name']+'님, 지금 마음은 어떤가요?')
    own=next((r for r in rows() if r['id']==me['id']),None)
    if 'mood' not in st.session_state: st.session_state.mood=own['state'] if own and own['state'] else 'green'
    cols=st.columns(3)
    for col,(key,(emoji,label,_,_)) in zip(cols,STATES.items()):
        if col.button(emoji+' '+label,key='pick_'+key,type='primary' if st.session_state.mood==key else 'secondary',use_container_width=True):
            st.session_state.mood=key;st.rerun()
    st.caption(STATES[st.session_state.mood][2])
    if st.session_state.mood=='red': st.caption('쉬고 싶은 마음도 존중해요. 가족에게 답장을 재촉하지 않도록 알려드려요.')
    with st.form('editor'):
        msg=st.text_input('하고 싶은 말 · 선택',value=(own['message'] or '') if own else '',max_chars=100,placeholder='오늘 힘든 일이 있었어요',key='message')
        with st.expander('원하는 배려 · 선택'):
            care_value=own['care'] if own and own['care'] in CARES else CARES[0]
            care=st.selectbox('이렇게 배려해 주세요',CARES,index=CARES.index(care_value),key='care')
            st.caption('예: 같이 이야기하고 싶어요 / 조금 쉬었다가 이야기할게요')
        sent=st.form_submit_button('마음 수정하기' if own and own['state'] else '내 마음 등록하기',type='primary',use_container_width=True)
    if sent:
        save(st.session_state.mood,msg.strip(),care)
        st.toast('가족에게 마음을 전했어요 🌿');st.rerun()
    if own and own['state']:
        with st.expander('내 상태 삭제'):
            confirm=st.checkbox('등록한 상태와 메시지를 삭제할게요')
            if st.button('내 상태 삭제하기',disabled=not confirm,use_container_width=True):
                delete()
                for key in ('message','care','mood'):st.session_state.pop(key,None)
                st.rerun()
    family_cards()
    with st.expander('방 코드 · 접속 QR'):
        st.caption('가족에게만 전달하세요. 방 코드를 아는 사람도 방 비밀번호가 필요해요.')
        st.code(me['code'],language=None)
        st.caption('가족은 로그인 화면의 ‘방 코드로 입장’에서 이 코드를 입력하면 돼요. 방 비밀번호는 별도로 전달하세요.')
        url=str(st.secrets.get('APP_URL','')).strip()
        if url.startswith('https://'):
            image=qrcode.make(url); buf=io.BytesIO();image.save(buf,format='PNG')
            st.image(buf.getvalue(),width=180)
            st.download_button('접속 QR 저장',buf.getvalue(),'family-qr.png','image/png',use_container_width=True)
        else: st.caption('관리자가 Secrets에 APP_URL을 설정하면 접속용 QR이 표시돼요.')
        st.caption('접속 QR에는 주소만 들어가며 비밀번호·PIN·마음 정보는 포함되지 않아요. PIN과 방 비밀번호는 복구 기능이 없으니 안전하게 기억해 주세요.')

def run():
    global DB_URL
    if not st.session_state.get('started'):
        image=base64.b64encode(SVG.encode()).decode()
        st.markdown(f'<div style="height:16vh"></div><div style="text-align:center"><img alt="집과 신호등 로고" src="data:image/svg+xml;base64,{image}" width="220"></div>',unsafe_allow_html=True)
        _,center,_=st.columns([1,2,1])
        center.button('시작',on_click=start,type='primary',use_container_width=True)
        return
    # Render the login UI even before database configuration; connect only on demand.
    try: DB_URL=str(st.secrets.get('DATABASE_URL','')).strip()
    except Exception: DB_URL=''
    if st.session_state.get('actor') and time.time()<st.session_state.get('until',0):
        main_screen();return
    if st.session_state.get('actor'): logout()
    # A failed configuration must not replace the login screen on the first click.
    login_screen()

# Initialize only when an action requires the database. The wrappers keep startup
# screens independent of Secrets and database availability.
_raw_db=db
_initialized=False
_initializing=False
def db():
    global _initialized,_initializing
    if not DB_URL.startswith(('postgresql://','postgres://')):
        raise ValueError('공유 저장소 설정이 필요해요. Streamlit 앱 Settings → Secrets에 DATABASE_URL을 넣어 주세요.')
    if not _initialized and not _initializing:
        _initializing=True
        try:
            init_db(hashlib.sha256(DB_URL.encode()).hexdigest())
            _initialized=True
        finally: _initializing=False
    return _raw_db()

try:
    run()
except ValueError as error:
    st.warning(str(error))
except PermissionError:
    logout();st.rerun()
except psycopg.Error:
    st.error('공유 저장소에 연결하지 못했어요. 잠시 후 다시 시도해 주세요. 관리자는 Neon 연결 주소와 테이블 생성 권한을 확인해 주세요.')
    if st.button('다시 시도',use_container_width=True):st.rerun()
