# 🚀 AI-Powered Automation Suite

This repository contains **three independent AI automation services** built using **FastAPI**, **LangChain**, **Twilio**, and **Google Gemini / OpenAI APIs**.

Each module is a self-contained microservice that demonstrates **AI + automation integration** for real-world use cases:

1. 🕵️‍♂️ LinkedIn Profile Scraper
2. 📞 AI Autodialer (Twilio + Gemini)
3. ✍️ AI Blog Generator (Gemini / OpenAI)

---

## 🧩 Project Structure

```
ai-automation-suite/
│
├── Scrape_LinkedIn/linkedin_scraper.py       # Task 1: LinkedIn Profile Scraper
├── AutoDialer/autodialer.py             # Task 2: AI Autodialer (Twilio + Gemini)
├── blog/blog_service.py           # Task 3: Blog Generator (Gemini / OpenAI)
├── requirements.txt
└── .env                      # Environment keys for APIs
```

---

## 🧠 Task 1 — LinkedIn Profile Scraper

### 📋 Overview

Scrapes **public or logged-in LinkedIn profiles** and extracts:

* Full Name
* Headline / Job Title
* Location
* About section
* Experience
* Profile URL

The script uses **Selenium** with randomized user agents and optional login for private profiles.

---

### ⚙️ Setup

```bash
pip install selenium python-dotenv pandas
```

Download and extract [ChromeDriver](https://chromedriver.chromium.org/downloads) matching your Chrome version,
then update the path inside the script:

```python
CHROMEDRIVER_PATH = r"C:/path/to/chromedriver.exe"
```

---

### 🔐 Environment Variables

Create a `.env` file:

```
LINKEDIN_EMAIL=your_email@example.com
LINKEDIN_PASSWORD=your_password
```

---

### ▶️ Run

```bash
python linkedin_scraper.py
```

You can list profile URLs (one per line) in `input_profiles.txt`.
After execution, the script generates:

```
profiles.csv
```

containing extracted profile data.

---

### 💡 Tip

To avoid being blocked by LinkedIn:

* Use **randomized user agents** (already implemented)
* Add **sleep delays** between profile visits
* Don’t scrape hundreds of profiles per session

---

## 📞 Task 2 — AI Autodialer (Twilio + Gemini)

### 📋 Overview

An **AI-powered autodialer web app** that:

* Automatically calls uploaded phone numbers via **Twilio**
* Accepts natural language commands (e.g., “Call all uploaded numbers”)
* Integrates **Google Gemini** via LangChain for understanding commands
* Logs call status (initiated, failed, invalid)

---

### ⚙️ Setup

```bash
pip install fastapi uvicorn twilio python-dotenv langchain-google-genai
```

---

### 🔐 Environment Variables

Create a `.env` file with your Twilio & Gemini credentials:

```
TWILIO_ACCOUNT_SID=your_twilio_sid
TWILIO_AUTH_TOKEN=your_twilio_auth_token
TWILIO_PHONE_NUMBER=+1234567890
GOOGLE_API_KEY=your_gemini_api_key
```

---

### ▶️ Run

```bash
uvicorn autodialer:app --reload
```

Then open:
🔗 **[http://127.0.0.1:8000](http://127.0.0.1:8000)**

---

### 🧩 Features

* Upload a `.csv` or `.txt` file with `+91XXXXXXXXXX` numbers
* Use AI prompt:

  ```
  Make a call to +919876543210
  ```

  or

  ```
  Start calling all uploaded numbers
  ```
* View call logs at `/logs`

---

### 🪄 Example Interaction

**Prompt:**

> Call +911234567890 and +919876543210

**Response:**

```json
{
  "message": "📞 Calling ['+911234567890', '+919876543210']"
}
```

**Call Log Example (`/logs`):**

```json
[
  {"number": "+911234567890", "status": "initiated"},
  {"number": "+919876543210", "status": "failed", "error": "Invalid number"}
]
```

---

## ✍️ Task 3 — AI Blog Generator (Gemini / OpenAI)

### 📋 Overview

A **standalone AI blog generation service** that:

* Generates 10 high-quality programming articles at once
* Uses **Google Gemini** or **OpenAI GPT-4/4o-mini**
* Saves posts as Markdown + JSON files
* Provides `/blog` and `/blog/{slug}` endpoints for viewing
* Accepts simple prompts like:

  ```
  Machine Learning Basics || Include example using scikit-learn
  Neural Networks || Focus on Keras code examples
  ```

---

### ⚙️ Setup

```bash
pip install fastapi uvicorn python-dotenv langchain-google-genai openai
```

---

### 🔐 Environment Variables

Create `.env` with one or both keys:

```
GOOGLE_API_KEY=your_gemini_api_key
OPENAI_API_KEY=your_openai_key
OPENAI_MODEL=gpt-4o-mini
```

---

### ▶️ Run

```bash
uvicorn blog_service:app --reload
```

Access:

* Home: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)
* API Docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
* Blog index: [http://127.0.0.1:8000/blog](http://127.0.0.1:8000/blog)

---

### 🧩 Example

Form input:

```
Python Decorators || Include code and real-world use case
LangChain Introduction || Explain prompt templates and chains
```

Response:

```json
{
  "job_id": "ab12cd34",
  "message": "Started generation of 2 articles. Poll /generate_blog_status/ab12cd34"
}
```

Check progress:

```
GET /generate_blog_status/ab12cd34
```

Once done, articles appear under `/blog` and saved as:

```
blog/python-decorators.md
blog/langchain-introduction.md
```

---

### 📁 Blog Directory Structure

```
blog/
 ├── python-decorators.md
 ├── python-decorators.json
 ├── langchain-introduction.md
 └── langchain-introduction.json
```

---

## 🧰 requirements.txt (combined)

```txt
fastapi
uvicorn
selenium
python-dotenv
pandas
twilio
langchain
langchain-google-genai
openai
```

---

## 🧠 Summary

| Task | Name             | Core Tech                           | Purpose                                           |
| ---- | ---------------- | ----------------------------------- | ------------------------------------------------- |
| 1    | LinkedIn Scraper | Selenium + Pandas                   | Extract structured info from LinkedIn profiles    |
| 2    | AI Autodialer    | FastAPI + Twilio + Gemini           | Automate test calls with natural language control |
| 3    | Blog Generator   | FastAPI + LangChain + Gemini/OpenAI | Generate developer blogs in Markdown via AI       |

---