import asyncio
import json
import hmac
from uuid import uuid4

from fastapi import FastAPI, Request, Depends
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import ROOT, Settings
from .errors import AppError
from .formatting import DISCLAIMER, LABELS, format_result
from .llm import Adapter
from .pipeline import analyze
from .schemas import AnalyzeRequest, ImportRequest
from .web_import import import_page


def create_app(settings=None, adapter=None):
    settings = settings or Settings()
    app = FastAPI(title='明白通 ClearNotice HK', docs_url=None, redoc_url=None)
    app.state.adapter = adapter or Adapter(settings)
    semaphore = asyncio.Semaphore(2)
    import_semaphore = asyncio.Semaphore(2)
    templates = Jinja2Templates(directory=ROOT / 'app/templates')
    app.mount('/static', StaticFiles(directory=ROOT / 'app/static'), name='static')
    if (ROOT / 'submission').is_dir():
        app.mount('/submission', StaticFiles(directory=ROOT / 'submission', html=True), name='submission')

    @app.middleware('http')
    async def bounded_body(request: Request, call_next):
        request.state.request_id = str(uuid4())
        if request.method == 'POST':
            # Bound body before JSON parsing, including chunked requests.
            data = bytearray()
            async for chunk in request.stream():
                data.extend(chunk)
                # JSON surrogate escapes for 12,000 code points need up to 144 KiB.
                if len(data) > 192 * 1024:
                    return JSONResponse({'error': {'code': 'INPUT_INVALID', 'message': '輸入過大，請縮短通知。'},
                                         'request_id': request.state.request_id}, status_code=422)
            request._body = bytes(data)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, _exc):
        return JSONResponse({'error': {'code': 'INPUT_INVALID', 'message': '請檢查通知文字長度（30至12000字）、語言及網頁連結（僅限http/https）。'},
                             'request_id': request.state.request_id}, status_code=422)

    @app.exception_handler(AppError)
    async def app_error(request, exc):
        return JSONResponse({'error': {'code': exc.code, 'message': exc.message},
                             'request_id': request.state.request_id}, status_code=exc.status)

    @app.exception_handler(Exception)
    async def unexpected_error(request, _exc):
        return JSONResponse({'error': {'code': 'INTERNAL_ERROR', 'message': '暫時無法解讀，請重試。'},
                             'request_id': request.state.request_id}, status_code=500)

    @app.get('/')
    async def index(request: Request):
        examples = []
        for path in sorted((ROOT / 'data/demo_notices').glob('*.json')):
            f = json.loads(path.read_text(encoding='utf-8'))
            examples.append({'id': path.stem, 'title': f['title'], 'text': f['text']})
        return templates.TemplateResponse(request=request, name='index.html', context={
            'mode': settings.llm_mode, 'examples': examples, 'labels': LABELS, 'disclaimers': DISCLAIMER})

    @app.get('/health')
    async def health():
        return {'status': 'ok', 'mode': settings.llm_mode, 'image_input': False, 'web_input': True}

    async def extension_auth(request: Request):
        # A local pairing key, never shipped inside the extension or sent to the model.
        token_path = ROOT / '.extension-token'
        if not token_path.exists():
            raise AppError('EXTENSION_NOT_PAIRED', '請先執行 scripts/build_extension.py，然後在插件設定配對。', 503)
        expected = token_path.read_text(encoding='utf-8').strip()
        supplied = request.headers.get('X-ClearNotice-Token', '')
        if len(expected) < 32 or not hmac.compare_digest(supplied.encode(), expected.encode()):
            raise AppError('EXTENSION_AUTH_FAILED', '插件尚未配對，請在插件設定填入本機配對碼。', 401)

    @app.get('/api/extension/health', dependencies=[Depends(extension_auth)])
    async def extension_health():
        return {'status': 'ok', 'mode': settings.llm_mode, 'model': settings.llm_model if settings.llm_mode == 'live' else 'fixed-examples'}

    @app.post('/api/import-url')
    async def import_notice(body: ImportRequest):
        try:
            async with asyncio.timeout(20):
                async with import_semaphore:
                    return await import_page(body.url)
        except TimeoutError:
            raise AppError('WEB_TIMEOUT', '讀取網頁逾時，請重試或改貼通知文字。', 504) from None

    @app.post('/api/extension/analyze', dependencies=[Depends(extension_auth)])
    @app.post('/api/analyze')
    async def analyze_notice(body: AnalyzeRequest, request: Request):
        try:
            async with asyncio.timeout(65):
                async with semaphore:
                    base = app.state.adapter
                    # Keep usage state local to this request while sharing a call budget.
                    active = Adapter(base.settings, transport=base.transport, budget=base.budget)
                    payload = await analyze(body, active, request_id=request.state.request_id)
        except TimeoutError:
            raise AppError('MODEL_TIMEOUT', '解讀超過時間上限，請重試。', 504) from None
        payload['copy_text'] = format_result(payload, body)
        return payload

    return app


app = create_app()
