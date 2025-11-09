import os
import csv
import random
import time
import datetime
import re
import json
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    WebDriverException,
    ElementClickInterceptedException,
)
from selenium.webdriver.common.keys import Keys
from scrape_html import parse_contact_html

# ---------------- CONFIG ----------------
CHROMEDRIVER_PATH = r"C:/Users/Om Nagvekar/Downloads/chromedriver-win64/chromedriver-win64/chromedriver.exe"
INPUT_FILE = "input_profiles.txt"
OUTPUT_CSV = "profiles.csv"
RAW_HTML_DIR = "raw_html"

# adjust these as needed
WAIT_SHORT = 5
WAIT_LONG = 20

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/94.0.4606.61 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.131 Safari/537.36",
]

load_dotenv()
LINKEDIN_EMAIL = os.getenv("LINKEDIN_EMAIL")
LINKEDIN_PASSWORD = os.getenv("LINKEDIN_PASSWORD")

os.makedirs(RAW_HTML_DIR, exist_ok=True)


# ---------------- DRIVER SETUP ----------------
def create_driver(headless=False):
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument(f"user-agent={random.choice(USER_AGENTS)}")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--start-maximized")
    svc = Service(CHROMEDRIVER_PATH)
    driver = webdriver.Chrome(service=svc, options=opts)
    driver.set_window_size(1600, 1000)
    return driver


# ---------------- LOGIN (OPTIONAL) ----------------
def linkedin_login(driver):
    if not LINKEDIN_EMAIL or not LINKEDIN_PASSWORD:
        print("⚠️ No LinkedIn credentials found — scraping public pages only.")
        return False

    driver.get("https://www.linkedin.com/login")

    try:
        # Wait for username input (longer wait)
        email_field = WebDriverWait(driver, WAIT_LONG).until(
            EC.presence_of_element_located((By.ID, "username"))
        )
        email_field.clear()
        email_field.send_keys(LINKEDIN_EMAIL)

        # Enter password
        password_field = driver.find_element(By.ID, "password")
        password_field.clear()
        password_field.send_keys(LINKEDIN_PASSWORD)

        # Try to uncheck a few possible checkbox names (be tolerant)
        checkbox_names = ["rememberMe", "rememberMeOptIn", "persist", "keepMeLoggedIn"]
        found_checkbox = False
        for name in checkbox_names:
            try:
                remember_checkbox = driver.find_element(By.NAME, name)
                found_checkbox = True
                try:
                    if remember_checkbox.is_selected():
                        driver.execute_script(
                            "arguments[0].checked = false; arguments[0].dispatchEvent(new Event('change'));",
                            remember_checkbox,
                        )
                        print(f"🟢 Checkbox '{name}' unchecked.")
                    else:
                        print(f"ℹ️ Checkbox '{name}' already unchecked.")
                except Exception:
                    try:
                        remember_checkbox.click()
                        print(f"🟢 Clicked to uncheck checkbox '{name}'.")
                    except Exception:
                        print(f"⚠️ Could not uncheck checkbox '{name}'.")
                break
            except NoSuchElementException:
                continue
        if not found_checkbox:
            print("⚠️ 'Remember me' checkbox not found (LinkedIn layout may be different).")

        # Click Sign In
        login_button = driver.find_element(By.XPATH, "//button[@type='submit']")
        driver.execute_script("arguments[0].click();", login_button)

        # Wait until homepage or nav bar appears (give it more time)
        WebDriverWait(driver, WAIT_LONG).until(EC.presence_of_element_located((By.ID, "global-nav-search")))
        print("✅ Logged in to LinkedIn successfully (without 'Remember me').")
        return True

    except TimeoutException:
        print("❌ Login failed or took too long.")
        return False
    except Exception as e:
        print("❌ Login error:", e)
        return False


# ---------------- HELPERS ----------------
def save_raw_html(driver, filename):
    path = os.path.join(RAW_HTML_DIR, filename)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        return path
    except Exception as e:
        print("Failed to save raw html:", e)
        return None


def slow_scroll(driver, pause=0.8, max_scrolls=20):
    """
    Slowly scrolls the page down, waiting for content to load.
    - pause: seconds between incremental scrolls
    - max_scrolls: maximum number of incremental scrolls
    The function checks the document height; if height grows, it continues.
    """
    try:
        last_height = driver.execute_script("return document.body.scrollHeight")
        scrolls = 0
        while scrolls < max_scrolls:
            # calculate incremental scroll distance
            viewport_height = driver.execute_script("return window.innerHeight")
            # scroll down by one viewport each iteration
            driver.execute_script("window.scrollBy(0, arguments[0]);", viewport_height * 0.9)
            scrolls += 1
            time.sleep(pause + random.uniform(0.1, 0.6))  # slight randomization
            new_height = driver.execute_script("return document.body.scrollHeight")
            # if new content loaded, reset counter to allow more scrolls
            if new_height > last_height:
                last_height = new_height
                # small extra wait to allow lazy-load images/text
                time.sleep(0.5 + random.uniform(0.1, 0.5))
            else:
                # if no new content, break early
                break
        # ensure top-to-bottom scan as well
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(0.3)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(0.6)
    except WebDriverException as e:
        # if scrolling fails for some reason, ignore and continue
        print("⚠️ slow_scroll encountered an error:", e)


def click_show_more(driver):
    """Click common 'show more' or 'see more' buttons to reveal hidden text."""
    texts = ["See more", "see more", "Show more", "show more", "See More"]
    for t in texts:
        try:
            els = driver.find_elements(By.XPATH, f"//button[contains(., '{t}')]")
            for el in els:
                try:
                    driver.execute_script("arguments[0].scrollIntoView(true);", el)
                    # try safe click; if intercepted, try JS click
                    try:
                        el.click()
                    except (ElementClickInterceptedException, WebDriverException):
                        driver.execute_script("arguments[0].click();", el)
                    time.sleep(0.4)
                except Exception:
                    pass
        except Exception:
            pass


def safe_text(el):
    return el.text.strip() if el is not None else ""


# ---------------- CONTACT INFO EXTRACTION ----------------
def extract_contact_info(driver, wait_time=15):
    """
    Robust Contact Info extractor:
    - Clicks the Contact info trigger (if present)
    - Waits for either overlay URL change (overlay/contact-info) OR role='dialog'
    - Scrolls the modal element to reveal lazy content
    - Extracts mailto:, tel:, http(s) anchors and regex-matched emails/phones/websites
    - Saves modal outerHTML to RAW_HTML_DIR for debugging
    - Closes modal and returns a dict
    """
    contact = {"emails": [], "phones": [], "websites": [], "other": []}
    try:
        # 1) Find and click the "Contact info" trigger (tolerant selectors)
        trigger = None
        candidates = []
        try:
            candidates += driver.find_elements(By.XPATH, "//a[normalize-space(.)='Contact info' or contains(normalize-space(.),'Contact info')]")
        except Exception:
            pass
        try:
            candidates += driver.find_elements(By.XPATH, "//button[normalize-space(.)='Contact info' or contains(normalize-space(.),'Contact info')]")
        except Exception:
            pass
        try:
            candidates += driver.find_elements(By.XPATH, "//*[contains(normalize-space(.), 'Contact info') and (name() = 'a' or name() = 'button' or name() = 'span')]")
        except Exception:
            pass

        for t in candidates:
            if t and t.is_displayed():
                trigger = t
                break

        if not trigger:
            # nothing to open
            return contact

        # Click the trigger (JS click first)
        try:
            driver.execute_script("arguments[0].click();", trigger)
        except Exception:
            try:
                trigger.click()
            except Exception:
                pass

        # 2) Wait — either for overlay URL change or a dialog element
        modal = None
        try:
            # check for overlay URL (e.g., /overlay/contact-info/)
            for _ in range(wait_time):
                current = driver.current_url
                if "/overlay/contact-info" in current.lower():
                    # allow DOM settle
                    time.sleep(0.6)
                    break
                time.sleep(0.4)
            # now try waiting for role=dialog with classes expected in modal
            modal = WebDriverWait(driver, wait_time).until(
                EC.presence_of_element_located((By.XPATH, "//div[@role='dialog' and (contains(@class,'artdeco-modal') or contains(@class,'pv-contact-info') or contains(@class,'overlay') or contains(@class,'contact'))]"))
            )
        except TimeoutException:
            # broader fallback: any role=dialog
            try:
                modal = WebDriverWait(driver, 6).until(EC.presence_of_element_located((By.XPATH, "//div[@role='dialog']")))
            except TimeoutException:
                # as a last resort, try to find an element with overlay/contact-info in href (some LinkedIn versions navigate)
                try:
                    # try to fetch an element with overlay path
                    links = driver.find_elements(By.XPATH, "//a[contains(@href,'overlay/contact-info') or contains(@href,'contact-info')]")
                    if links:
                        # click the first and wait shortly
                        try:
                            driver.execute_script("arguments[0].click();", links[0])
                        except Exception:
                            pass
                        modal = WebDriverWait(driver, 6).until(EC.presence_of_element_located((By.XPATH, "//div[@role='dialog']")))
                    else:
                        return contact
                except Exception:
                    return contact

        # 3) Scroll modal slowly to reveal lazy content
        try:
            driver.execute_script("""
                const modal = arguments[0];
                if(modal){
                  const total = modal.scrollHeight || (document.body.scrollHeight/2);
                  let step = Math.max(200, Math.floor(total/8));
                  let pos = 0;
                  for(let i=0;i<12;i++){
                    pos = Math.min(pos + step, total);
                    modal.scrollTop = pos;
                  }
                }
            """, modal)
            time.sleep(0.6)
        except Exception:
            try:
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(0.4)
            except Exception:
                pass

        # 4) Save modal outerHTML for debugging
        modal_html_path = None
        try:
            ts = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            modal_html_path = os.path.join(RAW_HTML_DIR, f"modal_{ts}.html")
            with open(modal_html_path, "w", encoding="utf-8") as fh:
                fh.write(modal.get_attribute("outerHTML") or driver.page_source)
        except Exception:
            modal_html_path = None

        # 5) Collect anchors (most reliable)
        try:
            anchors = modal.find_elements(By.XPATH, ".//a")
        except Exception:
            anchors = []
        for a in anchors:
            try:
                href = a.get_attribute("href") or ""
                text = a.text.strip() or ""
            except Exception:
                href = ""
                text = ""
            if href.startswith("mailto:"):
                email = href.split("mailto:")[1].split("?")[0]
                if email and email not in contact["emails"]:
                    contact["emails"].append(email.strip())
            elif href.startswith("tel:"):
                ph = href.split("tel:")[-1]
                ph = re.sub(r"\s+", " ", ph).strip()
                if ph and ph not in contact["phones"]:
                    contact["phones"].append(ph)
            elif href.startswith("http"):
                if href not in contact["websites"]:
                    contact["websites"].append(href.strip())
            else:
                # anchor text might itself be an email/phone/website
                for m in re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text):
                    if m not in contact["emails"]:
                        contact["emails"].append(m)
                for ph in re.findall(r"(?:\+?\d[\d\-\s\(\)]{6,}\d)", text):
                    cleaned = re.sub(r"\s+", " ", ph).strip()
                    if cleaned not in contact["phones"]:
                        contact["phones"].append(cleaned)
                if re.search(r"[A-Za-z0-9\.-]+\.(?:com|io|co|in|org|net)\b", text) and text not in contact["websites"]:
                    if not re.search(r"@", text):
                        contact["websites"].append(text.strip())

        # 6) Fallback - scan visible text nodes inside modal and regex
        try:
            text_nodes = modal.find_elements(By.XPATH, ".//*[normalize-space(text())]")
            for el in text_nodes:
                try:
                    t = el.text.strip()
                except Exception:
                    t = ""
                if not t or len(t) < 3:
                    continue
                # emails
                for m in re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", t):
                    if m not in contact["emails"]:
                        contact["emails"].append(m)
                # phones
                for ph in re.findall(r"(?:\+?\d[\d\-\s\(\)]{6,}\d)", t):
                    cleaned = re.sub(r"\s+", " ", ph).strip()
                    if cleaned not in contact["phones"]:
                        contact["phones"].append(cleaned)
                # websites/domains
                for w in re.findall(r"(https?://[^\s]+|[A-Za-z0-9\.-]+\.(?:com|io|co|in|org|net)[^\s]*)", t):
                    w_clean = w.strip().strip(".,;")
                    if w_clean not in contact["websites"]:
                        contact["websites"].append(w_clean)
                # collect other useful lines
                lower = t.lower()
                if lower not in ["phone", "email", "website", "birthday", "your profile", "contact info", "edit contact info"]:
                    if t not in contact["other"]:
                        contact["other"].append(t)
        except Exception:
            pass

        # 7) Close modal (button or ESC)
        try:
            close_btns = modal.find_elements(By.XPATH, ".//button[contains(@aria-label,'Close') or contains(@class,'artdeco-modal__dismiss') or contains(normalize-space(.),'Close') or contains(normalize-space(.),'Dismiss')]")
            closed = False
            for cb in close_btns:
                try:
                    driver.execute_script("arguments[0].click();", cb)
                    closed = True
                    time.sleep(0.3)
                    break
                except Exception:
                    continue
            if not closed:
                body = driver.find_element(By.TAG_NAME, "body")
                body.send_keys(Keys.ESCAPE)
                time.sleep(0.2)
        except Exception:
            pass

        # normalize and dedupe
        contact["emails"] = list(dict.fromkeys([e.strip() for e in contact["emails"] if e]))
        contact["phones"] = list(dict.fromkeys([p.strip() for p in contact["phones"] if p]))
        contact["websites"] = list(dict.fromkeys([w.strip() for w in contact["websites"] if w]))
        contact["other"] = list(dict.fromkeys([o.strip() for o in contact["other"] if o]))

        # debug hint if nothing parsed
        if not (contact["emails"] or contact["phones"] or contact["websites"] or contact["other"]):
            print("⚠️ extract_contact_info: modal opened but no contact fields parsed. Modal HTML saved at:", modal_html_path)
        else:
            print("ℹ️ extract_contact_info parsed:", contact)

    except Exception as e:
        print("⚠️ extract_contact_info error:", e)
    return contact



# ---------------- SCRAPE PROFILE ----------------
def scrape_profile(driver, url, max_retries=2):
    """Scrape a single LinkedIn profile with robust fallbacks and slower scrolling / waits."""
    data = {"profile_url": url, "scraped_at": datetime.datetime.utcnow().isoformat()}
    last_exception = None

    for attempt in range(1, max_retries + 1):
        try:
            # Direct navigation first (less noisy)
            print(f"ℹ️ Navigating to {url} (attempt {attempt})")
            driver.get(url)

            # Wait longer for the main heading or sign-in page to appear
            try:
                WebDriverWait(driver, WAIT_LONG).until(
                    EC.presence_of_element_located((By.TAG_NAME, "h1"))
                )
            except TimeoutException:
                # maybe login wall; allow additional time for redirects
                time.sleep(random.uniform(3, 6))

            # If LinkedIn shows login wall, try Google fallback
            if "login" in driver.current_url.lower() and attempt == 1:
                print("ℹ️ Detected login wall; trying Google fallback...")
                query_url = f"https://www.google.com/search?q={url}"
                driver.get(query_url)
                time.sleep(random.uniform(2, 3))
                anchors = driver.find_elements(By.CSS_SELECTOR, "a")
                clicked = False
                for a in anchors:
                    href = a.get_attribute("href") or ""
                    if "linkedin.com/in" in href:
                        try:
                            a.click()
                            clicked = True
                            break
                        except Exception:
                            continue
                if not clicked:
                    driver.get(url)
                # give the page extra time
                time.sleep(random.uniform(3, 6))

            # Slowly scroll to let lazy content load
            slow_scroll(driver, pause=0.8, max_scrolls=25)

            # small extra wait for dynamic content to render
            time.sleep(random.uniform(1.0, 2.5))

            # expand show-more sections
            click_show_more(driver)

            # final slow scroll to ensure all is loaded
            slow_scroll(driver, pause=0.6, max_scrolls=6)

            # --- NEW: extract contact info by opening the Contact Info modal ---
            try:
                contact_info = extract_contact_info(driver, wait_time=10)
                data["contact_info"] = contact_info
                # small wait after modal close
                time.sleep(0.6)
            except Exception as e:
                data["contact_info"] = {"error": str(e)}

            # Save raw HTML for debugging (after content load)
            raw_path = save_raw_html(driver, f"{url.split('/')[-1]}.html")
            data["raw_html"] = raw_path

            # ---- NEW: parse saved HTML file with parse_contact_html() ----
            parsed = {}
            try:
                if raw_path and os.path.exists(raw_path):
                    parsed = parse_contact_html(filepath=raw_path)
                else:
                    # fallback: parse current page source directly
                    parsed = parse_contact_html(content=driver.page_source)
            except Exception as e:
                parsed = {"error": f"parse_contact_html failed: {e}"}
            # attach parsed result
            data["contact_parsed"] = parsed

            # NAME - many LinkedIn pages use h1 as name - fallback to common classes
            name = ""
            try:
                # wait longer for h1
                name_elem = WebDriverWait(driver, WAIT_LONG).until(EC.presence_of_element_located((By.TAG_NAME, "h1")))
                name = name_elem.text.strip()
            except Exception:
                try:
                    el = driver.find_element(By.CSS_SELECTOR, "div.ph5 h1")
                    name = el.text.strip()
                except Exception:
                    name = ""
            data["full_name"] = name

            # HEADLINE - fallback multiple selectors
            headline = ""
            try:
                headline = driver.find_element(By.CSS_SELECTOR, "div.text-body-medium.break-words").text.strip()
            except Exception:
                try:
                    headline = driver.find_element(By.CSS_SELECTOR, ".pv-text-details__left-panel .text-body-medium").text.strip()
                except Exception:
                    headline = ""
            data["headline"] = headline

            # LOCATION
            location = ""
            try:
                location = driver.find_element(By.CSS_SELECTOR, "span.t-black--light.inline").text.strip()
            except Exception:
                try:
                    location = driver.find_element(By.CSS_SELECTOR, ".pv-top-card--list-bullet li").text.strip()
                except Exception:
                    location = ""
            data["location"] = location

            # ABOUT - LinkedIn 'About' may be in different selectors
            about = ""
            try:
                about_el = None
                try:
                    about_el = driver.find_element(By.XPATH, "//section[contains(@class,'pv-about-section')]")
                except Exception:
                    try:
                        about_el = driver.find_element(By.ID, "about")
                    except Exception:
                        about_el = driver.find_element(By.XPATH, "//div[contains(@class,'pv-shared-text-with-see-more')]")
                about = about_el.text.strip() if about_el else ""
            except Exception:
                about = ""
            data["about"] = about

            # EXPERIENCE - collect first 2-3 experience items if present
            experiences = []
            try:
                exp_sections = driver.find_elements(By.XPATH, "//section[contains(@id,'experience') or contains(@class,'experience-section')]")
                if not exp_sections:
                    exp_sections = driver.find_elements(By.CSS_SELECTOR, "section.pv-profile-section.experience-section ul li")
                for sec in exp_sections:
                    items = sec.find_elements(By.TAG_NAME, "li")
                    for it in items[:3]:
                        txt = it.text.strip().split("\n")[0]
                        if txt:
                            experiences.append(txt)
                if not experiences:
                    items = driver.find_elements(By.CSS_SELECTOR, "ul.pv-profile-section__section-info li")
                    for it in items[:3]:
                        experiences.append(it.text.strip().split("\n")[0])
            except Exception:
                pass
            data["experience"] = " | ".join(experiences)

            print(f"✅ Scraped (attempt {attempt}): {data.get('full_name')[:60] if data.get('full_name') else url}")
            return data

        except Exception as e:
            last_exception = e
            print(f"⚠️ Attempt {attempt} failed for {url}: {e}")
            # wait a bit longer before retrying
            time.sleep(3 + random.uniform(1.0, 3.0))
            continue

    # all retries failed
    data["error"] = str(last_exception)
    print(f"❌ All attempts failed for {url}. Raw saved at: {data.get('raw_html')}")
    return data


# ---------------- MAIN EXECUTION ----------------
def main():
    driver = create_driver(headless=False)
    logged_in = linkedin_login(driver)  # optional; continues if login fails

    # Load input URLs
    if not os.path.exists(INPUT_FILE):
        print(f"Input file {INPUT_FILE} not found. Create it and add one profile URL per line.")
        driver.quit()
        return

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        urls = [line.strip() for line in f if line.strip()]

    results = []
    for url in urls:
        try:
            profile_data = scrape_profile(driver, url)
            results.append(profile_data)
        except Exception as e:
            print("Unexpected error scraping:", e)
            results.append({"profile_url": url, "error": str(e)})
        sleep_time = random.uniform(6, 12)
        print(f"⏳ Waiting {sleep_time:.1f}s before next profile...\n")
        time.sleep(sleep_time)

    driver.quit()

    # Write to CSV
    fieldnames = [
        "profile_url",
        "scraped_at",
        "full_name",
        "headline",
        "location",
        "about",
        "experience",
        "contact_info",
        "contact_parsed",
        "raw_html",
        "error",
    ]
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            # JSON-serialize contact_info and parsed contact so it fits in CSV
            row = {
                "profile_url": r.get("profile_url"),
                "scraped_at": r.get("scraped_at"),
                "full_name": r.get("full_name"),
                "headline": r.get("headline"),
                "location": r.get("location"),
                "about": r.get("about"),
                "experience": r.get("experience"),
                "contact_info": json.dumps(r.get("contact_info", {}), ensure_ascii=False),
                "contact_parsed": json.dumps(r.get("contact_parsed", {}), ensure_ascii=False),
                "raw_html": r.get("raw_html"),
                "error": r.get("error"),
            }
            writer.writerow(row)

    print(f"📁 Scraping complete. Data saved to {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
