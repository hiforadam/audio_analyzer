import streamlit as st  # type: ignore
import soundfile as sf  # type: ignore
import numpy as np  # type: ignore
from datetime import datetime
import os
import re
import json

# ========== HELPERS ==========

def is_valid_email(email):
    pattern = r"^[\w\.-]+@[\w\.-]+\.\w+$"
    return re.match(pattern, email)

def save_user_local(email, info_dict):
    """שומר כל דאטה שנכנס לרשימת JSON מרכזית"""
    os.makedirs('user_data', exist_ok=True)
    file_path = "user_data/all_feedbacks.json"
    record = {
        "email": email,
        **info_dict,
        "timestamp": datetime.now().isoformat()
    }
    try:
        # טען את הדאטה הקיים (אם קיים)
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if not isinstance(data, list):
                    data = []
        else:
            data = []
        # הוסף את הרשומה החדשה
        data.append(record)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[DEBUG] Saved user data locally: {file_path}")
    except Exception as e:
        print(f"[ERROR] Could not save data: {e}")

def professional_tips(lufs, peak, crest, centroid, dominant_freq):
    tips = []
    main_tip = ""
    explanation = []

    if lufs > -11.5:
        tips.append(f"High loudness ({lufs:.2f} LUFS). It's recommended to reduce master volume/limiter to about -13~-14 LUFS to avoid distortion and automatic volume reduction on streaming platforms.")
        main_tip = "Loudness is too high – possible distortion/volume reduction."
        explanation.append("LUFS represents perceived loudness. Too high values will cause platforms like Spotify to reduce volume automatically, possibly causing distortion.")
    elif lufs < -15.5:
        tips.append(f"Low loudness ({lufs:.2f} LUFS). Consider raising volume or remastering to make the mix stand out.")
        main_tip = "Loudness is low – mix won't stand out compared to others."
        explanation.append("Low LUFS means the track sounds weak compared to others, especially in playlists.")
    else:
        tips.append(f"Average loudness is normal ({lufs:.2f} LUFS) – great!")
        explanation.append("Loudness is within normal range, but make sure other parameters are good too.")

    if peak > 0.98:
        tips.append(f"High peak value ({peak:.2f}). Recommended to lower to -0.5dBFS to avoid clipping or distortion.")
        if not main_tip:
            main_tip = "High peak – risk of clipping/distortion."
        explanation.append("High peak values mean audio signal touches upper limit, risking digital distortion.")
    elif peak < 0.7:
        tips.append(f"Low peak value ({peak:.2f}). Consider increasing gain to utilize dynamic range.")
        explanation.append("Low peak means mix isn't utilizing full dynamic range – master gain can be raised.")
    else:
        tips.append(f"Peak level is within a healthy range ({peak:.2f}).")

    if crest < 3:
        tips.append(f"Low Crest Factor ({crest:.2f}). Mix is too compressed – try reducing compression/limiter.")
        if not main_tip:
            main_tip = "Mix is over-compressed – loss of dynamics."
        explanation.append("Low Crest Factor indicates small difference between peaks and noise floor, meaning heavy compression.")
    elif crest > 6:
        tips.append(f"High Crest Factor ({crest:.2f}). Mix is very dynamic – might need compression.")
        explanation.append("High Crest Factor is typical for classical or soundtrack music; if not, mix might be too soft.")
    else:
        tips.append(f"Crest Factor is within normal range ({crest:.2f}).")

    if dominant_freq < 80:
        tips.append(f"Bass dominant frequency ({dominant_freq:.1f}Hz). Check for muddy build-up in 20–80Hz range.")
        explanation.append("Very low dominant frequency suggests bass is overpowering. Use headphones and EQ to check.")
    elif dominant_freq > 3000:
        tips.append(f"High frequency dominant ({dominant_freq:.1f}Hz). Possibly too much high-end boost.")
        explanation.append("High dominant frequency can cause harshness and listener fatigue. Balance highs and lows.")
    else:
        tips.append(f"Dominant frequency is within a healthy range ({dominant_freq:.1f}Hz).")

    if centroid < 1400:
        tips.append(f"Low spectral centroid ({centroid:.1f}Hz). Consider adding brightness (EQ around 2kHz-7kHz).")
        explanation.append("Low centroid results in a 'dark' mix; sometimes a bit of brightness is desired for modern sound.")
    elif centroid > 4800:
        tips.append(f"High spectral centroid ({centroid:.1f}Hz). High-end is dominant – consider EQ adjustments.")
        explanation.append("Too high centroid makes mix sound 'sharp' or 'thin', which can be unpleasant for long listening.")
    else:
        tips.append(f"Spectral centroid is balanced ({centroid:.1f}Hz).")

    if not main_tip:
        main_tip = "Your mix is balanced and excellent! Keep it up."

    return main_tip, tips, explanation

# ========== UI & LOGIC ==========

st.set_page_config(page_title="Smart Mixing Tips", layout="centered")

if 'email_ok' not in st.session_state:
    st.session_state['email_ok'] = False

if not st.session_state['email_ok']:
    st.markdown("""
    <div style='
        text-align:left;
        direction:ltr;
        background: #fff;
        color:#181818;
        font-weight:900;
        font-size:2.05em;
        border-radius:15px;
        padding: 20px 0 12px 8px;
        box-shadow: 0 1px 12px #e7e5e4;
        margin-bottom:20px;'
    >
    🎧 Smart Mixing Tips – Automatic Audio File Feedback
    </div>
    """, unsafe_allow_html=True)
    st.write("Before proceeding – please enter your email address to gain access:")
    email = st.text_input("Enter your email address (required):")
    if st.button("Continue"):
        if is_valid_email(email):
            st.session_state['email_ok'] = True
            st.session_state['user_email'] = email
            save_user_local(email, {'timestamp': datetime.now().isoformat()})
            st.success("Email received – you may continue!")
        else:
            st.error("Please enter a valid email address.")
    if not st.session_state['email_ok']:
        st.stop()

uploaded_file = st.file_uploader("Upload audio file (WAV/MP3)", type=["wav", "mp3"])

if uploaded_file:
    try:
        st.info("🔎 Analysis may take a few seconds. Please wait...")
        os.makedirs('uploads', exist_ok=True)
        filename = f"uploads/{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uploaded_file.name}"
        with open(filename, "wb") as f:
            f.write(uploaded_file.read())
        data, samplerate = sf.read(filename)
        if data.ndim > 1:
            data = np.mean(data, axis=1)
        duration = len(data) / samplerate
        rms = np.sqrt(np.mean(data**2))
        peak = np.max(np.abs(data))
        crest_factor = peak / (rms + 1e-9)
        lufs = 20 * np.log10(rms + 1e-9)
        spectrum = np.abs(np.fft.rfft(data))
        freqs = np.fft.rfftfreq(len(data), 1/samplerate)
        centroid = np.sum(freqs * spectrum) / np.sum(spectrum)
        dominant_freq = freqs[np.argmax(spectrum)]

        st.markdown(
            f"<div dir='ltr' style='text-align:left; background:#f4f4f5; color:#232323; padding:10px; border-radius:12px; margin-bottom:16px; font-size:1.01em'>"
            f"✅ File loaded successfully: <b>{uploaded_file.name}</b> | Size: <b>{uploaded_file.size/1024/1024:.1f}MB</b> | Duration: <b>{duration:.1f} seconds</b>"
            f"</div>",
            unsafe_allow_html=True
        )

        main_tip, tips, explanation = professional_tips(lufs, peak, crest_factor, centroid, dominant_freq)

        st.markdown(
            f"<div dir='ltr' style='text-align:left; background:#fefce8; color:#bb8504; padding:17px; border-radius:16px; margin-top:13px; font-size:1.18em; font-weight:bold; border:2px solid #fde68a;'>"
            f"{main_tip}"
            f"</div>",
            unsafe_allow_html=True
        )

        st.markdown("<div dir='ltr' style='text-align:left; font-size:1.13em; margin-top:13px; color:#111'><b>Professional Recommendations for this Mix:</b></div>", unsafe_allow_html=True)
        tips_html = "<div dir='ltr' style='text-align:left; font-size: 1.09em; background:#fff; color:#232323; padding:11px 8px 2px 0; border-radius:9px; margin-bottom:13px;'>"
        for tip in tips:
            tips_html += f"• {tip}<br>"
        tips_html += "</div>"
        st.markdown(tips_html, unsafe_allow_html=True)

        st.markdown("<div dir='ltr' style='text-align:left; font-size:1.05em; margin-top:8px; color:#8a593a; background:#f6e9d7; border-radius:7px; padding:7px 12px 7px 0;'><b>Detailed explanation for each parameter:</b><br>"
            + "<br>".join(explanation) + "</div>", unsafe_allow_html=True)

        with st.expander("📋 Summary for copy/share:"):
            summary = f"""<div dir='ltr' style='text-align:left; font-family:inherit; color:#222; background:#f8fafc; padding:12px; border-radius:10px'>
<b>Auto Summary:</b><br>
Loudness (LUFS): {lufs:.2f}<br>
Peak: {peak:.2f}<br>
Crest Factor: {crest_factor:.2f}<br>
Dominant Frequency: {dominant_freq:.0f}Hz<br>
Centroid: {centroid:.0f}Hz<br>
<br>
<b>Main Tip:</b><br>
{main_tip}<br>
<br>
<b>Additional Recommendations:</b><br>
- {'<br>- '.join(tips)}
</div>
"""
            st.markdown(summary, unsafe_allow_html=True)

        # Save user info immediately (even without feedback)
        user_info = {
            'filename': filename,
            'duration': duration,
            'lufs': lufs,
            'peak': peak,
            'crest_factor': crest_factor,
            'centroid': centroid,
            'dominant_freq': dominant_freq,
            'main_tip': main_tip,
            'tips': "; ".join(tips),
            'timestamp': datetime.now().isoformat()
        }
        save_user_local(st.session_state['user_email'], user_info)

        st.markdown("<div dir='ltr' style='text-align:left; color:#166534; font-size:1.06em; margin-bottom:7px; margin-top:20px;'>Your feedback will improve the system!</div>", unsafe_allow_html=True)

        feedback_purpose = st.selectbox(
            "Why did you create/upload this file?",
            ["Just checking", "Submit to client", "Streaming upload", "Demo phase", "Professional consultation", "Contest/Prize", "Other (please specify)"]
        )
        feedback_purpose_free = ""
        if feedback_purpose == "Other (please specify)":
            feedback_purpose_free = st.text_input("Free text detail:")

        feedback_hardest = st.multiselect(
            "What bothers you most about your mix? (select multiple)",
            ["Bass", "Highs", "Dynamics", "Overall loudness", "Unclear sound", "No depth", "No live feeling", "Distortion/Clipping", "Other (please specify)"]
        )
        feedback_hardest_free = ""
        if "Other (please specify)" in feedback_hardest:
            feedback_hardest_free = st.text_input("Free text for problem/shortcoming:")

        self_rating = st.slider("Rate your satisfaction with the mix (1=Not satisfied at all, 10=Completely satisfied):", 1, 10, 7)
        reference = st.text_input("Is there a reference sound you want to achieve? (link/song name/youtube)")
        q1 = st.radio("Were the recommendations relevant?", ["Yes", "No", "Partially"])
        q2 = st.text_area("What would you like to improve in this analysis?", height=100)
        q3 = st.text_area("Any comments/requests – help us improve!", height=100)

        if st.button("Submit feedback"):
            user_info.update({
                'feedback_purpose': feedback_purpose,
                'feedback_purpose_free': feedback_purpose_free,
                'self_rating': self_rating,
                'feedback_hardest': '/'.join(feedback_hardest),
                'feedback_hardest_free': feedback_hardest_free,
                'reference': reference,
                'q1': q1,
                'q2': q2,
                'q3': q3,
                'timestamp': datetime.now().isoformat()
            })
            save_user_local(st.session_state['user_email'], user_info)
            st.success("Thank you for your feedback! Want to analyze another file? Refresh the page or upload a new file.")

    except Exception as e:
        st.error(f"⚠️ Error: Unsupported or corrupted file ({e})")
else:
    st.markdown("<div style='direction:ltr; text-align:left; color:#232323; margin-top:14px; background:#fff; padding:8px; border-radius:8px'>Upload WAV or MP3 file only for analysis.</div>", unsafe_allow_html=True)