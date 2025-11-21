
import os
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")

if not API_KEY:
    print("❌ ERROR: GEMINI_API_KEY missing in .env")
else:
    genai.configure(api_key=API_KEY)

# ✅ Text Model
try:
    text_model = genai.GenerativeModel("gemini-pro")
except Exception as e:
    text_model = None
    print("❌ Gemini Text Model Error:", e)

# ✅ Vision Model
try:
    vision_model = genai.GenerativeModel("gemini-pro-vision")
except Exception as e:
    vision_model = None
    print("❌ Gemini Vision Model Error:", e)


def ask_gemini(question):
    """Ask Gemini text model."""
    try:
        if not text_model:
            return "❌ Gemini text model not available."
        response = text_model.generate_content(question)
        return response.text
    except Exception as e:
        print("❌ ask_gemini error:", e)
        return "Gemini API error."


def analyze_with_gemini(image_path, user_text=""):
    """Analyze plant images using Gemini vision model."""
    try:
        if not vision_model:
            return "❌ Gemini vision model not available."

        prompt = (
            "You are an agricultural expert. Analyze this plant image. "
            "Identify disease, pest, nutrient deficiency and give treatment steps."
        )

        if user_text:
            prompt += f"\nUser question: {user_text}"

        image_obj = genai.Image.from_file(image_path)

        response = vision_model.generate_content([prompt, image_obj])
        return response.text

    except Exception as e:
        print("❌ analyze_with_gemini error:", e)
        return "Image analysis failed."
