LABELS = {
    'zh-Hant': ['事項', '對象', '活動／服務時間', '報名截止', '地點', '費用', '辦理方式', '條件與限制'],
    'en': ['Subject', 'Audience', 'Event / service time', 'Registration deadline', 'Location', 'Fee', 'Method', 'Conditions'],
}
DISCLAIMER = {
    'zh-Hant': '本工具協助理解通知，重要日期、費用及資格請以原通知或主辦方回覆為準。',
    'en': 'This tool helps explain notices. Confirm important dates, fees and eligibility with the original notice or organizer.',
}


def format_result(payload, request):
    lang = request.output_language
    en = lang == 'en'
    m, r = payload['meta'], payload['result']
    out = ['明白通 ClearNotice HK', f"{'Language' if en else '輸出語言'}: {lang}",
           f"{'Source' if en else '來源'}: {request.source_label or ('User-provided notice' if en else '使用者提供的通知')}",
           f"URL: {request.source_url or '—'}", f"Mode: {m['mode']} · Model: {m['model']}",
           f"Generated: {m['generated_at']}", f"Request: {m['request_id']}", f"SHA-256: {m['source_hash']}", '']

    def evidence(items):
        return [f"  [{e['line_id']}] {e['quote']}" for e in items]

    out.append('Overview' if en else '一句話概覽')
    for item in r['summary']:
        out.extend([item['text'], *evidence(item['evidence'])])
    out.extend(['', 'Key information' if en else '關鍵資訊'])
    for label, fact in zip(LABELS[lang], r['facts'].values()):
        value = fact['value'] if fact['status'] == 'stated' else (
            ('Not stated in the notice' if en else '原文未說明') if fact['status'] == 'missing' else
            ('Needs checking' if en else '需要核對原文'))
        out.extend([f'{label}: {value}', *evidence(fact['evidence'])])
    out.extend(['', 'Actions' if en else '行動清單'])
    if not r['actions']:
        out.append('No required steps stated in the notice.' if en else '原文未列出需要辦理的步驟。')
    for item in r['actions']:
        out.extend([item['text'], *evidence(item['evidence'])])
    out.extend(['', 'Checks / advice' if en else '需要核對的地方／工具建議'])
    out.extend(w['message'] for w in payload['warnings'])
    out.extend(['', 'Source quotes were found; this does not verify the interpretation.' if en else
                '已找到原文引句，不代表解釋已獲語義驗證。', DISCLAIMER[lang], '', 'Original notice' if en else '原文'])
    out.extend(f"[{line['line_id']}] {line['text']}" for line in payload['source']['lines'])
    return '\n'.join(out)
