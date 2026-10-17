"""Chat Completions wire format lives here; no SDK or implicit retries."""
import json
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from .config import ROOT, Settings
from .errors import AppError
from .prompts import messages
from .source import source_hash

MAX_RESPONSE_BYTES = 256 * 1024


@dataclass
class CallBudget:
    limit: int
    used: int = 0

    def consume(self):
        if self.used >= self.limit:
            raise AppError('CALL_BUDGET_EXHAUSTED', '已達本次評測的供應商呼叫上限。', 503)
        self.used += 1


class Adapter:
    def __init__(self, settings: Settings, *, transport=None, budget=None):
        self.settings = settings
        self.transport = transport
        self.budget = budget
        self.usage_records = []

    def fixture(self, source, language):
        paths = [*(ROOT / 'data/fixtures').glob('*.json'), *(ROOT / 'data/demo_notices').glob('*.json')]
        for path in sorted(paths):
            record = json.loads(path.read_text(encoding='utf-8'))
            if source_hash(record['text']) == source_hash(source['text']) and record['text'] == source['text']:
                return record['outputs'][language]
        raise AppError('FIXTURE_NOT_AVAILABLE', '示例體驗僅支援預設的虛構通知。請選擇頁面提供的示例，並保留完整原文後再試。', 503)

    def check_config(self):
        s = self.settings
        if not s.llm_model or not s.llm_api_key.get_secret_value() or not s.llm_base_url:
            raise AppError('MODEL_NOT_CONFIGURED', '真實模型尚未設定。請由團隊在伺服器設定模型服務。', 503)
        url = urlsplit(s.llm_base_url)
        if url.scheme != 'https' or not url.netloc or url.username or url.password or url.query or url.fragment:
            raise AppError('MODEL_NOT_CONFIGURED', '模型服務網址須為有效 HTTPS 服務根網址。', 503)

    def output_limit(self, source):
        # Long multi-procedure notices need room for supported exceptions and quotes.
        return min(8192,self.settings.llm_max_tokens*2) if len(source['text'])>600 else self.settings.llm_max_tokens

    async def generate(self, source, language, *, baseline=False, repair=False, repair_hint=''):
        s = self.settings
        if s.llm_mode == 'fixture':
            if baseline:
                raise AppError('BASELINE_REQUIRES_LIVE', '固定樣例不代表基線模型結果。', 503)
            return self.fixture(source, language)
        self.check_config()
        payload = {'model': s.llm_model, 'messages': messages(source, language, baseline=baseline, repair=repair, repair_hint=repair_hint),
                   'max_tokens': self.output_limit(source), 'temperature': 0.2, 'stream': False}
        if s.llm_disable_thinking:
            payload['thinking'] = {'type': 'disabled'}
        if s.llm_json_mode and not baseline:
            payload['response_format'] = {'type': 'json_object'}
        headers = {'Authorization': 'Bearer ' + s.llm_api_key.get_secret_value()}
        if self.budget:
            self.budget.consume()
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=httpx.Timeout(30, connect=5),
                                         follow_redirects=False) as client:
                async with client.stream('POST', s.llm_base_url.rstrip('/') + '/chat/completions',
                                         json=payload, headers=headers) as response:
                    if response.status_code in (401, 403):
                        raise AppError('MODEL_AUTH_FAILED', '模型服務認證失敗，請團隊檢查伺服器設定。', 503)
                    if response.status_code == 429:
                        try:
                            delay = max(0, float(response.headers.get('retry-after', '1')))
                        except ValueError:
                            delay = 1
                        raise AppError('MODEL_RATE_LIMITED', '模型服務繁忙，請稍後重試。', 503, retryable=True, delay=delay)
                    if response.status_code >= 500:
                        raise AppError('MODEL_UNAVAILABLE', '模型服務暫時不可用，請重試。', 503, retryable=True)
                    if not response.is_success:
                        raise AppError('MODEL_UNAVAILABLE', '模型服務拒絕請求，請團隊檢查設定。', 503)
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > MAX_RESPONSE_BYTES:
                            raise AppError('MODEL_OUTPUT_INVALID', '模型回傳過大，請縮短通知後重試。', retryable=True)
            try:
                envelope = json.loads(data)
                usage = envelope.get('usage', {})
                self.usage_records.append({key: value for key, value in usage.items()
                                           if key in ('prompt_tokens', 'completion_tokens', 'total_tokens', 'prompt_cache_hit_tokens', 'prompt_cache_miss_tokens')
                                           and isinstance(value, int) and value >= 0})
                choice = envelope['choices'][0]
                content = choice['message']['content']
                if not isinstance(content, str) or choice.get('finish_reason') not in (None, 'stop'):
                    raise ValueError('incomplete output')
                return content
            except (ValueError, KeyError, IndexError, TypeError):
                raise AppError('MODEL_OUTPUT_INVALID', '模型回傳無法解析，請重試。', retryable=True) from None
        except httpx.TimeoutException:
            raise AppError('MODEL_TIMEOUT', '解讀逾時，原文已保留，請稍後重試。', 504, retryable=True) from None
        except httpx.RequestError:
            raise AppError('MODEL_UNAVAILABLE', '無法連接模型服務，請稍後重試。', 503, retryable=True) from None
