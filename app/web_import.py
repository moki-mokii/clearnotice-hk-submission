"""Bounded public-page import. No cookies, scripts, credentials or model calls."""
import asyncio
import codecs
from datetime import datetime, timezone
from html.parser import HTMLParser
import ipaddress
import re
import socket

import httpx

from .errors import AppError
from .source import normalize, source_hash

MAX_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 4


def public_ip(value):
    ip = ipaddress.ip_address(value)
    if not ip.is_global or ip.is_multicast or str(ip) == '168.63.129.16':
        return False
    if ip.version == 6:
        if ip.ipv4_mapped or ip.sixtofour or ip.teredo:
            return False
        if ip in ipaddress.ip_network('64:ff9b::/96'):
            return ipaddress.ip_address(int(ip) & 0xffffffff).is_global
    return True


def check_url(value):
    try:
        url = httpx.URL(value)
        if (url.scheme not in ('http', 'https') or not url.host or url.userinfo
                or url.port not in (None, 80, 443) or len(str(url)) > 2048):
            raise ValueError()
        host = url.host.rstrip('.').lower()
        if ('.' not in host and ':' not in host) or host.endswith(('.localhost', '.local', '.internal')):
            raise ValueError()
        try:
            if not public_ip(host):
                raise ValueError()
        except ValueError:
            # A hostname is resolved and checked before every request below.
            if re.fullmatch(r'[0-9.:]+', host) or ':' in host:
                raise
        return url.copy_with(fragment=None)
    except (ValueError, httpx.InvalidURL):
        raise AppError('WEB_URL_BLOCKED', '請使用公開網頁的 http 或 https 連結；不支援內網、帶帳密或特殊連接埠的網址。', 422) from None


async def resolve_public(host, port):
    try:
        values = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
        addresses = list(dict.fromkeys(item[4][0] for item in values))
    except (OSError, UnicodeError):
        raise AppError('WEB_UNAVAILABLE', '找不到這個網站，請檢查連結或改貼通知文字。', 502) from None
    if not addresses or any(not public_ip(address) for address in addresses):
        raise AppError('WEB_URL_BLOCKED', '這個連結不是可讀取的公開網頁，請改貼通知文字。', 422)
    # Prefer IPv4 when both families exist; pin the checked address, not the hostname.
    return next((ip for ip in addresses if ipaddress.ip_address(ip).version == 4), addresses[0])


class Node:
    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []


class PageParser(HTMLParser):
    VOID = {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.nodes = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        n = Node(tag, attrs)
        self.nodes.append(n)
        self.stack[-1].children.append(n)
        if tag not in self.VOID:
            self.stack.append(n)
        if len(self.stack) > 120:
            raise AppError('WEB_UNSUPPORTED', '這個網頁結構暫時無法讀取，請改貼通知文字。', 422)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack)-1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, value):
        self.stack[-1].children.append(value)


def plain(node):
    if isinstance(node, str):
        return re.sub(r'[\t\r\n ]+', ' ', node.replace('\xa0', ' '))
    attrs = node.attrs
    if (node.tag in ('script','style','noscript','nav','footer','aside','form','button','svg','iframe','template')
            or 'hidden' in attrs or attrs.get('aria-hidden') == 'true'
            or re.search(r'display\s*:\s*none|visibility\s*:\s*hidden', attrs.get('style',''), re.I)):
        return ''
    if node.tag == 'br':
        return '\n'
    value = ''.join(plain(c) for c in node.children)
    if node.tag in ('td','th'):
        return ' / '.join(x.strip() for x in value.splitlines() if x.strip()) + ' | '
    if node.tag in ('div','p','section','article','main','h1','h2','h3','h4','li','ul','ol','table','tr','blockquote'):
        return '\n' + value.strip(' |\n') + '\n'
    return value


def clean(node):
    return '\n'.join(x.strip().rstrip(' |') for x in plain(node).splitlines() if x.strip())


def extract(html):
    doc = PageParser(html)
    by_id = {n.attrs.get('id'):n for n in doc.nodes if n.attrs.get('id')}
    title = next((clean(n) for n in doc.nodes if n.tag == 'title'), '')[:250]
    if 'pressrelease' in by_id:
        body = clean(by_id['pressrelease'])
        title = clean(by_id.get('PRHeadline', Node())) or title
        method = 'government_press_release'
    else:
        candidates = [n for n in doc.nodes if n.tag in ('article','main') or n.attrs.get('role') == 'main']
        if candidates:
            body = max((clean(n) for n in candidates), key=len)
            method = 'main_content'
        else:
            # Be explicit that heuristic extraction may include unrelated text.
            bodies = [n for n in doc.nodes if n.tag == 'body']
            body = clean(bodies[0] if bodies else doc.root)
            method = 'body_fallback'
    text = normalize((title+'\n' if title and not body.startswith(title) else '') + body)
    if len(body) < 30:
        raise AppError('WEB_NO_TEXT', '未找到足夠的通知正文。網頁可能需要登入、只有圖片或需載入腳本，請改貼文字。', 422)
    if len(text) > 12000:
        raise AppError('WEB_TEXT_TOO_LONG', '網頁內容超過12,000字，請改貼其中一份通知的正文。', 422)
    return title, text, method


def decode(raw, content_type):
    charset = re.search(r'charset\s*=\s*["\']?([\w-]+)', content_type, re.I)
    if not charset:
        charset = re.search(br'charset\s*=\s*["\']?([\w-]+)', raw[:4096], re.I)
    name = charset.group(1) if charset else 'utf-8-sig'
    if isinstance(name, bytes):
        name = name.decode('ascii')
    try:
        codecs.lookup(name)
        return raw.decode(name)
    except (LookupError, UnicodeError):
        raise AppError('WEB_UNSUPPORTED', '暫時無法辨識網頁文字編碼，請改貼通知文字。', 422) from None


async def import_page(value, *, resolver=resolve_public, transport=None):
    initial = check_url(value)
    current = initial
    try:
        async with asyncio.timeout(18):
            for hop in range(MAX_REDIRECTS+1):
                current = check_url(str(current))
                ip = await resolver(current.host, current.port or (443 if current.scheme == 'https' else 80))
                if not public_ip(ip):
                    raise AppError('WEB_URL_BLOCKED', '無法讀取非公開網頁。', 422)
                target = current.copy_with(host=ip)
                headers = {'Host':current.netloc.decode('ascii'), 'User-Agent':'ClearNoticeHK/0.2 (public notice text reader)',
                           'Accept':'text/html,application/xhtml+xml,text/plain', 'Accept-Encoding':'identity'}
                # TLS still validates the original hostname; no ambient proxy/cookies/auth.
                async with httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(8,connect=5),
                                             follow_redirects=False, trust_env=False) as client:
                    async with client.stream('GET',target,headers=headers,extensions={'sni_hostname':current.host}) as response:
                        if response.status_code in (301,302,303,307,308):
                            location = response.headers.get('location')
                            if not location or hop == MAX_REDIRECTS:
                                raise AppError('WEB_UNAVAILABLE', '連結轉址過多或無法讀取，請改貼通知文字。', 502)
                            current = current.join(location)
                            continue
                        if not response.is_success:
                            raise AppError('WEB_UNAVAILABLE', '網站拒絕讀取或頁面不存在，請改貼通知文字。', 502)
                        kind = response.headers.get('content-type','').lower()
                        if kind.split(';')[0].strip() not in ('text/html','application/xhtml+xml','text/plain'):
                            raise AppError('WEB_UNSUPPORTED', '目前支援文字網頁；PDF、圖片或下載檔案請先轉成文字。', 422)
                        if response.headers.get('content-encoding','identity').lower() not in ('identity',''):
                            raise AppError('WEB_UNSUPPORTED', '這個網站的傳輸格式暫不支援，請改貼通知文字。', 422)
                        raw = bytearray()
                        async for chunk in response.aiter_raw():
                            raw.extend(chunk)
                            if len(raw) > MAX_BYTES:
                                raise AppError('WEB_TOO_LARGE', '網頁過大，請改貼通知正文。', 422)
                html = decode(raw, kind)
                if kind.startswith('text/plain'):
                    text, title, method = normalize(html), current.host, 'plain_text'
                    if not 30 <= len(text) <= 12000:
                        raise AppError('WEB_NO_TEXT', '正文須為30至12,000字，請改貼通知文字。', 422)
                else:
                    title, text, method = extract(html)
                return {'text':text, 'source_label':title or current.host, 'source_url':str(current),
                        'original_url':str(initial), 'retrieved_at':datetime.now(timezone.utc).isoformat(),
                        'source_hash':source_hash(text), 'extraction_method':method,
                        'notice':'已讀取網頁文字，請確認正文完整；圖片、附件及連結內的內容未讀取。'}
    except (TimeoutError, httpx.TimeoutException):
        raise AppError('WEB_TIMEOUT', '讀取網頁逾時，請重試或改貼通知文字。', 504) from None
    except (httpx.RequestError, httpx.InvalidURL):
        raise AppError('WEB_UNAVAILABLE', '無法連接這個網站，請檢查連結或改貼通知文字。', 502) from None
