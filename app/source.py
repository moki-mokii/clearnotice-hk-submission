import hashlib
import unicodedata


def normalize(text: str) -> str:
    return unicodedata.normalize('NFC', text.replace('\r\n', '\n').replace('\r', '\n')).strip()


def make_source(text: str) -> dict:
    text = normalize(text)
    return {'text': text, 'lines': [{'line_id': f'L{i:04d}', 'text': line}
                                  for i, line in enumerate(text.split('\n'), 1)]}


def source_hash(text: str) -> str:
    return hashlib.sha256(normalize(text).encode('utf-8')).hexdigest()
