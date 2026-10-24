import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import webbrowser
import html
import re
import os

# =====================================================================
# 1. EVERGREEN RSS ARCHITECTURE (Direct Editorial Feeds + Topic Feeds)
# =====================================================================
FEEDS = {
    "💡 Editorials, Explainers & Policy (GD Source)": [
        ("Indian Express - Explained", "https://indianexpress.com/section/explained/feed/"),
        ("The Hindu - Opinion/Editorial", "https://www.thehindu.com/opinion/editorial/feeder/default.rss"),
        ("The Hindu - Lead Columns", "https://www.thehindu.com/opinion/lead/feeder/default.rss"),
    ],
    "🇮🇳 National & Governance": [
        ("The Hindu - National", "https://www.thehindu.com/news/national/feeder/default.rss"),
        ("Indian Express - Front Page", "https://indianexpress.com/print/front-page/feed/"),
        ("Google News - India Top Stories", "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en")
    ],
    "🌍 World & Geopolitics": [
        ("BBC News - World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
        ("The Hindu - International", "https://www.thehindu.com/news/international/feeder/default.rss"),
        ("Google News - World", "https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-IN&gl=IN&ceid=IN:en")
    ],
    "📈 Economy, Business & Development": [
        ("LiveMint - News", "https://www.livemint.com/rss/news"),
        ("LiveMint - Markets", "https://www.livemint.com/rss/markets"),
        ("The Hindu - Business", "https://www.thehindu.com/business/feeder/default.rss"),
        ("Google News - Economy", "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=en-IN&gl=IN&ceid=IN:en")
    ],
    "🎖️ Defence & National Security (Priority)": [
        ("India Defence Aggregator", "https://news.google.com/rss/search?q=%22Ministry+of+Defence%22+OR+%22Armed+Forces%22+OR+%22Indian+Army%22+OR+%22Indian+Navy%22+OR+%22Indian+Air+Force%22+OR+DRDO&hl=en-IN&gl=IN&ceid=IN:en"),
        ("Global Defense & Security", "https://news.google.com/rss/search?q=Military+OR+Defense+OR+Aerospace+OR+Maritime+Security+OR+Naval&hl=en-US&gl=US&ceid=US:en")
    ],
    "🔬 Science, Space & Technology (Priority)": [
        ("The Hindu - Sci-Tech", "https://www.thehindu.com/sci-tech/feeder/default.rss"),
        ("BBC - Science & Environment", "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml"),
        ("Ars Technica - Tech & Science", "https://feeds.arstechnica.com/arstechnica/index"),
        ("LiveMint - Technology", "https://www.livemint.com/rss/technology"),
        ("Google News - Science & Tech", "https://news.google.com/rss/headlines/section/topic/SCITECH?hl=en-IN&gl=IN&ceid=IN:en")
    ],
    "🏆 Sports, Environment & Society": [
        ("The Hindu - Environment", "https://www.thehindu.com/sci-tech/energy-and-environment/feeder/default.rss"),
        ("Indian Express - Sports", "https://indianexpress.com/section/sports/feed/"),
        ("The Hindu - Sport", "https://www.thehindu.com/sport/feeder/default.rss")
    ]
}

PRIORITY_DOMAINS = [
    "defence", "defense", "military", "army", "navy", "air force", "security",
    "missile", "aerospace", "maritime", "border", "strategic", "space", "satellite",
    "research", "science", "technology", "artificial intelligence", "quantum",
    "cyber", "nuclear", "innovation", "robotics", "semiconductor", "biotech"
]

GD_THEMES = {
    "🏛️ Governance & Policy": [
        "policy", "reform", "constitution", "supreme court", "parliament", "legislation",
        "governance", "federalism", "judiciary", "democracy", "welfare", "regulation",
        "bill", "commission", "rights", "transparency", "administration", "census", "panchayat"
    ],
    "👥 Social & Demographics": [
        "education", "healthcare", "women", "gender", "youth", "employment", "poverty",
        "inequality", "rural", "urbanization", "literacy", "population", "society",
        "skill", "workforce", "nutrition", "mental health", "social media", "migration"
    ],
    "🤖 Science, Tech & Ethics": [
        "artificial intelligence", "privacy", "cybersecurity", "data protection", "automation",
        "deepfake", "biotechnology", "space exploration", "digital divide", "innovation",
        "ethics", "research", "quantum", "semiconductor", "internet", "algorithm"
    ],
    "🌱 Environment & Sustainability": [
        "climate change", "renewable", "sustainability", "emissions", "green energy",
        "biodiversity", "conservation", "water crisis", "pollution", "electric vehicles",
        "solar", "disaster", "ecology", "deforestation", "net zero", "glacier"
    ],
    "🌐 Economy & Geostrategy": [
        "geopolitics", "diplomacy", "bilateral", "supply chain", "inflation", "trade",
        "manufacturing", "self-reliance", "indigenisation", "global south", "multilateral",
        "sanctions", "maritime security", "strategic autonomy", "gdp", "infrastructure"
    ]
}

GD_SIGNAL_WORDS = [
    "explained", "why", "how", "impact", "challenge", "future", "crisis", "debate",
    "reform", "policy", "need", "growth", "transition", "dilemma", "shift", "role",
    "global", "india's", "versus", "beyond", "lesson", "framework", "roadmap"
]

MAX_AGE_HOURS = 36
ITEMS_PER_SOURCE = 6
MAX_GD_TOPICS = 8
IST_OFFSET = timezone(timedelta(hours=5, minutes=30))


# =====================================================================
# 2. PARSING & SCORING UTILITIES
# =====================================================================
def clean_text(raw_text):
    if not raw_text:
        return ""
    text = html.unescape(raw_text)
    text = re.sub(r'<[^>]+>', '', text)
    return re.sub(r'\s+', ' ', text).strip()

def split_google_title(title, default_source):
    if "Google" in default_source and " - " in title:
        parts = title.rsplit(" - ", 1)
        return parts[0].strip(), parts[1].strip()
    return title, default_source

def is_priority_topic(title, summary):
    combined = f"{title} {summary}".lower()
    for term in PRIORITY_DOMAINS:
        if re.search(rf'\b{re.escape(term)}\b', combined):
            return True
    return False

def evaluate_gd_potential(title, summary, category, source):
    combined = f"{title} {summary}".lower()
    matched_themes = []
    score = 0

    for theme_name, keywords in GD_THEMES.items():
        hits = sum(1 for kw in keywords if re.search(rf'\b{re.escape(kw)}\b', combined))
        if hits > 0:
            matched_themes.append(theme_name)
            score += hits * 2

    if "GD Source" in category or "Explained" in source or "Editorial" in source:
        score += 5

    signal_hits = sum(1 for sw in GD_SIGNAL_WORDS if re.search(rf'\b{re.escape(sw)}\b', combined))
    score += signal_hits

    if "Sports" in category and not matched_themes:
        score = 0

    angle = "Define issue → Key stakeholders → Pros/Cons → Balanced way forward"
    if "🏛️ Governance & Policy" in matched_themes:
        angle = "Constitutional/Policy context → Implementation challenges → Reforms needed"
    elif "👥 Social & Demographics" in matched_themes:
        angle = "Ground reality → Socio-economic impact → Inclusive solutions & awareness"
    elif "🤖 Science, Tech & Ethics" in matched_themes:
        angle = "Technological breakthrough → Utility vs. Ethical/Security risks → Regulation"
    elif "🌱 Environment & Sustainability" in matched_themes:
        angle = "Development vs. Ecology dilemma → Long-term climate impact → Sustainable path"
    elif "🌐 Economy & Geostrategy" in matched_themes:
        angle = "Global/Domestic drivers → Strategic & economic impact on India → Future outlook"

    return score, matched_themes[:2], angle

def parse_date(date_str):
    if not date_str:
        return datetime.now(timezone.utc)
    try:
        dt = parsedate_to_datetime(date_str)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        try:
            return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        except Exception:
            return datetime.now(timezone.utc)

def dedup_signature(title):
    cleaned = re.sub(r'[^a-zA-Z0-9\s]', '', title.lower())
    words = [w for w in cleaned.split() if len(w) > 3]
    return " ".join(words[:6])


# =====================================================================
# 3. UNIVERSAL RSS & ATOM FETCHER
# =====================================================================
def fetch_feed(category, source_name, url):
    articles = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=MAX_AGE_HOURS)
    
    try:
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            root = ET.fromstring(resp.read())
            
            items = root.findall('.//item')
            if not items:
                items = root.findall('.//{http://www.w3.org/2005/Atom}entry')
                
            for item in items[:ITEMS_PER_SOURCE]:
                title_el = item.find('title')
                if title_el is None:
                    title_el = item.find('{http://www.w3.org/2005/Atom}title')
                raw_title = clean_text(title_el.text if title_el is not None else "Untitled")
                
                link_el = item.find('link')
                link = "#"
                if link_el is not None:
                    link = link_el.text or link_el.attrib.get('href', '#')
                else:
                    atom_link = item.find('{http://www.w3.org/2005/Atom}link')
                    if atom_link is not None:
                        link = atom_link.attrib.get('href', '#')
                        
                date_el = item.find('pubDate')
                if date_el is None:
                    date_el = item.find('{http://purl.org/dc/elements/1.1/}date')
                if date_el is None:
                    date_el = item.find('{http://www.w3.org/2005/Atom}published')
                pub_dt = parse_date(date_el.text if date_el is not None else "")
                
                if pub_dt < cutoff:
                    continue
                    
                desc_el = item.find('description')
                if desc_el is None:
                    desc_el = item.find('{http://www.w3.org/2005/Atom}summary')
                summary = clean_text(desc_el.text if desc_el is not None else "")
                if len(summary) > 220:
                    summary = summary[:217] + "..."
                    
                clean_title, publisher = split_google_title(raw_title, source_name)
                priority = is_priority_topic(clean_title, summary)
                gd_score, gd_themes, gd_angle = evaluate_gd_potential(
                    clean_title, summary, category, publisher
                )
                
                articles.append({
                    'category': category,
                    'title': clean_title,
                    'summary': summary if summary and summary != clean_title else "",
                    'source': publisher,
                    'link': link.strip(),
                    'datetime': pub_dt,
                    'time_str': pub_dt.astimezone(IST_OFFSET).strftime("%d %b, %I:%M %p IST"),
                    'is_priority': priority,
                    'gd_score': gd_score,
                    'gd_themes': gd_themes,
                    'gd_angle': gd_angle,
                    'sig': dedup_signature(clean_title)
                })
    except Exception as e:
        print(f"⚠️ Skipped {source_name} ({e})")
        
    return articles


def aggregate_all():
    structured = {cat: [] for cat in FEEDS}
    all_unique_articles = []
    seen = set()
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [
            executor.submit(fetch_feed, cat, src_name, url)
            for cat, src_list in FEEDS.items()
            for src_name, url in src_list
        ]
        for future in as_completed(futures):
            for art in future.result():
                if art['sig'] and art['sig'] not in seen:
                    seen.add(art['sig'])
                    structured[art['category']].append(art)
                    all_unique_articles.append(art)
                    
    for cat in structured:
        structured[cat].sort(key=lambda x: (x['is_priority'], x['datetime']), reverse=True)
        
    gd_candidates = [a for a in all_unique_articles if a['gd_score'] >= 4 and a['gd_themes']]
    gd_candidates.sort(key=lambda x: (x['gd_score'], x['datetime']), reverse=True)
    
    return structured, gd_candidates[:MAX_GD_TOPICS]


# =====================================================================
# 4. EXPORT TO GITHUB PAGES (index.html) & README.md
# =====================================================================
def generate_outputs(news_data, gd_topics):
    now_ist = datetime.now(IST_OFFSET)
    today = now_ist.strftime("%d %b %Y")
    updated_time = now_ist.strftime("%d %b %Y, %I:%M %p IST")
    
    md_file = "README.md"
    html_file = "index.html"
    total = sum(len(v) for v in news_data.values())
    
    # 1. Write Markdown (README.md)
    with open(md_file, 'w', encoding='utf-8') as f:
        f.write(f"# 🗞️ Daily News & GD Digest ({today})\n")
        f.write(f"*Last Updated: {updated_time} | {total} top stories + {len(gd_topics)} GD & Lecturette topics.*\n\n---\n\n")
        f.write(f"## 🎙️ Top Group Discussion (GD) & Lecturette Topics ({len(gd_topics)})\n\n")
        for idx, art in enumerate(gd_topics, 1):
            themes_str = " | ".join([f"`{t}`" for t in art['gd_themes']])
            f.write(f"{idx}. **{art['title']}** ({themes_str})  \n")
            if art['summary'] and "Google" not in art['source']:
                f.write(f"   > {art['summary']}  \n")
            f.write(f"   *🧭 Speaking Flow:* `{art['gd_angle']}` | [Read]({art['link']})\n\n")
        f.write("---\n\n")
        for category, items in news_data.items():
            f.write(f"## {category} ({len(items)})\n\n")
            for art in items:
                badge = "⭐ **[PRIORITY]** " if art['is_priority'] and "Priority" not in category else ""
                f.write(f"- {badge}**{art['title']}** (*{art['source']}*) - [Read]({art['link']})\n")
            f.write("\n")

    # 2. Write Mobile-First Progressive Web App (index.html)
    html_out = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <meta name="theme-color" content="#0f172a">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <title>Daily Brief & GD Digest</title>
    <style>
        :root {{ --bg: #0f172a; --card: #1e293b; --text: #f8fafc; --muted: #94a3b8; --accent: #38bdf8; --gold: #f59e0b; --purple: #c084fc; }}
        * {{ box-sizing: border-box; -webkit-tap-highlight-color: transparent; }}
        body {{ font-family: system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--text); max-width: 820px; margin: 0 auto; padding: 0 14px 60px; line-height: 1.45; }}
        
        .sticky-top {{ position: sticky; top: 0; background: rgba(15, 23, 42, 0.95); backdrop-filter: blur(8px); padding: 12px 0 8px; z-index: 100; border-bottom: 1px solid #334155; }}
        .top-row {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; flex-wrap: wrap; gap: 6px; }}
        h1 {{ margin: 0; font-size: 1.3rem; letter-spacing: -0.5px; }}
        .date-badge {{ font-size: 0.75rem; color: var(--muted); background: var(--card); padding: 4px 8px; border-radius: 6px; border: 1px solid #334155; }}
        
        .search-box {{ width: 100%; padding: 10px 14px; border-radius: 8px; border: 1px solid #334155; background: var(--card); color: #fff; font-size: 0.92rem; margin-bottom: 10px; outline: none; }}
        .search-box:focus {{ border-color: var(--accent); }}
        
        .nav {{ display: flex; gap: 8px; overflow-x: auto; padding-bottom: 6px; scrollbar-width: none; }}
        .nav::-webkit-scrollbar {{ display: none; }}
        .tab-btn {{ flex-shrink: 0; background: var(--card); color: var(--muted); padding: 7px 14px; border-radius: 20px; border: 1px solid #334155; font-size: 0.8rem; font-weight: 600; cursor: pointer; }}
        .tab-btn.active {{ background: var(--accent); color: #000; border-color: var(--accent); }}
        .tab-btn.gd-pill.active {{ background: var(--purple); color: #000; border-color: var(--purple); }}

        h2 {{ color: var(--accent); font-size: 1.15rem; margin: 24px 0 12px; }}
        h2.gd-header {{ color: var(--purple); }}
        .grid {{ display: flex; flex-direction: column; gap: 12px; }}
        
        .card {{ background: var(--card); padding: 14px; border-radius: 10px; border-left: 4px solid #475569; }}
        .card.priority {{ border-left-color: var(--gold); }}
        .card.gd {{ background: #1e1b4b; border-left-color: var(--purple); }}
        
        .title {{ color: #fff; font-weight: 600; font-size: 1rem; text-decoration: none; display: block; margin-bottom: 6px; }}
        .title:hover {{ color: var(--accent); }}
        .summary {{ color: #cbd5e1; font-size: 0.88rem; margin: 6px 0; }}
        .angle {{ background: rgba(192, 132, 252, 0.14); color: #e9d5ff; font-size: 0.8rem; padding: 8px 10px; border-radius: 6px; margin: 8px 0; border-left: 2px solid var(--purple); }}
        
        .meta {{ font-size: 0.75rem; color: var(--muted); display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 6px; margin-top: 8px; }}
        .tags-wrap {{ display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }}
        .badge {{ background: var(--gold); color: #000; font-weight: 700; font-size: 0.68rem; padding: 2px 6px; border-radius: 4px; }}
        .theme-tag {{ background: #4c1d95; color: #f3e8ff; font-weight: 600; font-size: 0.7rem; padding: 2px 7px; border-radius: 4px; }}
        .src {{ color: var(--accent); font-weight: 600; }}
        .share-btn {{ background: transparent; border: 1px solid #475569; color: var(--muted); border-radius: 4px; padding: 3px 8px; font-size: 0.72rem; cursor: pointer; }}
    </style>
</head>
<body>
    <div class="sticky-top">
        <div class="top-row">
            <h1>🗞️ Daily Brief & GD</h1>
            <span class="date-badge">{updated_time} &bull; {total} stories</span>
        </div>
        <input type="text" id="searchInput" class="search-box" placeholder="🔍 Search topics, keywords, DRDO, ISRO, AI, policy..." oninput="filterArticles()">
        <div class="nav">
            <button class="tab-btn active" onclick="filterCategory('all', this)">All Sections</button>
            <button class="tab-btn gd-pill" onclick="filterCategory('sec-gd', this)">🎙️ GD Topics ({len(gd_topics)})</button>
            {"".join([f'<button class="tab-btn" onclick="filterCategory(\'sec-{i}\', this)">{html.escape(cat.split()[0] + " " + cat.split()[1])}</button>' for i, cat in enumerate(news_data.keys())])}
        </div>
    </div>

    <div id="sec-gd" class="news-section">
        <h2 class="gd-header">🎙️ Top GD & Lecturette Topics ({len(gd_topics)})</h2>
        <div class="grid">
"""
    for art in gd_topics:
        theme_badges = "".join([f'<span class="theme-tag">{html.escape(t)}</span>' for t in art['gd_themes']])
        sum_html = f'<div class="summary">{html.escape(art["summary"])}</div>' if art['summary'] and "Google" not in art['source'] else ''
        safe_js_title = html.escape(art['title']).replace("'", "\\'")
        html_out += f"""            <div class="card gd searchable">
                <a class="title" href="{html.escape(art['link'])}" target="_blank" rel="noopener">{html.escape(art['title'])}</a>
                {sum_html}
                <div class="angle"><strong>🧭 Speaking Flow:</strong> {html.escape(art['gd_angle'])}</div>
                <div class="meta">
                    <div class="tags-wrap">{theme_badges} <span class="src">{html.escape(art['source'])}</span> &bull; <span>{art['time_str']}</span></div>
                    <button class="share-btn" onclick="shareItem('{safe_js_title}', '{html.escape(art['link'])}')">Share ↗</button>
                </div>
            </div>\n"""
    html_out += '        </div>\n    </div>\n'

    for i, (category, items) in enumerate(news_data.items()):
        html_out += f'    <div id="sec-{i}" class="news-section">\n        <h2>{html.escape(category)} ({len(items)})</h2>\n        <div class="grid">\n'
        for art in items:
            is_prio = art['is_priority'] and "Priority" not in category
            card_cls = "card priority searchable" if is_prio else "card searchable"
            badge_html = '<span class="badge">★ PRIORITY</span>' if is_prio else ''
            theme_badges = "".join([f'<span class="theme-tag">{html.escape(t)}</span>' for t in art['gd_themes']])
            sum_html = f'<div class="summary">{html.escape(art["summary"])}</div>' if art['summary'] and "Google" not in art['source'] else ''
            safe_js_title = html.escape(art['title']).replace("'", "\\'")
            
            html_out += f"""            <div class="{card_cls}">
                <a class="title" href="{html.escape(art['link'])}" target="_blank" rel="noopener">{html.escape(art['title'])}</a>
                {sum_html}
                <div class="meta">
                    <div class="tags-wrap">{badge_html} {theme_badges} <span class="src">{html.escape(art['source'])}</span> &bull; <span>{art['time_str']}</span></div>
                    <button class="share-btn" onclick="shareItem('{safe_js_title}', '{html.escape(art['link'])}')">Share ↗</button>
                </div>
            </div>\n"""
        html_out += '        </div>\n    </div>\n'

    html_out += """
    <script>
        function filterCategory(secId, btn) {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            document.querySelectorAll('.news-section').forEach(sec => {
                sec.style.display = (secId === 'all' || sec.id === secId) ? 'block' : 'none';
            });
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }
        function filterArticles() {
            const q = document.getElementById('searchInput').value.toLowerCase();
            document.querySelectorAll('.searchable').forEach(card => {
                card.style.display = card.innerText.toLowerCase().includes(q) ? 'block' : 'none';
            });
        }
        function shareItem(title, url) {
            if (navigator.share) {
                navigator.share({ title: title, text: title, url: url });
            } else {
                navigator.clipboard.writeText(title + " - " + url);
                alert("Link copied to clipboard!");
            }
        }
    </script>
</body>
</html>"""
    with open(html_file, 'w', encoding='utf-8') as f:
        f.write(html_out)
        
    return md_file, html_file


if __name__ == "__main__":
    print("🌐 Pulling live feeds & building Mobile Web App...")
    start = datetime.now()
    news_by_cat, top_gd_topics = aggregate_all()
    md_path, html_path = generate_outputs(news_by_cat, top_gd_topics)
    print(f"✅ Completed in {(datetime.now() - start).total_seconds():.2f}s!")
    print(f"📄 Markdown File : {os.path.abspath(md_path)}")
    print(f"🖥️ HTML Web App  : {os.path.abspath(html_path)}")
    
    # Auto-open in browser only when run locally on your laptop/PC
    if not os.environ.get("GITHUB_ACTIONS"):
        webbrowser.open(f"file://{os.path.abspath(html_path)}")
