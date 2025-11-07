import os, json, re
from typing import Dict, Any
from langdetect import detect, DetectorFactory

DetectorFactory.seed = 0
try:
    from googletrans import Translator
    TRANSLATOR = Translator()
    HAS_GOOGLETRANS = True
except Exception:
    TRANSLATOR = None
    HAS_GOOGLETRANS = False

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY') or None
if OPENAI_API_KEY:
    try:
        from openai import OpenAI
        OPENAI_CLIENT = OpenAI(api_key=OPENAI_API_KEY)
        HAS_OPENAI = True
    except Exception:
        HAS_OPENAI = False
        OPENAI_CLIENT = None
else:
    HAS_OPENAI = False
    OPENAI_CLIENT = None

KB_PATH = os.path.join(os.path.dirname(__file__), 'kb.json')

def load_kb():
    if not os.path.exists(KB_PATH):
        return {}
    with open(KB_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    out = {}
    if isinstance(data, list):
        for entry in data:
            keys = entry.get('keywords') or []
            if isinstance(keys, str):
                keys = [k.strip() for k in keys.split(',') if k.strip()]
            for k in keys:
                out[k.lower()] = {
                    'en': entry.get('answer_en', ''),
                    'hi': entry.get('answer_hi', ''),
                    'ta': entry.get('answer_ta', ''),
                    'te': entry.get('answer_te', ''),  # Telugu added
                    'kn': entry.get('answer_kn', '')   # Kannada added
                }
    elif isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, str):
                out[k.lower()] = {'en': v}
            elif isinstance(v, dict):
                out[k.lower()] = {
                    'en': v.get('answer_en', ''),
                    'hi': v.get('answer_hi', ''),
                    'ta': v.get('answer_ta', ''),
                    'te': v.get('answer_te', ''),  # Telugu added
                    'kn': v.get('answer_kn', '')   # Kannada added
                }
    return out

KB = load_kb()

def detect_language(text: str) -> str:
    try:
        return detect(text)
    except Exception:
        return 'en'

def translate_text(text: str, dest: str) -> str:
    dest = dest[:2]
    if not HAS_GOOGLETRANS:
        return text
    try:
        return TRANSLATOR.translate(text, dest=dest).text
    except Exception:
        return text

def find_in_kb(message: str):
    m = message.lower()
    for k, v in KB.items():
        if k in m:
            return v
    tokens = re.findall(r"\w+", m)
    for k, v in KB.items():
        ktoks = re.findall(r"\w+", k)
        if any(t in ktoks for t in tokens if len(t) > 3):
            return v
    return None

def openai_fallback(user_profile: Dict[str, Any], message_text: str, target_lang: str = 'en') -> str:
    if not HAS_OPENAI or not OPENAI_CLIENT:
        return ''
    try:
        lang_names = {'en': 'English', 'hi': 'Hindi', 'ta': 'Tamil', 'te': 'Telugu', 'kn': 'Kannada'}
        lang_name = lang_names.get(target_lang[:2], 'English')

        system_msg = f"You are an expert agricultural assistant helping farmers with crop advice, pest control, soil management, and farming best practices. Always respond in {lang_name}."
        user_msg = f"User profile: Crop={user_profile.get('primary_crop', 'N/A')}, Region={user_profile.get('region', 'N/A')}\n\nQuestion: {message_text}\n\nProvide a helpful, concise answer in {lang_name}."

        resp = OPENAI_CLIENT.chat.completions.create(
            model='gpt-4o-mini',
            messages=[
                {'role': 'system', 'content': system_msg},
                {'role': 'user', 'content': user_msg}
            ],
            max_tokens=300,
            temperature=0.7
        )
        text = resp.choices[0].message.content.strip()
        return text
    except Exception as e:
        print(f"OpenAI error: {e}")
        return ''

def process_message(user_profile: Dict[str, Any], message_text: str) -> str:
    if not message_text or not message_text.strip():
        return 'Please ask a question about crops, soil, or pests.'
    detected = detect_language(message_text)
    if HAS_GOOGLETRANS and detected != 'en':
        try:
            english_text = translate_text(message_text, 'en')
        except Exception:
            english_text = message_text
    else:
        english_text = message_text

    kb_item = find_in_kb(english_text)
    if kb_item:
        lang = (user_profile.get('preferred_language') or detected or 'en')[:2]
        ans = (
            kb_item.get(lang)
            or kb_item.get('en')
            or next(iter(kb_item.values()), '')
        )
        if not ans and kb_item.get('en') and lang != 'en' and HAS_GOOGLETRANS:
            ans = translate_text(kb_item.get('en'), lang)
        return ans

    if HAS_OPENAI:
        resp = openai_fallback(
            user_profile or {},
            english_text,
            target_lang=(user_profile.get('preferred_language') or detected or 'en')[:2]
        )
        if resp:
            return resp
    return "I don't have that answer in KB. Try asking about a specific crop or pest."
