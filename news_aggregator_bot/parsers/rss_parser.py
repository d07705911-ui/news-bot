import feedparser
import re
from typing import List, Dict, Optional


def parse_rss(url: str) -> List[Dict]:
    """Парсит RSS-ленту и возвращает список новостей."""
    try:
        feed = feedparser.parse(url)
        news = []
        
        for entry in feed.entries[:10]:  # Берём последние 10
            # Пытаемся извлечь картинку
            image_url = extract_image(entry)
            
            news.append({
                "title": entry.get("title", "Без названия"),
                "description": clean_html(entry.get("summary", entry.get("description", ""))),
                "link": entry.get("link", ""),
                "published": parse_date(entry.get("published", "")),
                "source": feed.feed.get("title", url),
                "image": image_url,
            })
        
        return news
    except Exception as e:
        print(f"Ошибка парсинга {url}: {e}")
        return []


def extract_image(entry) -> Optional[str]:
    """Извлекает URL картинки из записи RSS."""
    # Пробуем разные источники картинок
    # 1. Media content
    if hasattr(entry, 'media_content') and entry.media_content:
        for m in entry.media_content:
            if 'url' in m and 'image' in m.get('type', ''):
                return m['url']
    
    # 2. enclosures
    if hasattr(entry, 'enclosures') and entry.enclosures:
        for enc in entry.enclosures:
            if enc.get('type', '').startswith('image'):
                return enc.get('url')
    
    # 3. links
    if hasattr(entry, 'links'):
        for link in entry.links:
            if link.get('type', '').startswith('image'):
                return link.get('href')
    
    # 4. Из description (HTML)
    summary = entry.get('summary', '') or entry.get('description', '')
    img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', summary)
    if img_match:
        return img_match.group(1)
    
    return None


def clean_html(text: str) -> str:
    """Удаляет HTML-теги из текста."""
    import re
    clean = re.sub(r'<[^>]+>', '', text)
    clean = clean.replace('&nbsp;', ' ').replace('&amp;', '&')
    return clean.strip()[:200] + "..." if len(clean) > 200 else clean


def parse_date(date_str: str) -> str:
    """Парсит дату из RFC 822 в читаемый формат."""
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(date_str)
        return dt.strftime("%d.%m.%Y %H:%M")
    except:
        return date_str


def get_all_news(sources: Dict[str, List[str]]) -> List[Dict]:
    """Получает новости со всех источников."""
    all_news = []
    
    for category, urls in sources.items():
        for url in urls:
            news = parse_rss(url)
            for item in news:
                item["category"] = category
            all_news.extend(news)
    
    # Сортируем по дате (новые первыми)
    all_news.sort(key=lambda x: x["published"], reverse=True)
    return all_news
