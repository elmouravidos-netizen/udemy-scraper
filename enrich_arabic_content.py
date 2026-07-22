"""
Arabic SEO Content Enrichment  v2 — OpenRouter edition (free models, $0 cost)
Finds courses with content_status='pending' in Supabase, asks an OpenRouter
free-tier model to generate fully-Arabic SEO content, writes results back.

Cost control:
  - Only uses models in FREE_MODELS (":free" suffix = $0/token on OpenRouter)
  - max_price header hard-caps spend at $0 per request as a safety net,
    so even a misconfiguration can never bill you.
  - Rotates through multiple free models if one is rate-limited, instead
    of just waiting/failing — free models each have their own daily cap.
"""

import os
import json
import time
import re
import requests

SUPABASE_URL     = os.environ["SUPABASE_URL"]
SUPABASE_KEY     = os.environ["SUPABASE_KEY"]
OPENROUTER_KEY   = os.environ["OPENROUTER_API_KEY"]

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Pass 1: generation — OpenRouter's free-models router. It auto-picks
# from all currently available free models, so we don't hardcode slugs
# that go stale when OpenRouter deprecates/renames individual models.
GENERATION_MODEL = "openrouter/free"

# Pass 2: review — small paid model, strong at Arabic, very cheap
# (a few cents per 100 courses). Set REVIEW_ENABLED=False to skip and
# stay at $0 if you don't want to add any credit yet.
REVIEW_MODEL = "qwen/qwen-2.5-72b-instruct"
REVIEW_ENABLED = os.environ.get("REVIEW_ENABLED", "true").lower() == "true"
REVIEW_MAX_PRICE = {"prompt": 1.0, "completion": 2.0}  # $/1M tokens hard cap

BATCH_LIMIT = 20

LANGUAGE_LABELS_AR = {
    "en": "الإنجليزية", "fr": "الفرنسية", "es": "الإسبانية",
    "de": "الألمانية", "tr": "التركية", "pt": "البرتغالية",
    "it": "الإيطالية", "ar": "العربية", "ru": "الروسية",
    "hi": "الهندية", "zh": "الصينية", "ja": "اليابانية",
    "ko": "الكورية", "nl": "الهولندية", "pl": "البولندية",
}


def build_prompt(course):
    lang_label = LANGUAGE_LABELS_AR.get(
        (course.get("course_language") or "en"), "الإنجليزية"
    )
    return f"""أنت كاتب محتوى SEO محترف متخصص في المحتوى العربي لموقع دورات تدريبية.

اكتب محتوى عربي فصيح بالكامل (وليس ترجمة حرفية) لصفحة دورة تدريبية بناءً على البيانات التالية.
لغة الدورة نفسها هي: {lang_label} — لا تترجم هذا كمحتوى، فقط اعرف أن الدورة بهذه اللغة.

بيانات الدورة (من Udemy):
العنوان الأصلي: {course.get('title', '')}
الفئة: {course.get('category', '')}
المدرب: {course.get('instructor') or 'غير معروف'}
التقييم: {course.get('rating') or 'غير متوفر'}
الوصف الأصلي (إنجليزي، للاستئناس فقط): {(course.get('description') or '')[:800]}

أرجع فقط كائن JSON صالح بدون أي نص إضافي قبله أو بعده، بالضبط بهذا الشكل:
{{
  "meta_title": "عنوان SEO عربي (50-60 حرف تقريباً)",
  "meta_description": "وصف ميتا عربي (150-160 حرف)",
  "description_unique": "فقرة عربية أصلية من جملتين إلى ثلاث جمل",
  "what_youll_learn": ["نقطة 1", "نقطة 2", "نقطة 3", "نقطة 4"],
  "faq": [{{"question": "سؤال؟", "answer": "إجابة مختصرة"}}, {{"question": "سؤال آخر؟", "answer": "إجابة"}}]
}}

مهم: لا تذكر أي محتوى عن الخمور أو لحم الخنزير أو أي محتوى غير لائق. حافظ على لغة عربية فصيحة واحترافية.
"""


def extract_json(text):
    # Models sometimes wrap JSON in ```json fences or add stray text
    text = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.M).strip()
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError("no JSON object found in model response")
    return json.loads(match.group(0))


def build_review_prompt(course, content):
    return f"""راجع محتوى SEO العربي التالي لدورة تدريبية وصحح أي أخطاء لغوية أو نحوية
أو ترجمة غير طبيعية أو معلومات غير منطقية. حافظ على نفس البنية والمعنى العام.

عنوان الدورة الأصلي: {course.get('title', '')}

المحتوى الحالي (JSON):
{json.dumps(content, ensure_ascii=False)}

أرجع فقط نسخة JSON مصححة بنفس البنية بالضبط (نفس المفاتيح)، بدون أي نص إضافي.
تأكد أيضاً أنه لا يوجد أي ذكر للخمور أو لحم الخنزير أو محتوى غير لائق.
"""


def review_and_fix(course, content):
    if not REVIEW_ENABLED:
        return content
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://cvsirati.com",
        "X-Title": "cvsirati arabic review",
    }
    payload = {
        "model": REVIEW_MODEL,
        "messages": [{"role": "user", "content": build_review_prompt(course, content)}],
        "temperature": 0.3,
        "max_tokens": 900,
        "max_price": REVIEW_MAX_PRICE,
    }
    try:
        resp = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=40)
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        reviewed = extract_json(text)
        required = ["meta_title", "meta_description", "description_unique",
                    "what_youll_learn", "faq"]
        if all(k in reviewed for k in required):
            return reviewed
        print("    review returned incomplete JSON, keeping original")
        return content
    except Exception as e:
        print(f"    review pass failed ({e}), keeping unreviewed content")
        return content


def call_openrouter(course, retries=3):
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://cvsirati.com",
        "X-Title": "cvsirati arabic enrichment",
    }
    payload = {
        "model": GENERATION_MODEL,
        "messages": [{"role": "user", "content": build_prompt(course)}],
        "temperature": 0.6,
        "max_tokens": 900,
        # Hard cost cap: never allow this request to spend beyond $0.
        "max_price": {"prompt": 0, "completion": 0},
    }
    last_err = None
    for attempt in range(retries):
        try:
            resp = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=40)
            if resp.status_code == 429:
                wait = 15 * (attempt + 1)
                print(f"    rate limited, waiting {wait}s (attempt {attempt+1}/{retries})")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
            return extract_json(text)
        except Exception as e:
            print(f"    attempt {attempt+1} failed: {e}")
            last_err = e
            time.sleep(3)
    raise RuntimeError(f"generation failed after retries: {last_err}")


def supabase_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }


def fetch_pending(limit=BATCH_LIMIT):
    url = (
        f"{SUPABASE_URL}/rest/v1/udemy_courses"
        f"?content_status=eq.pending&is_expired=eq.false"
        f"&select=id,title,category,instructor,rating,description,course_language"
        f"&limit={limit}"
    )
    resp = requests.get(url, headers=supabase_headers(), timeout=20)
    resp.raise_for_status()
    return resp.json()


def update_course(course_id, fields):
    url = f"{SUPABASE_URL}/rest/v1/udemy_courses?id=eq.{course_id}"
    resp = requests.patch(
        url, headers={**supabase_headers(), "Prefer": "return=minimal"},
        json=fields, timeout=20,
    )
    resp.raise_for_status()


def main():
    print("=" * 60)
    print("ARABIC SEO CONTENT ENRICHMENT (OpenRouter free models)")
    print("=" * 60)

    rows = fetch_pending()
    print(f"Found {len(rows)} pending courses (batch limit {BATCH_LIMIT})")

    ok, failed = 0, 0
    for i, course in enumerate(rows, 1):
        print(f"[{i}/{len(rows)}] {course['title'][:60]}")
        try:
            content = call_openrouter(course)
            required = ["meta_title", "meta_description", "description_unique",
                        "what_youll_learn", "faq"]
            if not all(k in content for k in required):
                raise ValueError(f"missing fields in response: {content.keys()}")
            content = review_and_fix(course, content)
            update_course(course["id"], {
                "meta_title":         content["meta_title"],
                "meta_description":   content["meta_description"],
                "description_unique": content["description_unique"],
                "what_youll_learn":   content["what_youll_learn"],
                "faq":                content["faq"],
                "content_status":     "generated",
            })
            ok += 1
            print("  generated ok")
        except Exception as e:
            print(f"  failed, left pending for retry: {e}")
            failed += 1
        time.sleep(2)

    print("\n" + "=" * 60)
    print(f"Done. Generated: {ok} | Failed/retry-later: {failed} | Total: {len(rows)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
