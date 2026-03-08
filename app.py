import streamlit as st
import requests
from google import genai # ⬅️ 새로운 라이브러리 임포트 방식으로 변경
from PIL import Image
import io
import json
import datetime

st.set_page_config(page_title="Verkada & Gemini 감시 시스템", layout="wide")

# --- 1. GUI 구성 (사이드바에 설정값 입력란 배치) ---
st.sidebar.header("⚙️ 주요 구성 정보 입력")
verkada_api_key = st.sidebar.text_input("Verkada API Key", type="password")
gemini_api_key = st.sidebar.text_input("Gemini API Key", type="password")
verkada_org_id = st.sidebar.text_input("Verkada Org ID")
camera_id = st.sidebar.text_input("Verkada Camera ID")
event_type_uid = st.sidebar.text_input("Helix Event Type UID", help="Helix에 등록된 이벤트 스키마의 고유 ID입니다.")

st.sidebar.markdown("---")
st.sidebar.subheader("📸 비교할 시간 설정")
date_1 = st.sidebar.date_input("기준 날짜 (Time 1)")
time_1 = st.sidebar.time_input("기준 시간 (Time 1)")
date_2 = st.sidebar.date_input("비교 날짜 (Time 2)")
time_2 = st.sidebar.time_input("비교 시간 (Time 2)")

dt1 = datetime.datetime.combine(date_1, time_1)
dt2 = datetime.datetime.combine(date_2, time_2)
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

def get_verkada_thumbnail(token, cam_id, time_ms):
    url = "https://api.verkada.com/cameras/v1/footage/thumbnails"
    headers = {
        "x-verkada-auth": token, 
        "accept": "image/jpeg"
    }
    params = {
        "camera_id": cam_id,
        "time_ms": time_ms
    }
    
    response = requests.get(url, headers=headers, params=params)
    if response.status_code == 200:
        return Image.open(io.BytesIO(response.content))
    elif response.status_code == 303:
        img_url = response.json().get("url")
        img_res = requests.get(img_url)
        return Image.open(io.BytesIO(img_res.content))
    else:
        st.error(f"썸네일 로드 실패 ({time_ms}): {response.text}")
        return None

def compare_with_gemini(api_key, img1, img2):
    """3. Gemini에 두 사진을 보내 변경점(yes/no)과 설명을 JSON으로 받습니다."""
    # ⬅️ 최신 genai 클라이언트 초기화 및 모델명(2.5-flash) 변경
    client = genai.Client(api_key=api_key)
    
    prompt = """
    Look at these two images taken from the same camera at different times.
    Is there any difference between the two photos? Specifically, check for changes in the arrangement of objects or if any items are missing.
    Respond ONLY with a strictly formatted JSON object containing two keys:
    1. "changed": string value, strictly "yes" or "no".
    2. "description": a brief explanation of what changed or what the current state is.
    """
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash', # 최신 모델 적용
            contents=[prompt, img1, img2]
        )
        result_text = response.text.strip().replace('```json', '').replace('```', '')
        return json.loads(result_text)
    except Exception as e:
        st.error(f"Gemini 분석 오류: {e}")
        return None

def send_to_verkada_helix(token, cam_id, event_uid, time_ms, changed_status, description, org_id):
    url = "https://api.verkada.com/cameras/v1/video_tagging/event"
    headers = {
        "x-verkada-auth": token,
        "content-type": "application/json",
        "accept": "application/json"
    }
    payload = {
        "camera_id": cam_id,
        "event_type_uid": event_uid,
        "time_ms": time_ms,
        "attributes": {
            "changed": changed_status,
            "description": description,
            "org_id": org_id 
        }
    }
    
    response = requests.post(url, headers=headers, json=payload)
    return response


# --- 3. 메인 실행 로직 ---

st.title("👀 Verkada & Gemini AI 자동 감시 시스템")
st.write("지정된 두 시간의 카메라 화면을 비교하고, 물건 배치가 달라지거나 없어진 항목이 있으면 Helix에 기록합니다.")

if st.button("🚀 사진 비교 및 Helix 전송 실행", type="primary"):
    if not all([verkada_api_key, gemini_api_key, camera_id, event_type_uid]):
        st.warning("사이드바에서 API Key, Camera ID, Event Type UID를 모두 입력해 주세요!")
    else:
        with st.spinner("Verkada API 토큰을 발급받는 중..."):
            v_token = get_verkada_token(verkada_api_key)
            
        if v_token:
            with st.spinner("카메라 썸네일을 다운로드하는 중..."):
                img1 = get_verkada_thumbnail(v_token, camera_id, time_1_ms)
                img2 = get_verkada_thumbnail(v_token, camera_id, time_2_ms)
                
            if img1 and img2:
                col1, col2 = st.columns(2)
                with col1:
                    st.image(img1, caption=f"기준 시간: {dt1.strftime('%Y-%m-%d %H:%M:%S')}")
                with col2:
                    st.image(img2, caption=f"비교 시간: {dt2.strftime('%Y-%m-%d %H:%M:%S')}")
                    
                with st.spinner("Gemini AI가 두 사진을 정밀 비교하는 중..."):
                    gemini_result = compare_with_gemini(gemini_api_key, img1, img2)
                    
                if gemini_result:
                    changed = gemini_result.get("changed", "no")
                    desc = gemini_result.get("description", "설명 없음")
                    
                    st.subheader("🤖 Gemini 분석 결과")
                    st.markdown(f"**변경 사항 발생 여부:** `{changed.upper()}`")
                    st.info(f"**상세 설명:** {desc}")
                    
                    with st.spinner("Verkada Helix로 분석 결과를 전송하는 중..."):
                        helix_res = send_to_verkada_helix(
                            v_token, camera_id, event_type_uid, time_2_ms, changed, desc, verkada_org_id
                        )
                        
                    if helix_res.status_code in [200, 201, 202]:
                        st.success("✅ Verkada Helix에 성공적으로 이벤트가 기록되었습니다!")
                    else:
                        st.error(f"❌ Helix 전송 실패 ({helix_res.status_code}): {helix_res.text}")
