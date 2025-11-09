#!/usr/bin/env python3
"""
Standalone Blog Generation service.

Usage:
  pip install -r requirements.txt
  export GOOGLE_API_KEY=...
  export OPENAI_API_KEY=...
  uvicorn blog_service:app --reload

Endpoints:
  POST /generate_blog   (form field: prompt_text)
  GET  /generate_blog_status/{job_id}
  GET  /blog
  GET  /blog/{slug}
"""

import os
import re
import json
import hashlib
import datetime
import asyncio
import pathlib
from typing import List, Dict, Optional

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, JSONResponse
from dotenv import load_dotenv
import uvicorn

load_dotenv()

app = FastAPI(title="Standalone Blog Generator")

# Directory to store posts
BLOG_DIR = "blog"
os.makedirs(BLOG_DIR, exist_ok=True)

# LLM setup: try LangChain + Google Gemini (Gemini via ChatGoogleGenerativeAI), else OpenAI
USE_LLMS = False
llm_chain = None
try:
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_core.prompts import  PromptTemplate

    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
    if GOOGLE_API_KEY:
        llm = ChatGoogleGenerativeAI(
            model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
            temperature=float(os.getenv("GEMINI_TEMP", "0.3")),
            google_api_key=GOOGLE_API_KEY,
        )
        prompt_template = PromptTemplate(
            input_variables=["prompt_text"],
            template="{prompt_text}"
        )
        llm_chain = prompt_template | llm
        USE_LLMS = True
        print("✅ Using LangChain + Gemini as LLM.")
    else:
        print("⚠️ GOOGLE_API_KEY not set; Gemini disabled.")
except Exception as e:
    print("⚠️ LangChain/Gemini import failed or not configured:", e)
    USE_LLMS = False

# Utility regex
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?:\+?\d[\d\-\s\(\)]{6,}\d)")

# ---------------- helpers ----------------
def slugify(text: str) -> str:
    s = re.sub(r"[^\w\s-]", "", (text or "")).strip().lower()
    return re.sub(r"[\s_]+", "-", s)[:80] or hashlib.md5((text or "").encode()).hexdigest()[:8]

def save_post(markdown: str, meta: Dict) -> str:
    slug = meta.get("slug") or slugify(meta.get("title", "") or hashlib.md5(markdown.encode()).hexdigest()[:8])
    md_path = os.path.join(BLOG_DIR, f"{slug}.md")
    json_path = os.path.join(BLOG_DIR, f"{slug}.json")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(markdown)
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)
    return slug

def build_generation_prompt(title: str, details: Optional[str] = None) -> str:
    return f"""
Write a clear, developer-friendly article for the title:

Title: "{title}"

Requirements:
- Approx 600-900 words (developer audience).
- Include intro, 3-5 sections with headings, example code blocks where relevant, and a short conclusion.
- Provide a 1-line JSON metadata object on the very first line with fields: title, description, tags (comma-separated). After that JSON line, return the full article in Markdown only.

Additional details: {details or "None"}
"""

def parse_generation_output(raw: str, title: str) -> Dict:
    raw = raw.strip()
    meta = {}
    md = raw
    # If the first line is JSON, parse it.
    first_line, sep, rest = raw.partition("\n")
    try:
        candidate = json.loads(first_line)
        if isinstance(candidate, dict):
            meta = candidate
            md = rest.strip()
    except Exception:
        # No JSON first-line — create metadata heuristically
        excerpt = md.split("\n\n", 1)[0][:160]
        meta = {"title": title, "description": excerpt, "tags": ""}
    meta.setdefault("title", title)
    if "slug" not in meta:
        meta["slug"] = slugify(title)
    meta.setdefault("generated_at", datetime.datetime.utcnow().isoformat() + "Z")
    return {"meta": meta, "markdown": md}

def generate_article_sync(title: str, details: Optional[str] = None) -> Dict:
    prompt = build_generation_prompt(title, details)
    raw_output = None

    # Helper to coerce many response shapes to string
    def coerce_to_text(obj):
        if obj is None:
            return None
        # already a string
        if isinstance(obj, str):
            return obj
        # common langchain message types: AIMessage, HumanMessage, SystemMessage
        # they usually have .content
        if hasattr(obj, "content"):
            try:
                return str(obj.content)
            except Exception:
                pass
        # sometimes it's nested inside .message or .text
        if hasattr(obj, "text"):
            try:
                return str(obj.text)
            except Exception:
                pass
        if hasattr(obj, "message"):
            try:
                m = getattr(obj, "message")
                if isinstance(m, str):
                    return m
                if hasattr(m, "content"):
                    return str(m.content)
            except Exception:
                pass
        # dict-like responses
        if isinstance(obj, dict):
            # common keys
            for k in ("output", "outputs", "text", "content", "result"):
                if k in obj:
                    return coerce_to_text(obj[k])
            # some chains return {'generations': [[Generation]]}
            if "generations" in obj:
                gens = obj["generations"]
                if isinstance(gens, list) and gens:
                    first = gens[0]
                    if isinstance(first, list) and first:
                        # nested
                        candidate = first[0]
                        return coerce_to_text(candidate)
                    return coerce_to_text(first)
        # objects with attribute 'generations'
        if hasattr(obj, "generations"):
            try:
                gens = getattr(obj, "generations")
                if isinstance(gens, list) and gens:
                    first = gens[0]
                    if isinstance(first, list) and first:
                        candidate = first[0]
                        return coerce_to_text(candidate)
                    return coerce_to_text(first)
            except Exception:
                pass
        # fallback to str()
        try:
            return str(obj)
        except Exception:
            return None

    # 1) Try Gemini via LangChain (tolerant invocation)
    if USE_LLMS and llm_chain is not None:
        try:
            # prefer invoke with prompt_text dict if available
            try:
                raw_output = llm_chain.invoke({"prompt_text": prompt})
            except TypeError:
                try:
                    # some runtimes expect named arg
                    raw_output = llm_chain.invoke(prompt_text=prompt)
                except TypeError:
                    try:
                        raw_output = llm_chain.invoke(prompt)
                    except Exception:
                        raw_output = None
            except Exception:
                raw_output = None

            # if still none, try run(...)
            if raw_output is None and hasattr(llm_chain, "run"):
                try:
                    raw_output = llm_chain.run(prompt)
                except TypeError:
                    try:
                        raw_output = llm_chain.run(prompt_text=prompt)
                    except Exception:
                        raw_output = None
                except Exception:
                    raw_output = None

            # if still none and llm_chain is callable
            if raw_output is None and callable(llm_chain):
                try:
                    raw_output = llm_chain(prompt)
                except Exception:
                    raw_output = None

        except Exception as e:
            print("⚠️ llm_chain invocation raised:", repr(e))
            raw_output = None

    # Coerce to string if we got something
    text_out = coerce_to_text(raw_output)

    # Final validation
    if not text_out or not isinstance(text_out, str) or not text_out.strip():
        # helpful debug output
        print("❌ No usable text from LLM. Raw output repr:", repr(raw_output))
        raise RuntimeError("No LLM produced usable text. Check llm_chain invocation and API keys.")

    # Trim and continue
    raw_text = text_out.strip()
    # For debugging, show type and first 120 chars
    cleaned_text = raw_text[:120].replace('\\n',' ')
    print(f"ℹ️ LLM produced text (len={len(raw_text)}): {cleaned_text}")

    parsed = parse_generation_output(raw_text, title)
    markdown = parsed["markdown"]
    meta = parsed["meta"]
    slug = save_post(markdown, meta)
    return {"title": title, "slug": slug, "meta": meta, "markdown": markdown}


# ---------------- async orchestrator ----------------
pending_jobs = {}  # job_id -> {task, items, started}

async def generate_articles_async(items: List[Dict]) -> List[Dict]:
    results = []
    for it in items:
        try:
            article = await asyncio.to_thread(generate_article_sync, it.get("title"), it.get("details"))
            results.append({"title": it.get("title"), "slug": article["slug"], "status": "ok"})
        except Exception as e:
            results.append({"title": it.get("title"), "status": "error", "error": str(e)})
        await asyncio.sleep(float(os.getenv("BLOG_GEN_DELAY", "1.2")))
    return results

# ---------------- HTTP endpoints ----------------
@app.get("/", response_class=HTMLResponse)
async def index():
    return """
    <h2>Standalone Blog Generator</h2>
    <form action="/generate_blog" method="post">
      Enter titles (one per line). Optional: "Title || details" to add notes.<br>
      <textarea name="prompt_text" rows="8" cols="80"></textarea><br>
      <input type="submit" value="Generate (max 10)">
    </form>
    <p>View generated posts: <a href="/blog">/blog</a></p>
    """

@app.post("/generate_blog")
async def generate_blog(prompt_text: str = Form(...)):
    if not prompt_text.strip():
        return {"error": "No input provided."}
    items = []
    for line in prompt_text.splitlines():
        line = line.strip()
        if not line:
            continue
        if "||" in line:
            title, details = [x.strip() for x in line.split("||", 1)]
        else:
            title, details = line, None
        items.append({"title": title, "details": details})
        if len(items) >= 10:
            break
    if not items:
        return {"error": "No valid titles parsed."}
    job_id = hashlib.md5(("".join([i["title"] for i in items]) + datetime.datetime.utcnow().isoformat()).encode()).hexdigest()[:8]
    task = asyncio.create_task(generate_articles_async(items))
    pending_jobs[job_id] = {"task": task, "items": items, "started": datetime.datetime.utcnow().isoformat()}
    return {"job_id": job_id, "message": f"Started generation of {len(items)} articles. Poll /generate_blog_status/{job_id}"}

@app.get("/generate_blog_status/{job_id}")
async def generate_blog_status(job_id: str):
    job = pending_jobs.get(job_id)
    if not job:
        return {"error": "job_id not found"}
    task = job["task"]
    if task.done():
        res = await task
        pending_jobs.pop(job_id, None)
        return {"status": "done", "results": res}
    else:
        return {"status": "running", "items": job["items"], "started": job["started"]}

@app.get("/blog", response_class=HTMLResponse)
async def blog_index():
    files = []
    for p in sorted(pathlib.Path(BLOG_DIR).glob("*.json"), key=os.path.getmtime, reverse=True):
        try:
            with open(p, "r", encoding="utf-8") as fh:
                files.append(json.load(fh))
        except Exception:
            continue
    html = ["<h1>Generated Blog</h1>", "<ul>"]
    for meta in files:
        slug = meta.get("slug") or slugify(meta.get("title", "untitled"))
        title = meta.get("title", slug)
        desc = meta.get("description", "") or meta.get("description", "")
        html.append(f"<li><a href='/blog/{slug}'>{title}</a> — {desc}</li>")
    html.append("</ul>")
    return "\n".join(html)

@app.get("/blog/{slug}", response_class=HTMLResponse)
async def blog_post(slug: str):
    md_path = os.path.join(BLOG_DIR, f"{slug}.md")
    json_path = os.path.join(BLOG_DIR, f"{slug}.json")
    if not os.path.exists(md_path):
        return HTMLResponse(f"<h1>Not found</h1><p>{slug} not found</p>", status_code=404)
    with open(json_path, "r", encoding="utf-8") as fh:
        meta = json.load(fh)
    with open(md_path, "r", encoding="utf-8") as fh:
        md = fh.read()
    # minimal markdown to HTML (replace headings and preserve line breaks)
    html = f"<h1>{meta.get('title')}</h1><p><em>{meta.get('description','')}</em></p><hr>"
    md_html = (
        md.replace("```", "<pre><code>").replace("</code></pre>", "</code></pre>")
        .replace("\n", "<br>")
    )
    html += f"<div>{md_html}</div>"
    return HTMLResponse(html)

# ---------------- Run guidance ----------------
# Start with: uvicorn blog_service:app --reload
# or python -m uvicorn blog_service:app --reload
if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)