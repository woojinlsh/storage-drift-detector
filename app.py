import streamlit as st
import requests
from google import genai
from PIL import Image
import io
import json
import datetime
import zoneinfo

st.set_page_config(page_title="Verkada & Gemini 자동 감시 시스템", layout="wide")

# --- 1. GUI 구성 (사이드바에 설정값 입력란 배치) ---
st.sidebar.header("⚙️ 주요 구성 정보 입력")
verkada_api_key = st.sidebar.text_input("Verkada API Key", type="password")
gemini_api_key = st.sidebar.text_input("Gemini API Key", type="password")
verkada_org_id = st.sidebar.text_input("Verkada Org ID", help="예: 607ef9ff-...") 
camera_id = st.sidebar.text_input("Verkada Camera ID")
event_type_uid = st.sidebar.text_input("Helix Event Type UID")

st.sidebar.markdown("---")
st.sidebar.subheader("📸 비교할 시간 설정")
tz_string = st.sidebar.selectbox("타임존 (Timezone)", ["Asia/Seoul", "UTC", "America/New_York", "America/Los_Angeles"])
local_tz = zoneinfo.ZoneInfo(tz_string)

date_1 = st.sidebar.date_input("기준 날짜 (Time 1)")
time_1 = st.sidebar.time_input("기준 시간 (Time 1)")
date_2 = st.sidebar.date_input("비교 날짜 (Time 2)")
time_2 = st.sidebar.time_input("비교 시간 (Time 2)")

dt1 = datetime.datetime.combine(date_1, time_1).replace(tzinfo=local_tz)
dt2 = datetime.datetime.combine(date_2, time_2).replace(tzinfo=local_tz)

# 썸네일용(초 단위)과 Helix용(밀리초 단위) 시간 분리
time_1_sec = int(dt1.timestamp())
time_2_sec = int(dt2.timestamp())

time_1_ms = int(dt1.timestamp() * 1000)
time_2_ms = int(dt2.timestamp() * 1000)


# --- 2. Verkada API & Gemini 연동 함수 ---

def get_verkada_token(api_key):
    url = "https://api.verkada.com/token"
    headers = {
        "x-api-key": api_key,
        "accept": "application/json"
    }
    response = requests.post(url, headers=headers)
    if response.status_code == 200:
        return response.json().get("token")
    else:
        st.error(f"토큰 발급 실패: {response.text}")
        return None

def get_verkada_thumbnail(token, cam_id, time_sec):
    url = "https://api.verkada.com/cameras/v1/footage/thumbnails"
    headers = {
        "x-verkada-auth": token, 
        "accept": "image/jpeg"
    }
    params = {
        "camera_id": cam_id,
        "timestamp": time_sec,
        "resolution": "hi-res" 
    }
    
    response = requests.get(url, headers=headers, params=params)
    if response.status_code == 200:
        return Image.open(io.BytesIO(response.content))
    elif response.status_code == 303:
        img_url = response.json().get("url")
        img_res = requests.get(img_url)
        return Image.open(io.BytesIO(img_res.content))
    else:
        st.error(f"썸네일 로드 실패 ({time_sec}): {response.text}")
        return None

def compare_with_gemini(api_key, img1, img2):
    client = genai.Client(api_key=api_key)
    
    # 💡 수정 1: 프롬프트에서 글자 수와 줄바꿈 제한을 강력하게 지시합니다.
    prompt = """
    제공된 두 장의 사진은 같은 카메라에서 다른 시간에 촬영된 것입니다.
    두 사진을 비교하여 차이점이 있는지 분석해 주세요. 
    
    응답은 반드시 아래 두 개의 키를 포함하는 엄격한 JSON 형식으로만 작성해야 합니다:
    1. "changed": 차이가 있다면 "yes", 없다면 "no" (반드시 영어 소문자).
    2. "description": 무엇이 변경되었는지 **반드시 한국어로, 50자 이내의 아주 짧고 간결한 단일 문장으로** 작성해 주세요. 절대 줄바꿈을 포함하지 마세요. (예: "책상 위 흰색 머그컵이 사라졌습니다.")
    """
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash', 
            contents=[prompt, img1, img2]
        )
        result_text = response.text.strip().replace('```json', '').replace('```', '')
        return json.loads(result_text)
    except Exception as e:
        st.error(f"Gemini 분석 오류: {e}")
        return None

def send_to_verkada_helix(token, cam_id, event_uid, time_ms, changed_status, description, org_id):
    url = "https://api.verkada.com/cameras/v1/video_tagging/event"
    
    params = {"org_id": org_id}
    headers = {
        "x-verkada-auth": token,
        "content-type": "application/json"
    }
    payload = {
        "attributes": {
            "changed": changed_status,
            "description": description
        },
        "event_type_uid": event_uid,
        "camera_id": cam_id,
        "time_ms": time_ms 
    }
    
    response = requests.post(url, headers=headers, params=params, json=payload)
    return response


# --- 3. 메인 실행 로직 ---

st.title("👀 Verkada & Gemini AI 자동 감시 시스템")
st.write("지정된 두 시간의 카메라 화면을 비교하고, 물건 배치가 달라지거나 없어진 항목이 있으면 Helix에 기록합니다.")

if st.button("🚀 사진 비교 및 Helix 전송 실행", type="primary"):
    if not all([verkada_api_key, gemini_api_key, verkada_org_id, camera_id, event_type_uid]):
        st.warning("사이드바에서 모든 설정값(API Key, Org ID, Camera ID, Event Type UID)을 입력해 주세요!")
    else:
        with st.spinner("Verkada API 토큰을 발급받는 중..."):
            v_token = get_verkada_token(verkada_api_key)
            
        if v_token:
            with st.spinner("카메라 썸네일을 다운로드하는 중..."):
                img1 = get_verkada_thumbnail(v_token, camera_id, time_1_sec)
                img2 = get_verkada_thumbnail(v_token, camera_id, time_2_sec)
                
            if img1 and img2:
                col1, col2 = st.columns(2)
                with col1:
                    st.image(img1, caption=f"기준 시간: {dt1.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                with col2:
                    st.image(img2, caption=f"비교 시간: {dt2.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                    
                with st.spinner("Gemini AI가 두 사진을 정밀 비교하는 중..."):
                    gemini_result = compare_with_gemini(gemini_api_key, img1, img2)
                    
                if gemini_result:
                    changed = gemini_result.get("changed", "no")
                    desc = gemini_result.get("description", "설명 없음")
                    
                    # 💡 수정 2: 파이썬에서 보내기 직전에 안전하게 글자 수를 자르고 줄바꿈을 없앱니다.
                    desc = desc.replace('\n', ' ').strip()
                    if len(desc) > 80:
                        desc = desc[:77] + "..."
                    
                    st.subheader("🤖 Gemini 분석 결과")
                    st.markdown(f"**변경 사항 발생 여부:** `{changed.upper()}`")
                    st.info(f"**상세 설명(안전 전송용):** {desc}")
                    
                    with st.spinner("Verkada Helix로 분석 결과를 전송하는 중..."):
                        helix_res = send_to_verkada_helix(
                            v_token, camera_id, event_type_uid, time_2_ms, changed, desc, verkada_org_id
                        )
                        
                    if helix_res.status_code in [200, 201, 202]:
                        st.success("✅ Verkada Helix 이벤트가 성공적으로 생성되었습니다!")
                        st.caption(f"기록된 시간(Time_ms): {time_2_ms}")
                    else:
                        st.error(f"❌ Helix 전송 실패 ({helix_res.status_code})")
                        st.code(helix_res.text)
