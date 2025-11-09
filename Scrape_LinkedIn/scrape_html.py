#!/usr/bin/env python3
"""
Parse an HTML file (e.g., LinkedIn contact modal) and extract:
 - name
 - emails
 - phone numbers
 - social/profile links (LinkedIn, GitHub, etc.)
 - other contact text snippets

Usage (CLI):
    python parse_contact_modal.py --input path/to/modal.html --output out.json

Usage (Programmatic):
    from parse_contact_modal import parse_contact_html
    result = parse_contact_html(filepath="raw_html/contact_modal_20251108_154227.html")
    # or
    html_content = open("sample.html").read()
    result = parse_contact_html(content=html_content)
"""

import argparse
import json
import os
import re
from urllib.parse import urlparse
from bs4 import BeautifulSoup

# ------------------- Regex Patterns -------------------
PHONE_RE = re.compile(r"(?:\+?\d{1,3}[\s\-\.])?(?:\(?\d{2,4}\)?[\s\-\.])?(?:\d[\d\-\s\(\)]{5,}\d)")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
URL_RE = re.compile(r"https?://[^\s'\"<>]+")

# ------------------- Known Social Domains -------------------
SOCIAL_PATTERNS = {
    "linkedin": ["linkedin.com/in", "linkedin.com/pub", "linkedin.com/profile"],
    "github": ["github.com/"],
    "twitter": ["x.com/", "twitter.com/"],
    "medium": ["medium.com/"],
    "portfolio": [".github.io", "dev.to", "behance.net", "dribbble.com", "wordpress.com", "netlify.app", "vercel.app"],
    "google_scholar": ["scholar.google.com", "citations.google.com"],
    "researchgate": ["researchgate.net"],
    "orcid": ["orcid.org"],
    "scholar": ["scholar.google"],
    "stack_overflow": ["stackoverflow.com/users"],
    "personal_site": [],  # fallback: domain looks like personal site
}


def classify_link(href: str):
    href_lower = href.lower()
    for label, patterns in SOCIAL_PATTERNS.items():
        for p in patterns:
            if p in href_lower:
                return label
    parsed = urlparse(href_lower)
    domain = parsed.netloc
    if domain and any(domain.endswith(t) for t in (".io", ".me", ".dev", ".app", ".site", ".tech")):
        return "personal_site"
    return "website"


def extract_from_scripts(text: str):
    """Find emails, phones, and URLs in embedded JSON or JS."""
    emails = EMAIL_RE.findall(text)
    phones = PHONE_RE.findall(text)
    urls = URL_RE.findall(text)
    return emails, phones, urls


def get_candidate_name(soup: BeautifulSoup):
    """Heuristic for name extraction."""
    # 1. h1 tag
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        return h1.get_text(strip=True)

    # 2. meta property og:title
    og = soup.find("meta", {"property": "og:title"})
    if og and og.get("content"):
        return og.get("content").strip()

    # 3. <title>
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
        candidate = re.split(r"[\|\-\–\,\|]", title)[0].strip()
        if candidate:
            return candidate

    # 4. fallback heuristic
    candidates = []
    for tag in ["div", "span", "strong", "p"]:
        for el in soup.find_all(tag, recursive=True):
            txt = (el.get_text(" ", strip=True) or "").strip()
            if 2 < len(txt) <= 60:
                lowered = txt.lower()
                if any(excl in lowered for excl in ("contact", "email", "phone", "website", "birthday", "edit contact info")):
                    continue
                if re.match(r"^[A-Za-z][A-Za-z\.\'\- ]+$", txt) and " " in txt:
                    candidates.append(txt)
    if candidates:
        return sorted(candidates, key=len)[0]
    return ""


# ------------------- Main Parsing Function -------------------
def parse_contact_html(filepath: str = None, content: str = None):
    """
    Parse LinkedIn contact modal HTML.
    Args:
        filepath (str): path to the HTML file
        content (str): raw HTML string
    Returns:
        dict: extracted contact info
    """
    if not filepath and not content:
        raise ValueError("Either 'filepath' or 'content' must be provided.")

    if filepath:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as fh:
            raw = fh.read()
    else:
        raw = content

    soup = BeautifulSoup(raw, "html.parser")

    result = {
        "name": get_candidate_name(soup),
        "emails": [],
        "phones": [],
        "links": [],
        "other_texts": [],
        "source_file": filepath or "<from_content>",
    }

    # --- Anchors ---
    anchors = soup.find_all("a", href=True)
    seen_hrefs = set()
    for a in anchors:
        href = a.get("href").strip()
        text = a.get_text(" ", strip=True)
        if href.startswith("mailto:"):
            email = href.split("mailto:")[1].split("?")[0]
            if EMAIL_RE.match(email):
                result["emails"].append(email)
        elif href.startswith("tel:"):
            ph = re.sub(r"\s+", " ", href.split("tel:")[-1]).strip()
            result["phones"].append(ph)
        elif href.startswith("http") or href.startswith("//"):
            if href.startswith("//"):
                href = "https:" + href
            if href not in seen_hrefs:
                seen_hrefs.add(href)
                result["links"].append({
                    "href": href,
                    "text": text,
                    "type": classify_link(href)
                })

    # --- Text Scanning ---
    visible_texts = []
    for el in soup.find_all(string=True):
        parent = el.parent.name if el.parent else ""
        if parent in ("script", "style", "meta", "link"):
            continue
        txt = el.strip()
        if txt:
            visible_texts.append(txt)
    visible_text = " ".join(visible_texts)

    # Emails / Phones / URLs
    result["emails"] = sorted(set(result["emails"] + EMAIL_RE.findall(visible_text)))
    phones = [re.sub(r"\s+", " ", ph).strip() for ph in PHONE_RE.findall(visible_text)]
    result["phones"] = sorted(set([p for p in phones if len(re.sub(r"\D", "", p)) >= 7]))

    for u in URL_RE.findall(raw):
        if u.startswith("//"):
            u = "https:" + u
        if all(u != l["href"] for l in result["links"]):
            result["links"].append({"href": u, "text": "", "type": classify_link(u)})

    # --- Script Tags ---
    for script in soup.find_all("script"):
        if not script.string:
            continue
        es, ps, us = extract_from_scripts(script.string)
        result["emails"].extend(es)
        result["phones"].extend(ps)
        for u in us:
            if u.startswith("//"):
                u = "https:" + u
            if all(u != l["href"] for l in result["links"]):
                result["links"].append({"href": u, "text": "", "type": classify_link(u)})

    # Deduplicate
    result["emails"] = sorted(set(result["emails"]))
    result["phones"] = sorted(set([re.sub(r"\s+", " ", p).strip() for p in result["phones"]]))

    # Social classification summary
    social = {}
    for link in result["links"]:
        social.setdefault(link["type"], []).append(link["href"])
    result["social"] = social

    return result


# ------------------- CLI Entry -------------------
def main():
    parser = argparse.ArgumentParser(description="Parse contact modal HTML")
    parser.add_argument("--input", "-i", required=True, help="Path to HTML file")
    parser.add_argument("--output", "-o", default="parsed_contact.json", help="Output JSON file")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print("❌ Input file not found:", args.input)
        return

    data = parse_contact_html(filepath=args.input)

    print("\n📄 Parsed Contact Info:")
    print("Name:", data.get("name"))
    print("Emails:", data.get("emails"))
    print("Phones:", data.get("phones"))
    print("Social Profiles:")
    for k, v in data.get("social", {}).items():
        print(f"  - {k}: {v}")

    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    print(f"\n✅ Saved to {args.output}")


if __name__ == "__main__":
    main()
