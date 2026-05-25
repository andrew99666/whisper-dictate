"""Stage 0: verify Groq + Gemini API keys work, and confirm gemini-3.5-flash model ID."""
import os
import sys
from dotenv import load_dotenv

load_dotenv()

def check_groq():
    from groq import Groq
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    # Cheap call: list models
    models = client.models.list()
    ids = [m.id for m in models.data]
    has_whisper = "whisper-large-v3-turbo" in ids
    print(f"[Groq] OK — {len(ids)} models available; whisper-large-v3-turbo present: {has_whisper}")
    return has_whisper

def check_gemini():
    from google import genai
    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    # Try the user-requested model first, then fall back so we discover the right ID
    candidates = ["gemini-3.5-flash", "gemini-3.5-flash-latest", "gemini-2.5-flash"]
    for model_id in candidates:
        try:
            resp = client.models.generate_content(
                model=model_id,
                contents="Reply with the single word OK.",
            )
            text = (resp.text or "").strip()
            print(f"[Gemini] OK — model '{model_id}' replied: {text!r}")
            return model_id
        except Exception as e:
            print(f"[Gemini] '{model_id}' failed: {type(e).__name__}: {e}")
    return None

if __name__ == "__main__":
    ok_groq = check_groq()
    gemini_model = check_gemini()
    if ok_groq and gemini_model:
        print(f"\nStage 0 PASS. Use gemini model: {gemini_model}")
        sys.exit(0)
    print("\nStage 0 FAIL.")
    sys.exit(1)
