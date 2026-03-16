import feedparser, pytz, requests, pyshorteners, hashlib, json, logging, datetime, urllib.parse, base64, re, os
from email.utils import parsedate_to_datetime

logging.basicConfig(level=logging.INFO)

class URLManager:
    def __init__(self, cache_file='url_cache.json'):
        self.cache_file = cache_file
        self.cache = self.load_cache()
        self.shortener = pyshorteners.Shortener()

    def load_cache(self):
        if os.path.exists(self.cache_file):
            with open(self.cache_file, 'r', encoding='utf-8') as f: return json.load(f)
        return {}

    def save_cache(self):
        with open(self.cache_file, 'w', encoding='utf-8') as f: json.dump(self.cache, f, ensure_ascii=False)

    def decode_url(self, raw_url, title):
        try:
            match = re.search(r'articles/([^?]+)', raw_url)
            if match:
                encoded = match.group(1) + "=="
                decoded = base64.urlsafe_b64decode(encoded)
                url_match = re.search(rb'https?://[^\x00-\x1F\x7F]+', decoded)
                if url_match: return url_match.group(0).decode('utf-8')
        except: pass
        return f"https://www.google.com/search?q={urllib.parse.quote(title)}&btnI=1"

    def get_short(self, url):
        h = hashlib.md5(url.encode()).hexdigest()
        if h not in self.cache:
            try: self.cache[h] = self.shortener.tinyurl.short(url)
            except: return url
        return self.cache[h]

class NewsFetcher:
    def __init__(self):
        self.hkt = pytz.timezone('Asia/Hong_Kong')
        self.keywords = '"青衣" OR "葵涌" OR "葵芳" OR "葵興" OR "青山道" OR "和宜合道"'
        self.exclude = ['股價', '股市', '恆指', '業績', '盈利', '板塊', '融資']

    def fetch(self, url_mgr):
        feed = feedparser.parse(f"https://news.google.com/rss/search?q={urllib.parse.quote(self.keywords)}&hl=zh-HK&gl=HK&ceid=HK:zh-Hant")
        data = {'P1': [], 'P2': [], 'P3': []}
        p1_src = ['東方', '東網', '星島', '大公', '文匯', '01']
        
        for e in feed.entries:
            title = e.title.rsplit(' - ', 1)[0]
            if any(w in title for w in self.exclude): continue
            
            src = e.source.title if hasattr(e, 'source') else '新聞'
            dt = parsedate_to_datetime(e.published).astimezone(self.hkt)
            
            item = {
                'title': title, 'source': src, 'time': dt.strftime('%H:%M'),
                'date': dt.strftime('%Y-%m-%d'), 'url': url_mgr.get_short(url_mgr.decode_url(e.link, title))
            }
            
            if any(s in src for s in p1_src): data['P1'].append(item)
            elif any(s in e.link for s in ['facebook.com', 'youtube.com', 'threads.net']): data['P3'].append(item)
            else: data['P2'].append(item)
        return data

# HTML 模板包含日期搜尋與 iPhone App 優化
HTML_TMPL = """
<!DOCTYPE html><html><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<meta name="apple-mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-status-bar-style" content="black">
<title>葵青新聞</title>
<style>
    body { font-family:-apple-system; background:#F2F2F7; margin:0; padding:15px; }
    .search-box { position:sticky; top:10px; background:white; padding:10px; border-radius:12px; display:flex; gap:5px; box-shadow:0 4px 10px rgba(0,0,0,0.1); margin-bottom:15px; z-index:99; }
    input { flex:1; border:1px solid #DDD; border-radius:8px; padding:8px; font-size:16px; }
    .card { background:white; border-radius:12px; padding:15px; margin-bottom:12px; }
    .title { font-size:18px; font-weight:bold; text-decoration:none; color:black; display:block; margin-bottom:8px; }
    .meta { color:gray; font-size:13px; margin-bottom:10px; }
    .btn { background:#25D366; color:white; text-decoration:none; padding:8px; border-radius:8px; display:block; text-align:center; font-size:14px; }
    h2 { border-left:4px solid #007AFF; padding-left:10px; font-size:20px; }
</style>
</head>
<body>
    <h2>葵青即時新聞</h2>
    <div class="search-box">
        <input type="date" id="d">
        <input type="text" id="q" placeholder="搜尋關鍵字...">
    </div>
    <div id="content">
        {%CONTENT%}
    </div>
    <script>
        const d = document.getElementById('d');
        const q = document.getElementById('q');
        function filter() {
            const dv = d.value;
            const qv = q.value.toLowerCase();
            document.querySelectorAll('.card').forEach(c => {
                const matchD = !dv || c.dataset.date === dv;
                const matchQ = c.innerText.toLowerCase().includes(qv);
                c.style.display = (matchD && matchQ) ? 'block' : 'none';
            });
        }
        d.onchange = filter; q.oninput = filter;
    </script>
</body></html>
"""

def main():
    u = URLManager(); f = NewsFetcher()
    d = f.fetch(u); u.save_cache()
    
    body = ""
    for cat in ['P1', 'P2', 'P3']:
        body += f"<h3>{cat} 分類</h3>"
        for i in d[cat]:
            share = urllib.parse.quote(f"{i['title']}\\n{i['url']}")
            body += f'''<div class="card" data-date="{i['date']}">
                <a class="title" href="{i['url']}">{i['title']}</a>
                <div class="meta">{i['source']} | {i['date']} {i['time']}</div>
                <a class="btn" href="https://api.whatsapp.com/send?text={share}">WhatsApp 分享</a>
            </div>'''
    
    with open('index.html', 'w', encoding='utf-8') as f:
        f.write(HTML_TMPL.replace('{%CONTENT%}', body))

if __name__ == "__main__": main()
