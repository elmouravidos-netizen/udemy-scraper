"""
Arabic SEO Content Enrichment  v1
Finds courses with content_status='pending' in Supabase, asks Gemini to
generate fully-Arabic SEO content grounded in the real Udemy data already
scraped, and writes the results back.
"""

import os
import json
import time
import requests

SUPABASE_URL   = os.environ["SUPABASE_URL"]
SUPABASE_KEY   = os.environ["SUPABASE_KEY"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

GEMINI_MODEL = "gemini-2.0-flash"
GEMINI_URL   = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
)

BATCH_LIMIT = 10  # keep small until you confirm your Gemini quota/tier

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "meta_title":         {"type": "string"},
        "meta_description":   {"type": "string"},
        "description_unique": {"type": "string"},
        "what_youll_learn": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 4, "maxItems": 6,
        },
        "faq": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "answer":   {"type": "string"},
                },
                "required": ["question", "answer"],
            },
            "minItems": 2, "maxItems": 3,
        },
    },
    "required": [
        "meta_title", "meta_description", "description_unique",
        "what_youll_learn", "faq",
    ],
}

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

المطلوب (أرجع JSON فقط حسب المخطط):
- meta_title: عنوان SEO عربي جذاب (50-60 حرف تقريباً)
- meta_description: وصف ميتا عربي (150-160 حرف)
- description_unique: فقرة عربية أصلية من جملتين إلى ثلاث جمل تشرح محتوى الدورة ولمن تناسب
- what_youll_learn: 4 إلى 6 نقاط عربية عن أهم ما سيتعلمه الطالب (استنتجها من العنوان والوصف، لا تختلق تفاصيل غير مذكورة)
- faq: سؤالين إلى ثلاثة أسئلة شائعة بصيغة عربية طبيعية مع إجابات مختصرة

مهم: لا تذكر أي محتوى عن الخمور أو لحم الخنزير أو أي محتوى غير لائق. حافظ على لغة عربية فصيحة واحترافية.
"""


class RateLimited(Exception):
    pass


def call_gemini(course, retries=3):
    payload = {
        "contents": [{"parts": [{"text": build_prompt(course)}]}],
        "generationConfig": {
            "response_mime_type": "application/json",
            "response_schema": RESPONSE_SCHEMA,
            "temperature": 0.6,
        },
    }
    for attempt in range(retries):
        resp = requests.post(GEMINI_URL, json=payload, timeout=30)
        if resp.status_code == 429:
            wait = 20 * (attempt + 1)
            print(f"    rate limited, waiting {wait}s (attempt {attempt+1}/{retries})")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        data = resp.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(text)
    raise RateLimited("still rate limited after retries")


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
    print("ARABIC SEO CONTENT ENRICHMENT")
    print("=" * 60)

    rows = fetch_pending()
    print(f"Found {len(rows)} pending courses (batch limit {BATCH_LIMIT})")

    ok, failed = 0, 0
    for i, course in enumerate(rows, 1):
        print(f"[{i}/{len(rows)}] {course['title'][:60]}")
        try:
            content = call_gemini(course)
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
        except RateLimited as e:
            print(f"  skipped (still rate limited): {e} — left as pending for next run")
            failed += 1
        except Exception as e:
            print(f"  failed: {e}")
            try:
                update_course(course["id"], {"content_status": "failed"})
            except Exception:
                pass
            failed += 1
        time.sleep(4)  # slower pace to respect free-tier RPM limits

    print("\n" + "=" * 60)
    print(f"Done. Generated: {ok} | Failed: {failed} | Total: {len(rows)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
