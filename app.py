import streamlit as st  # type: ignore
import soundfile as sf  # type: ignore
import numpy as np  # type: ignore
from datetime import datetime
import os
import re
import hashlib
from pathlib import Path
import uuid
from supabase import create_client, Client  # type: ignore

# ========== Supabase ==========
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
TABLE_NAME = "feedbacks"
BUCKET_NAME = "audio-uploads"

APP_ROOT = Path(__file__).parent.resolve()
UPLOADS_DIR = APP_ROOT / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

# ======= HELPERS & ERROR HANDLING =========

def clean_record_for_supabase(record: dict) -> dict:
    # Supabase לא אוהב None – ננקה את כל המפתחות
    for k, v in list(record.items()):
        if v is None:
            record[k] = ""
        elif not isinstance(v, (str, int, float)):
            record[k] = str(v)
    return record

def safe_supabase(func):
    """Decorator to catch and report Supabase errors."""
    def wrapper(*args, **kwargs):
        try:
            res = func(*args, **kwargs)
            if hasattr(res, 'error') and res.error:
                st.error(f"Database error: {res.error.message if hasattr(res.error, 'message') else res.error}")
                return None
            return res
        except Exception as e:
            st.error(f"Supabase error: {e}")
            return None
    return wrapper

def is_valid_email(email: str) -> bool:
    pattern = r"^[\w\.-]+@[\w\.-]+\.\w+$"
    return re.match(pattern, email) is not None

def safe_filename(s: str) -> str:
    s = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', s)
    return s[:64]

def compute_file_hash(file_path: Path) -> str:
    h = hashlib.sha1()
    with open(file_path, 'rb') as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()[:10]

@safe_supabase
def find_record(email: str, file_hash: str):
    res = supabase.table(TABLE_NAME).select("*").eq("email", email).eq("file_hash", file_hash).execute()
    if res and res.data and len(res.data) > 0:
        return res.data[0]
    return None

@safe_supabase
def get_user_feedbacks(email: str):
    res = supabase.table(TABLE_NAME).select("*").eq("email", email).order("created_at", desc=True).execute()
    if res and res.data:
        return res.data
    return []

@safe_supabase
def get_next_project_number(email: str) -> int:
    res = supabase.table(TABLE_NAME).select("filename").eq("email", email).execute()
    max_n = 0
    for rec in (res.data or []):
        # תיקון NoneType:
        fname = rec.get("filename") or ""
        m = re.search(r'__project_(\d+)', fname)
        if m:
            try:
                n = int(m.group(1))
                if n > max_n:
                    max_n = n
            except ValueError:
                continue
    return max_n + 1

def build_project_filename(email: str, project_num: int, ext: str) -> Path:
    email_part = safe_filename(email.split("@")[0]) if email else "anon"
    unique_id = uuid.uuid4().hex[:8]
    return UPLOADS_DIR / f"{email_part}__project_{project_num}_{unique_id}{ext}"

@safe_supabase
def save_or_update_record(email: str, record: dict) -> None:
    record = clean_record_for_supabase(record)  # נקיון לפני כל שמירה!
    fh = record.get("file_hash")
    now_iso = datetime.now().isoformat()
    exists = find_record(email, fh) if fh else None
    if exists:
        record["updated_at"] = now_iso
        supabase.table(TABLE_NAME).update(record).eq("email", email).eq("file_hash", fh).execute()
    else:
        record.setdefault("email", email)
        record["created_at"] = now_iso
        record["updated_at"] = now_iso
        supabase.table(TABLE_NAME).insert(record).execute()

def _read_audio_to_mono(path: Path):
    data_arr, samplerate = sf.read(str(path))
    if data_arr.ndim > 1:
        data_arr = np.mean(data_arr, axis=1)
    if data_arr.size == 0:
        raise ValueError("Empty audio data.")
    return data_arr.astype(np.float64, copy=False), int(samplerate)

# --- העלאת קובץ ל-Supabase Storage והחזרת URL ---
def upload_to_supabase_storage(local_path: Path, remote_path: str) -> str:
    # תיקון: storage הוא מאפיין, לא פונקציה; אין פרמטר upsert ל-upload
    with open(local_path, "rb") as f:
        supabase.storage.from_(BUCKET_NAME).upload(path=remote_path, file=f)
    url_res = supabase.storage.from_(BUCKET_NAME).get_public_url(remote_path)
    # החזרת מחרוזת URL
    if isinstance(url_res, dict) and "publicUrl" in url_res:
        return url_res["publicUrl"]
    elif isinstance(url_res, str):
        return url_res
    return ""

# ====== TIPS FUNCTION (כמו קודם) ======
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

# ====== UI & LOGIC ======
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
            save_or_update_record(email, clean_record_for_supabase({"email": email}))
            st.success("Email received – you may continue!")
        else:
            st.error("Please enter a valid email address.")
    if not st.session_state['email_ok']:
        st.stop()

email = st.session_state.get('user_email', 'anon')
uploaded_file = st.file_uploader("Upload audio file (WAV/MP3)", type=["wav", "mp3"])
genre = st.text_input("Genre (optional, e.g., Pop, Rock, Trap, Techno, etc.)")
project_stage = st.selectbox("Project Stage:", [
    "Demo", "Mix", "Master", "Reference Check", "Final", "Other"
])

# הצג היסטוריה של כל הפרויקטים/פידבקים (כולל לינק קובץ)

if uploaded_file:
    try:
        st.info("🔎 Analysis may take a few seconds. Please wait...")

        ext = Path(uploaded_file.name).suffix.lower()
        tmp = UPLOADS_DIR / f"__tmp_{uuid.uuid4().hex[:8]}{ext}"
        with open(tmp, "wb") as f:
            f.write(uploaded_file.getbuffer())

        file_hash = compute_file_hash(tmp)
        idx_rec = find_record(email, file_hash)

        n = get_next_project_number(email)
        safe_user = safe_filename(email.split("@")[0]) if email else "anon"
        unique_id = uuid.uuid4().hex[:8]
        remote_file = f"{safe_user}__project_{n}_{unique_id}{ext}"

        # העלאה ל-storage (תיקון: בלי upsert ובלי קריאה כ-פונקציה)
        file_url = upload_to_supabase_storage(tmp, remote_file)

        # עיבוד אודיו
        data_arr, samplerate = _read_audio_to_mono(tmp)
        duration = len(data_arr) / samplerate
        eps = 1e-12
        rms = float(np.sqrt(np.mean(data_arr**2)))
        peak = float(np.max(np.abs(data_arr))) if data_arr.size > 0 else 0.0
        crest_factor = float(peak / (rms + eps))
        lufs = float(20 * np.log10(rms + eps))
        spectrum = np.abs(np.fft.rfft(data_arr))
        freqs = np.fft.rfftfreq(len(data_arr), 1 / samplerate)
        denom = float(np.sum(spectrum)) + eps
        centroid = float(np.sum(freqs * spectrum) / denom)
        dominant_freq = float(freqs[np.argmax(spectrum)]) if spectrum.size > 0 else 0.0

        main_tip, tips, explanation = professional_tips(lufs, peak, crest_factor, centroid, dominant_freq)
        st.markdown(
            f"<div dir='ltr' style='text-align:left; background:#fefce8; color:#bb8504; padding:17px; border-radius:16px; margin-top:13px; font-size:1.18em; font-weight:bold; border:2px solid #fde68a;'>"
            f"{main_tip}"
            f"</div>",
            unsafe_allow_html=True
        )
        st.markdown(
            "<div dir='ltr' style='text-align:left; font-size:1.13em; margin-top:13px; color:#111'><b>Professional Recommendations for this Mix:</b></div>",
            unsafe_allow_html=True
        )
        tips_html = "<div dir='ltr' style='text-align:left; font-size: 1.09em; background:#fff; color:#232323; padding:11px 8px 2px 0; border-radius:9px; margin-bottom:13px;'>"
        for tip in tips:
            tips_html += f"• {tip}<br>"
        tips_html += "</div>"
        st.markdown(tips_html, unsafe_allow_html=True)

        with st.expander("📋 Summary for copy/share:"):
            summary = f"""<div dir='ltr' style='text-align:left; font-family:inherit; color:#222; background:#f8fafc; padding:12px; border-radius:10px'>
<b>Auto Summary:</b><br>
Loudness (LUFS): {lufs:.2f}<br>
Peak: {peak:.2f}<br>
Crest Factor: {crest_factor:.2f}<br>
Dominant Frequency: {dominant_freq:.0f}Hz<br>
Centroid: {centroid:.0f}Hz<br>
Genre: {genre}<br>
Project Stage: {project_stage}<br>
Audio File: <a href="{file_url}" target="_blank">{remote_file}</a>
</div>
"""
            st.markdown(summary, unsafe_allow_html=True)

        record = {
            'email': email,
            'file_hash': file_hash,
            'file_url': file_url,
            'filename': remote_file,
            'duration': duration,
            'lufs': lufs,
            'peak': peak,
            'crest_factor': crest_factor,
            'centroid': centroid,
            'dominant_freq': dominant_freq,
            'main_tip': main_tip,
            'tips': "; ".join(tips),
            'genre': genre,
            'project_stage': project_stage,
        }
        save_or_update_record(email, record)

        st.session_state["current_file_hash"] = file_hash
        st.session_state["current_filename"] = remote_file

        st.markdown(
            "<div dir='ltr' style='text-align:left; color:#166534; font-size:1.06em; margin-bottom:7px; margin-top:20px;'>Your feedback will improve the system!</div>",
            unsafe_allow_html=True
        )

        feedback_purpose = st.selectbox(
            "Why did you create/upload this file?",
            [
                "Just checking", "Submit to client", "Streaming upload",
                "Demo phase", "Professional consultation", "Contest/Prize",
                "Other (please specify)"
            ]
        )
        if "Other (please specify)" in feedback_purpose:
            feedback_purpose_free = st.text_input("Free text detail:")
        else:
            feedback_purpose_free = ""

        feedback_hardest = st.multiselect(
            "What bothers you most about your mix? (select multiple)",
            [
                "Bass", "Highs", "Dynamics", "Overall loudness",
                "Unclear sound", "No depth", "No live feeling",
                "Distortion/Clipping", "Other (please specify)"
            ]
        )
        if "Other (please specify)" in feedback_hardest:
            feedback_hardest_free = st.text_input("Free text for problem/shortcoming:")
        else:
            feedback_hardest_free = ""

        self_rating = st.slider(
            "Rate your satisfaction with the mix (1=Not satisfied at all, 10=Completely satisfied):",
            1, 10, 7
        )
        reference = st.text_input("Is there a reference sound you want to achieve? (link/song name/youtube)")
        q1 = st.radio("Were the recommendations relevant?", ["Yes", "No", "Partially"])
        q2 = st.text_area("What would you like to improve in this analysis?", height=100)
        q3 = st.text_area("Any comments/requests – help us improve!", height=100)

        if st.button("Submit feedback"):
            update_payload = {
                'email': email,
                'file_hash': st.session_state.get("current_file_hash"),
                'filename': st.session_state.get("current_filename"),
                'file_url': file_url,
                'feedback_purpose': feedback_purpose,
                'feedback_purpose_free': feedback_purpose_free,
                'self_rating': self_rating,
                'feedback_hardest': '/'.join(feedback_hardest) if feedback_hardest else "",
                'feedback_hardest_free': feedback_hardest_free,
                'reference': reference,
                'q1': q1,
                'q2': q2,
                'q3': q3,
            }
            save_or_update_record(email, update_payload)
            st.success("Thank you for your feedback!")

    except Exception as e:
        st.error(f"⚠️ Error: Unsupported or corrupted file ({e})")