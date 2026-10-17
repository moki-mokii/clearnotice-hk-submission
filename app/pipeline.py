import asyncio
import json
import logging
import re
import time
from datetime import datetime, timezone
from uuid import uuid4

from pydantic import ValidationError

from .errors import AppError
from .formatting import LABELS
from .llm import Adapter
from .prompts import PROMPT_VERSION
from .schemas import AnalyzeRequest, Result
from .source import make_source, source_hash

logger = logging.getLogger('clearnotice')


def check_output_language(result: Result, language: str):
    """Catch gross wrong-language prose, not proper names or translation correctness."""
    text = ' '.join(item.text for item in [*result.summary, *result.actions])
    han = len(re.findall(r'[\u3400-\u9fff]', text))
    latin = len(re.findall(r'[A-Za-z]', text))
    if (language == 'en' and han >= 8 and han > latin) or (
            language == 'zh-Hant' and han == 0 and latin >= 20):
        raise AppError('MODEL_OUTPUT_INVALID', '解讀結果的語言不符，請重試。', retryable=True)
    if result.card:
        card_text=' '.join([result.card.overview.text, result.card.next_step.text if result.card.next_step else '',
                           *[f.value or '' for _,f in result.card.facts]])
        card_han=len(re.findall(r'[\u3400-\u9fff]',card_text));card_latin=len(re.findall(r'[A-Za-z]',card_text))
        if (language=='en' and card_han>=8 and card_han>card_latin) or (language=='zh-Hant' and card_han==0 and card_latin>=20):
            raise AppError('MODEL_OUTPUT_INVALID','重點卡片的語言不符，請重試。',retryable=True)


def check_wording(result: Result):
    """Reject specific unsupported qualifiers; this is not general semantic checking."""
    patterns = (
        r'非保證|不保證|無法保證|並非保證|not (?:a )?guarantee(?:d)?|no guarantee(?:d)?',
        r'預計|預期|估計|預料|expected|estimated|anticipated',
        r'另行通知|另行公布|until further notice|until further announcement',
    )
    entries = [(f.value, f.evidence) for _,f in result.facts if f.status=='stated']
    entries += [(x.text,x.evidence) for x in [*result.summary,*result.actions]]
    if result.card:
        entries += [(f.value,f.evidence) for _,f in result.card.facts if f.status=='stated']
        entries.append((result.card.overview.text,result.card.overview.evidence))
        if result.card.next_step:entries.append((result.card.next_step.text,result.card.next_step.evidence))
    for text,evidence in entries:
        quotes = ' '.join(e.quote for e in evidence)
        for pattern in patterns:
            if re.search(pattern,text or '',re.I) and not re.search(pattern,quotes,re.I):
                raise AppError('MODEL_OUTPUT_INVALID', '部分表述的確定程度或時間條件與原文不符，請重試。', retryable=True)


def check_evidence(result: Result, source: dict, language: str):
    """Substring checking is NOT semantic verification."""
    lines = {line['line_id']: line['text'] for line in source['lines']}
    warnings = []
    en = language == 'en'
    field_labels = dict(zip(Result.model_fields['facts'].annotation.model_fields, LABELS[language]))

    def valid(ev):
        return ev.line_id in lines and ev.quote in lines[ev.line_id]

    for name, fact in result.facts:
        if any(not valid(e) for e in fact.evidence):
            fact.evidence = [e for e in fact.evidence if valid(e)]
            fact.status = 'uncertain'
            fact.value = None
            warnings.append({'code': 'FACT_EVIDENCE_MISMATCH', 'field': name,
                             'message': f'{field_labels[name]}: source quote not found; please check.' if en else f'{field_labels[name]}的部分引句不符，請核對原文。'})
        # Referring to an unseen attachment is not a stated price or a known venue.
        if name in ('fee','location') and fact.status=='stated' and re.search(r'附件|attachment',fact.value or '',re.I):
            known_price = name=='fee' and re.search(r'\d|免費|free|no charge',fact.value or '',re.I)
            if not known_price:
                fact.status='uncertain';fact.value=None
                warnings.append({'code':'DETAIL_IN_ATTACHMENT','field':name,
                    'message':f'{field_labels[name]} depends on an attachment; check the original attachment before acting.' if en else
                    f'{field_labels[name]}涉及附件資料，請先核對原通知附件後再辦理。'})
    for kind in ('summary', 'actions'):
        kept = []
        for item in getattr(result, kind):
            if all(valid(e) for e in item.evidence):
                kept.append(item)
            else:
                warnings.append({'code': 'ITEM_REMOVED', 'field': kind,
                                 'message': 'An unsupported item was removed.' if en else '已移除引句不符的內容，請核對原文。'})
        setattr(result, kind, kept)
    if not result.summary:
        raise AppError('MODEL_OUTPUT_INVALID', '無法保留有原文引句的概覽，請核對原文或重新解讀。')
    for name, fact in result.facts:
        if fact.status != 'stated':
            warnings.append({'code': 'CHECK_WITH_ORGANIZER', 'field': name,
                             'message': f'{field_labels[name]}: not stated or uncertain; you may ask the organizer.' if en else f'{field_labels[name]}未說明或不確定，可向主辦方查詢。'})
    if result.card:
        card=result.card
        items=[card.overview,*([card.next_step] if card.next_step else [])]
        invalid=any(f.status!=getattr(result.facts,name).status or any(not valid(e) for e in f.evidence)
                    for name,f in card.facts)
        invalid=invalid or any(any(not valid(e) for e in item.evidence) for item in items)
        invalid=invalid or bool(card.next_step)!=bool(result.actions)
        if invalid:
            result.card=None
            warnings.append({'code':'CARD_VIEW_FALLBACK','field':'card',
                             'message':'The brief card needs checking; full information is shown.' if en else '簡短卡片需要核對，已顯示完整資料。'})
    return result, warnings


async def analyze(request: AnalyzeRequest, adapter: Adapter, *, request_id=None, baseline=False, capture_raw=False):
    request_id = request_id or str(uuid4())
    start = time.monotonic()
    source = make_source(request.text)
    attempts = 0
    usage_start = len(adapter.usage_records)
    error_code = None
    repair_hint = ''
    try:
        async with asyncio.timeout(65):
            for index in range(2):
                try:
                    # Configuration/fixture lookup does not consume provider calls.
                    if adapter.settings.llm_mode == 'live':
                        adapter.check_config()
                        if adapter.budget and adapter.budget.used >= adapter.budget.limit:
                            raise AppError('CALL_BUDGET_EXHAUSTED', '已達供應商呼叫上限。', 503)
                        attempts += 1
                    raw = await adapter.generate(source, request.output_language, baseline=baseline, repair=index > 0, repair_hint=repair_hint)
                    if baseline:
                        if not isinstance(raw, str) or not raw.strip():
                            raise AppError('MODEL_OUTPUT_INVALID', '基線模型回傳空內容。', retryable=True)
                        result, warnings = raw, []
                    else:
                        try:
                            result = Result.model_validate(json.loads(raw) if isinstance(raw, str) else raw)
                        except (ValueError, ValidationError, TypeError) as exc:
                            if isinstance(exc, ValidationError) and any(e['type']=='string_too_long' for e in exc.errors()):
                                repair_hint = 'The previous output exceeded text length limits. Use concise wording and more short action groups; preserve critical exceptions.'
                            else:
                                repair_hint = 'Check status/value/evidence consistency: missing uses null and []; stated requires a nonempty value and evidence.'
                            raise AppError('MODEL_OUTPUT_INVALID', '模型輸出格式不符，請重試。', retryable=True) from None
                        try:
                            check_output_language(result, request.output_language)
                        except AppError:
                            repair_hint = 'The previous explanation used the wrong language. Translate ALL summary and action prose into the REQUIRED output language; only names and quotes retain source wording.'
                            raise
                        try:
                            check_wording(result)
                        except AppError:
                            repair_hint = ('Remove unsupported qualifiers: do not add expected/estimated, not guaranteed, or until further notice unless supported by the quoted source. '
                                           'A stated conditional reopening stays conditional, not estimated. Preserve the original certainty; do not invent reader actions.')
                            raise
                        result, warnings = check_evidence(result, source, request.output_language)
                    break
                except AppError as exc:
                    remaining = 65 - (time.monotonic() - start)
                    if not (exc.retryable and index == 0 and adapter.settings.llm_mode == 'live' and exc.delay < remaining):
                        raise
                    if exc.delay:
                        await asyncio.sleep(exc.delay)
            s = adapter.settings
            payload = {'result': result if baseline else result.model_dump(exclude={'card'} if result.card is None else set()), 'source': source, 'warnings': warnings,
                    'meta': {'request_id': request_id, 'source_hash': source_hash(source['text']),
                             'output_language': request.output_language, 'mode': s.llm_mode,
                             'model': s.llm_model if s.llm_mode == 'live' else 'fixed-examples',
                             'prompt_version': 'baseline-v1' if baseline else (PROMPT_VERSION if s.llm_mode == 'live' else 'fixed-examples'),
                             'generated_at': datetime.now(timezone.utc).isoformat(),
                             'latency_ms': round((time.monotonic() - start) * 1000), 'attempts': attempts,
                             'max_output_tokens': adapter.output_limit(source),
                             'usage': adapter.usage_records[usage_start:]}}
            if capture_raw:
                payload['raw_output'] = raw
            return payload
    except TimeoutError:
        error_code = 'MODEL_TIMEOUT'
        raise AppError(error_code, '解讀超過時間上限，請重試。', 504) from None
    except AppError as exc:
        error_code = exc.code
        raise
    finally:
        logger.info('request_id=%s latency_ms=%s attempts=%s error_code=%s', request_id,
                    round((time.monotonic() - start) * 1000), attempts, error_code)
