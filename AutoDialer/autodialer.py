# autodialer.py
from fastapi import FastAPI, UploadFile, Form
from fastapi.responses import HTMLResponse, JSONResponse
from twilio.rest import Client
import pandas as pd
import re, os, asyncio
from dotenv import load_dotenv
import json
import uvicorn
import logging

load_dotenv()
app = FastAPI(title="AI Autodialer")

# -------------------- TWILIO SETUP --------------------
twilio_client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
# TWILIO_PHONE = os.getenv("TWILIO_PHONE_NUMBER")

# -------------------- GEMINI / LANGCHAIN SETUP --------------------
# We attempt to use LangChain + ChatGoogleGenerativeAI. If it fails (missing package or invalid config)
# we fall back to a simple rule-based parser.
USE_LLMS = False
llm_chain = None

try:
    # Try canonical langchain imports (works with recent langchain versions)
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_core.prompts import PromptTemplate

    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
    if GOOGLE_API_KEY:
        llm = ChatGoogleGenerativeAI(
            model="gemini-1.5-flash",
            temperature=0.3,
            google_api_key=GOOGLE_API_KEY
        )

        prompt_template = PromptTemplate(
            input_variables=["command"],
            template="""
You are an assistant controlling an autodialer that can:
- start calling uploaded numbers,
- call specific numbers,
- show call logs.

Respond in strict JSON only with this shape:
{{
  "action": "call" | "show_logs" | "unknown",
  "numbers": ["+91XXXXXXXXXX", ...]
}}

User command: "{command}"
"""
        )

        llm_chain = prompt_template | llm
        USE_LLMS = True
        logging.info("✅ LangChain + Gemni initialized")
    else:
        logging.warning("⚠️ GOOGLE_API_KEY not set; LangChain disabled")
except Exception as e:
    logging.warning("⚠️ LangChain/Gemini not available or failed to import: %s", e)
    USE_LLMS = False

# -------------------- GLOBALS --------------------
call_logs = []

def validate_number(num: str):
    return bool(re.match(r"^\+91\d{10}$", num))


# -------------------- ROUTES --------------------
@app.get("/", response_class=HTMLResponse)
async def home():
    return """
    <h2>📞 AI Autodialer (Gemini + Twilio)</h2>
    <form action="/upload" method="post" enctype="multipart/form-data">
        Upload CSV or TXT with numbers:<br>
        <input type="file" name="file"><br><br>
        <input type="submit" value="Upload">
    </form>
    <br>
    <form action="/prompt" method="post">
        Enter AI command:<br>
        <input type="text" name="text" style="width:400px;">
        <input type="submit" value="Run">
    </form>
    <br>
    <a href="/logs">📜 View Logs</a>
    <p>API docs: <a href="/docs">/docs</a> and OpenAPI JSON: <a href="/openapi.json">/openapi.json</a></p>
    """


@app.post("/upload")
async def upload(file: UploadFile):
    content = await file.read()
    text = content.decode(errors="ignore")
    numbers = re.findall(r"\+91\d{10}", text)
    if not numbers:
        return {"error": "No valid +91 numbers found (expected +91XXXXXXXXXX format)."}
    df = pd.DataFrame({"phone": numbers})
    df.to_csv("numbers.csv", index=False)
    return {"message": f"✅ Uploaded {len(numbers)} numbers", "sample": numbers[:5]}


async def parse_command_with_fallback(command: str):
    """
    Try to parse `command` using the LLM chain if available; otherwise use a rule-based parser.
    Returns a dict with keys action and numbers.
    """
    # 1) If LLM available, use it
    if USE_LLMS and llm_chain is not None:
        try:
            # llm_chain.run returns a string; we try to parse JSON from it
            raw = llm_chain.run(command)
            logging.debug("LLM raw response: %s", raw)
            # try to parse JSON directly
            try:
                parsed = json.loads(raw)
                return parsed
            except Exception:
                # fallback: extract first {...} block
                m = re.search(r"\{.*\}", raw, re.DOTALL)
                if m:
                    try:
                        parsed = json.loads(m.group(0))
                        return parsed
                    except Exception:
                        logging.warning("LLM returned JSON-like but unparsable content.")
                # if LLM output unparseable, fall through to rule-based
        except Exception as e:
            logging.warning("LLM chain failed: %s", e)

    # 2) Rule-based fallback parser
    cmd = command.lower()
    numbers = re.findall(r"\+91\d{10}", cmd)
    action = "unknown"
    if "call" in cmd or "dial" in cmd or "make a call" in cmd:
        action = "call"
    elif "log" in cmd or "show logs" in cmd or "show call logs" in cmd:
        action = "show_logs"
    return {"action": action, "numbers": numbers}


@app.post("/prompt")
async def handle_prompt(text: str = Form(...)):
    """Handles natural language AI prompts using Gemini (LangChain) with fallback to rules."""
    text = text.strip()
    if not text:
        return {"error": "No prompt provided."}
    logging.info("Received prompt: %s", text)

    parsed = await parse_command_with_fallback(text)
    logging.info("Parsed command: %s", parsed)

    action = parsed.get("action", "unknown")
    numbers = parsed.get("numbers", []) or []

    # Action handlers
    if action == "show_logs":
        return JSONResponse(call_logs)

    if action == "call":
        if numbers:
            asyncio.create_task(start_calls(numbers))
            return {"message": f"📞 Calling {numbers}"}
        elif os.path.exists("numbers.csv"):
            df = pd.read_csv("numbers.csv")
            nums = df["phone"].dropna().astype(str).tolist()
            asyncio.create_task(start_calls(nums))
            return {"message": f"📞 Started calling {len(nums)} uploaded numbers"}
        else:
            return {"error": "No numbers provided and no uploaded CSV found."}

    return {"AI understanding": parsed}


# -------------------- CALL LOGIC --------------------
async def start_calls(numbers):
    """Sequentially call numbers via Twilio - updates call_logs in-memory."""
    for raw_num in numbers:
        num = raw_num.strip()
        if not validate_number(num):
            call_logs.append({"number": num, "status": "invalid", "ts": datetime_now()})
            continue
        try:
            call = twilio_client.calls.create(
                to=num,
                from_=TWILIO_PHONE,
                twiml='<Response><Say voice="alice">Hello! This is an automated test call from AI Autodialer.</Say></Response>'
            )
            call_logs.append({"number": num, "sid": call.sid, "status": "initiated", "ts": datetime_now()})
        except Exception as e:
            call_logs.append({"number": num, "status": "failed", "error": str(e), "ts": datetime_now()})
        await asyncio.sleep(2)  # delay between calls


def datetime_now():
    import datetime
    return datetime.datetime.utcnow().isoformat() + "Z"


@app.get("/logs")
def logs():
    return JSONResponse(call_logs)


# Run with `python autodialer.py` or `uvicorn autodialer:app --reload`
if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
