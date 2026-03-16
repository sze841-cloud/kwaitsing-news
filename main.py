import feedparser
import pytz
import requests
import pyshorteners
import hashlib
import json
import logging
import datetime
import urllib.parse
import base64
import re
import os
from email.utils import parsedate_to_datetime

# 設置日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class URLManager:
    """
    URL 管理器 (OOP封裝)
    負責 Google News 網址解碼、短網址生成與 MD5 快取處理
    """
    def __init__(self, cache_file='url_cache.json'):
        self.cache_file = cache_file
        self.cache = self.load_cache()
        self.shortener = pyshorteners.Shortener()

    def load_cache(self):
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logging.error(f"讀取快取失敗: {e}")
        return {}

    def save_cache(self):
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.cache, f, ensure_ascii=False, indent=2)
            logging.info("網址快取已成功儲存。")
        except Exception as e:
            logging.error(f"儲存快取失敗: {e}")

    def decode_google_news_url(self, raw_url, title):
        """
        將 Google News 原始網址進行 Base64 解碼。
        若失敗則使用終極跳轉方案 (手氣不錯)。
        """
        try:
            # Google News RSS 文章連結特徵，通常在 articles/ 之後
            match = re.search(r'articles/([^?]+)', raw_url)
            if match:
                encoded_part = match.group(1)
                # 補齊 Base64 padding
                encoded_part += "=" * ((4 - len(encoded_part) % 4) % 4)
                decoded_bytes = base64.urlsafe_b64decode(encoded_part)
                
                # 從解碼的位元組中提取真實網址
                url_match = re.search(rb'https?://[^\x00-\x1F\x7F]+', decoded_bytes)
                if url_match:
                    real_url = url_match.group(0).decode('utf-8', errors='ignore')
                    return real_url
        except Exception as e:
            logging.warning(f"Base64 解碼失敗 ({title}): {e}")

        # 終極跳轉方案：I'm Feeling Lucky
        logging.info(f"使用終極跳轉方案: {title}")
        encoded_title = urllib.parse.quote(title)
        return f"https://www.google.com/search?q={encoded_title}&btnI=1"

    def get_short_url(self, long_url):
        """
        使用 pyshorteners 生成 TinyURL，並透過 MD5 快取避免重複請求
        """
        url_hash = hashlib.md5(long_url.encode('utf-8')).hexdigest()
        if url_hash in self.cache:
            return self.cache[url_hash]
        
        try:
            short_url = self.shortener.tinyurl.short(long_url)
            self.cache[url_hash] = short_url
            return short_url
        except Exception as e:
            logging.error(f"縮網址生成失敗 {long_url}: {e}")
            return long_url # 失敗時返回原始網址作為 fallback


class NewsFetcher:
    """
    新聞抓取與分類器
    """
    def __init__(self):
        self.hkt = pytz.timezone('Asia/Hong_Kong')
        self.now = datetime.datetime.now(self.hkt)
        
        # 設定目標時間：今日凌晨 05:00 (HKT)
        self.start_time = self.now.replace(hour=5, minute=0, second=0, microsecond=0)
        # 如果目前時間早於 05:00，則抓取昨天 05:00 之後的新聞
        if self.now < self.start_time:
            self.start_time -= datetime.timedelta(days=1)

        self.keywords = '"青衣" OR "葵涌" OR "葵芳" OR "葵興" OR "青山道" OR "和宜合道"'
        self.p1_sources = ['東方', '東網', '星島', '大公', '文匯', '01']

    def is_valid_time(self, pub_date_str):
        try:
            dt = parsedate_to_datetime(pub_date_str)
            dt_hkt = dt.astimezone(self.hkt)
            return dt_hkt >= self.start_time
        except Exception as e:
            logging.error(f"時間解析錯誤 ({pub_date_str}): {e}")
            return False

    def fetch_rss(self, query):
        encoded_query = urllib.parse.quote(query)
        url = f"https://news.google.com/rss/search?q={encoded_query}&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
        logging.info(f"正在抓取 RSS: {query}")
        return feedparser.parse(url)

    def process_entries(self, entries, url_manager):
        results = []
        for entry in entries:
            if not self.is_valid_time(entry.published):
                continue

            # 清理標題 (移除 Google News 附加的來源後綴)
            title = entry.title
            if ' - ' in title:
                title = title.rsplit(' - ', 1)[0]
                
            source = entry.source.title if hasattr(entry, 'source') else '未知來源'
            raw_link = entry.link
            
            # URL 工程處理
            real_url = url_manager.decode_google_news_url(raw_link, title)
            short_url = url_manager.get_short_url(real_url)

            # 轉換顯示時間
            dt = parsedate_to_datetime(entry.published).astimezone(self.hkt)
            time_str = dt.strftime('%H:%M')

            results.append({
                'title': title,
                'source': source,
                'url': short_url,
                'time': time_str,
                'raw_date': dt
            })
            
        # 依時間降序排列 (最新在前)
        results.sort(key=lambda x: x['raw_date'], reverse=True)
        return results

    def fetch_all(self, url_manager):
        # 抓取一般新聞 (P1 & P2)
        general_rss = self.fetch_rss(self.keywords)
        general_news = self.process_entries(general_rss.entries, url_manager)

        p1, p2 = [], []
        for item in general_news:
            if any(s in item['source'] for s in self.p1_sources):
                p1.append(item)
            else:
                p2.append(item)

        # 抓取社交媒體新聞 (P3)
        sm_query = f'({self.keywords}) AND (site:facebook.com OR site:youtube.com OR site:threads.net)'
        sm_rss = self.fetch_rss(sm_query)
        p3 = self.process_entries(sm_rss.entries, url_manager)

        return {'P1': p1, 'P2': p2, 'P3': p3}


class HTMLGenerator:
    """
    iPhone 最佳化網頁產生器
    """
    @staticmethod
    def generate_share_text(category_name, items):
        """生成該分類前 8 則新聞的分享文字"""
        lines = [f"📊 【{category_name}】最新資訊彙整"]
        for item in items[:8]:
            lines.append(f"▪️ [{item['source']}] {item['title']}\n🔗 {item['url']}")
        return "\n\n".join(lines)

    @staticmethod
    def generate_html(data):
        update_time = datetime.datetime.now(pytz.timezone('Asia/Hong_Kong')).strftime('%Y-%m-%d %H:%M:%S HKT')
        
        html_template = f"""<!DOCTYPE html>
<html lang="zh-HK">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>葵青區即時新聞</title>
    <style>
        :root {{
            --bg-color: #f2f2f7;
            --card-bg: #ffffff;
            --text-main: #1c1c1e;
            --text-sub: #8e8e93;
            --accent: #007aff;
            --whatsapp: #25D366;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: var(--bg-color);
            color: var(--text-main);
            margin: 0;
            padding: 16px;
            -webkit-font-smoothing: antialiased;
        }}
        header {{
            text-align: center;
            margin-bottom: 24px;
        }}
        h1 {{ font-size: 28px; font-weight: 700; margin: 0 0 8px 0; }}
        .update-time {{ font-size: 14px; color: var(--text-sub); }}
        
        .section-header {{
            display: flex;
            justify-content: space-between;
            align-items: flex-end;
            margin: 28px 0 12px 0;
            padding-bottom: 8px;
            border-bottom: 1px solid #c6c6c8;
        }}
        .section-title {{ font-size: 22px; font-weight: 600; margin: 0; }}
        
        .card {{
            background: var(--card-bg);
            border-radius: 14px;
            padding: 16px;
            margin-bottom: 16px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.04);
        }}
        .news-title {{
            font-size: 19px;
            font-weight: 600;
            line-height: 1.4;
            margin: 0 0 8px 0;
            color: var(--text-main);
            text-decoration: none;
            display: block;
        }}
        .news-meta {{
            font-size: 14px;
            color: var(--text-sub);
            margin-bottom: 14px;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .source-tag {{
            background: #e5e5ea;
            color: #3a3a3c;
            padding: 2px 8px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 500;
        }}
        
        .btn {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            border-radius: 8px;
            font-weight: 600;
            text-decoration: none;
            cursor: pointer;
            border: none;
        }}
        .btn-share {{
            background-color: #e8f9ed;
            color: var(--whatsapp);
            padding: 8px 16px;
            font-size: 15px;
            width: 100%;
            box-sizing: border-box;
        }}
        .btn-share svg {{ margin-right: 6px; }}
        
        .btn-share-group {{
            background-color: var(--accent);
            color: white;
            padding: 6px 14px;
            font-size: 14px;
            border-radius: 16px;
        }}
        .empty-state {{ text-align: center; color: var(--text-sub); padding: 20px 0; font-size: 16px; }}
    </style>
</head>
<body>
    <header>
        <h1>葵青區即時新聞</h1>
        <div class="update-time">最後更新：{update_time}</div>
        <div class="update-time">涵蓋時間：今日 05:00 至今</div>
    </header>
"""

        # 分區渲染
        sections = [
            ('P1', '主要報章 (P1)', data['P1']),
            ('P2', '其他媒體 (P2)', data['P2']),
            ('P3', '社交媒體 (P3)', data['P3'])
        ]

        for cat_id, title, items in sections:
            # 準備類別分享連結
            share_text = urllib.parse.quote(HTMLGenerator.generate_share_text(title, items))
            share_link = f"https://api.whatsapp.com/send?text={share_text}"
            
            html_template += f"""
    <div class="section-header">
        <h2 class="section-title">{title}</h2>
        <a href="{share_link}" target="_blank" class="btn btn-share-group">分享清單</a>
    </div>
"""
            if not items:
                html_template += '<div class="empty-state">目前時段暫無相關新聞</div>'
            else:
                for item in items:
                    # 單篇分享文字
                    single_share_text = urllib.parse.quote(f"【{item['source']}】{item['title']}\n🔗 {item['url']}")
                    single_share_link = f"https://api.whatsapp.com/send?text={single_share_text}"
                    
                    html_template += f"""
    <div class="card">
        <a href="{item['url']}" target="_blank" class="news-title">{item['title']}</a>
        <div class="news-meta">
            <span class="source-tag">{item['source']}</span>
            <span>{item['time']}</span>
        </div>
        <a href="{single_share_link}" target="_blank" class="btn btn-share">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
                <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413Z"/>
            </svg>
            WhatsApp 分享
        </a>
    </div>
"""

        html_template += """
</body>
</html>
"""
        return html_template

def main():
    logging.info("開始執行葵青區新聞自動抓取任務...")
    
    # 1. 啟動 URL 管理器 (載入快取)
    url_manager = URLManager()
    
    # 2. 抓取與篩選資料
    fetcher = NewsFetcher()
    news_data = fetcher.fetch_all(url_manager)
    
    # 3. 儲存 URL 快取
    url_manager.save_cache()
    
    # 4. 生成 HTML
    html_content = HTMLGenerator.generate_html(news_data)
    
    # 5. 輸出靜態文件
    with open('index.html', 'w', encoding='utf-8') as f:
        f.write(html_content)
        
    logging.info("網頁生成完成，已輸出至 index.html")

if __name__ == "__main__":
    main()
