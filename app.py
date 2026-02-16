import streamlit as st
import os
import google.generativeai as genai
from dotenv import load_dotenv
import io
import numpy as np
import wave
import requests
from datetime import datetime

# 1. Page Config & Design
st.set_page_config(
    page_title="CSM17 Meeting Assistant",
    page_icon="🎙️",
    layout="centered"
)

# Custom CSS for polish
st.markdown("""
<style>
    .stButton>button {
        width: 100%;
        border-radius: 8px;
        height: 3rem;
    }
    .main-header {
        font-size: 2.5rem;
        font-weight: 700;
        color: #1E1E1E;
        text-align: center;
        margin-bottom: 2rem;
    }
    .content-box {
        background-color: #f0f2f6;
        padding: 20px;
        border-radius: 10px;
        border: 1px solid #e0e0e0;
        margin-bottom: 1rem;
        white-space: pre-wrap;
    }
</style>
""", unsafe_allow_html=True)

# Helper functions
def check_audio_volume(audio_bytes):
    try:
        with wave.open(io.BytesIO(audio_bytes), 'rb') as wf:
            frames = wf.readframes(wf.getnframes())
            if len(frames) == 0: return 0
            audio_data = np.frombuffer(frames, dtype=np.int16)
            if len(audio_data) == 0: return 0
            rms = np.sqrt(np.mean(audio_data**2))
            return rms
    except Exception as e:
        print(f"Error checking volume: {e}")
        return -1

def save_audio_file(audio_bytes):
    if not os.path.exists("recordings"):
        os.makedirs("recordings")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"recordings/meeting_{timestamp}.wav"
    with open(filename, "wb") as f:
        f.write(audio_bytes)
    return filename

def send_to_slack(token, channel, summary_data, attendants="", context=""):
    url = "https://slack.com/api/chat.postMessage"
    headers = {"Authorization": f"Bearer {token}"}
    
    if not channel.startswith("#") and not channel.startswith("C"):
        channel = f"#{channel}"

    # Prepare Message
    message = f"*🎙️ 씨에스엠17 회의 기록 완료 ({datetime.now().strftime('%Y-%m-%d %H:%M')})*\n\n"
    
    if attendants:
        message += f"*👥 참여자*: {attendants}\n"
    if context:
        message += f"*💡 회의 목적 및 배경*: {context}\n"
    
    message += "\n"
    
    if summary_data.get('three_line'):
        message += f"*✨ 3줄 요약*\n{summary_data['three_line']}\n\n"
    
    if summary_data.get('todo'):
        message += f"*⚡ 할 일 (To-Do)*\n{summary_data['todo']}\n\n"
        
    if summary_data.get('detailed'):
        message += f"*📌 상세 요약*\n{summary_data['detailed']}\n\n"
    
    payload = {
        "channel": channel,
        "text": message
    }
    
    response = requests.post(url, headers=headers, json=payload)
    return response.json()

# 2. Sidebar & API Setup
load_dotenv()
with st.sidebar:
    st.header("설정")
    
    # 1. Try to get from st.secrets (Streamlit Cloud)
    # 2. Fallback to os.getenv (.env local file)
    api_key = st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
    slack_token = st.secrets.get("SLACK_BOT_TOKEN") or os.getenv("SLACK_BOT_TOKEN")
    
    if not api_key:
        st.error("⚠️ API 키가 설정되지 않았습니다. (Secrets 또는 .env 확인 필요)")
        st.stop()
    
    try:
        genai.configure(api_key=api_key)
        st.success("✅ 시스템 준비 완료")
    except Exception as e:
        st.error(f"API 구성 오류: {e}")
    
    st.markdown("---")
    st.markdown("### ℹ️ 앱 정보")
    st.markdown("씨에스엠17 전용 회의 비서입니다.")
    st.markdown("*powered by **euna***")

# 3. Main Interface
st.markdown('<div class="main-header">씨에스엠17 회의 비서 🎙️</div>', unsafe_allow_html=True)

# 4. Audio Recording
st.subheader("🔴 단계 1: 회의 녹음하기")
st.info("아래 녹음기 버튼을 눌러 회의를 시작하세요. (최대 2시간 녹음 가능)")
audio_val = st.audio_input("여기를 눌러 녹음 시작/중단")

with st.expander("❓ 마이크가 작동하지 않나요?"):
    st.markdown("1. 주소창 왼쪽 **(i)** 또는 **자물쇠** 아이콘 클릭\n2. 마이크 **허용** 확인\n3. 윈도우 소리 설정에서 '스테레오 믹스'가 아닌 진짜 **마이크** 선택")

# 5. Processing Logic
if audio_val:
    audio_val.seek(0)
    audio_bytes = audio_val.read()
    rms_val = check_audio_volume(audio_bytes)
    
    if rms_val < 5:
        st.error(f"⚠️ 무음 감지 (음량: {rms_val:.2f})")
    elif rms_val < 15: # Lowered threshold
        st.warning(f"⚠️ 소리가 매우 작습니다 (음량: {rms_val:.2f})")
    else:
        st.success(f"✅ 녹음 완료! (음량: {rms_val:.0f})")

    if st.button("📝 회의록 생성 및 분석 시작", type="primary"):
        if rms_val < 5:
            st.error("무음 상태라 분석이 불가능합니다.")
        else:
            with st.spinner("파일 저장 및 AI 분석 중... 잠시만 기다려 주세요."):
                # Save File
                saved_path = save_audio_file(audio_bytes)
                abs_path = os.path.abspath(saved_path)
                st.session_state['saved_path'] = saved_path
                st.info(f"💾 오디오 파일이 자동 저장되었습니다:\n`{abs_path}`")
                
                # Analyze with Gemini
                try:
                    candidate_models = ["models/gemini-2.0-flash", "models/gemini-flash-latest"]
                    
                    full_result = None
                    last_error = None
                    
                    prompt = (
                        "당신은 전문 비서입니다. 제공된 오디오를 바탕으로 다음 세 가지 섹션을 한국어로 정확히 작성해주세요.\n\n"
                        "[3-Line Summary]: 회의의 핵심 내용을 딱 3줄로 요약해 주세요.\n"
                        "[To-do List]: 회의에서 결정된 할 일들을 리스트 형식으로 정리해 주세요.\n"
                        "[Detailed Summary]: 주요 주제와 결정 사항을 포함한 상세 요약을 작성해 주세요.\n\n"
                        "각 섹션은 대괄호 [] 로 시작하는 제목으로 명확히 구분해 주세요."
                    )

                    for model_name in candidate_models:
                        try:
                            model = genai.GenerativeModel(model_name)
                            response = model.generate_content([prompt, {"mime_type": "audio/wav", "data": audio_bytes}])
                            full_result = response.text
                            if full_result: break
                        except Exception as e:
                            last_error = e
                            continue
                    
                    if not full_result:
                        st.error(f"Analysis failed. Error: {last_error}")
                        st.stop()

                    # Section Parsing Logic
                    def extract_section(text, section_name):
                        import re
                        pattern = f"\\[{section_name}\\](.*?)(?=\\[|$)"
                        match = re.search(pattern, text, re.DOTALL)
                        return match.group(1).strip() if match else ""

                    st.session_state['res_three'] = extract_section(full_result, "3-Line Summary")
                    st.session_state['res_todo'] = extract_section(full_result, "To-do List")
                    st.session_state['res_detailed'] = extract_section(full_result, "Detailed Summary")
                    
                except Exception as e:
                    st.error(f"Analysis failed: {e}")

# Display Results
if 'res_detailed' in st.session_state:
    st.divider()
    st.subheader("🔵 단계 2: 회의 분석 결과 확인")
    
    t1, t2 = st.tabs(["✨ 요약 (Summary)", "⚡ 할 일 (To-Do)"])
    
    with t1:
        st.markdown("**[3줄 요약]**")
        st.info(st.session_state['res_three'])
        st.markdown("**[상세 요약]**")
        st.markdown(f'<div class="content-box">{st.session_state["res_detailed"]}</div>', unsafe_allow_html=True)
    
    with t2:
        st.markdown(f'<div class="content-box">{st.session_state["res_todo"]}</div>', unsafe_allow_html=True)
    
    # Enhanced Slack Flow
    st.divider()
    st.subheader("🟢 단계 3: 슬랙으로 전송하기")
    
    target_channels = ["회의록", "김은아1", "김은아2"]
    selected_channel = st.selectbox("전송할 채널을 선택하세요", options=target_channels)
    
    # New Input Fields
    attendants = st.text_input("참여자 명단", placeholder="예: 홍길동, 김철수, 이영희")
    meeting_context = st.text_area("회의 목적 및 배경", placeholder="이 회의의 목적이나 특이사항을 입력하세요")
    
    if st.button("슬랙으로 회의록 전송", type="primary"):
        if not slack_token:
            st.error(".env 파일에 슬랙 토큰이 없습니다!")
        else:
            with st.spinner(f"#{selected_channel} 채널로 전송 중..."):
                summary_data = {
                    'three_line': st.session_state['res_three'],
                    'todo': st.session_state['res_todo'],
                    'detailed': st.session_state['res_detailed']
                }
                res = send_to_slack(
                    slack_token, 
                    selected_channel, 
                    summary_data,
                    attendants=attendants,
                    context=meeting_context
                )
                if res.get("ok"):
                    st.success(f"✅ #{selected_channel} 채널로 회의록이 성공적으로 전송되었습니다!")
                else:
                    st.error(f"❌ 슬랙 전송 실패: {res.get('error')}")
                    if "channel_not_found" in str(res):
                        st.info("💡 봇이 해당 채널에 초대되어 있는지 확인하세요.")
