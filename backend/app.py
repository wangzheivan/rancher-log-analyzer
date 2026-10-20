from contextlib import asynccontextmanager
from pathlib import Path
import asyncio
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from starlette.requests import ClientDisconnect

from .archive import ImportFailure
from .config import Settings
from .store import Store


class CaseName(BaseModel):
    name: str = Field(min_length=1, max_length=100)

    @field_validator('name')
    @classmethod
    def trim(cls, value):
        if not value.strip():
            raise ValueError('案例名称不能为空')
        return value.strip()


def create_app(settings=None):
    settings = settings or Settings()
    store = Store(settings)

    @asynccontextmanager
    async def lifespan(app):
        store.start()
        yield
        store.close()

    app = FastAPI(title='Rancher Log Explorer', version='0.1.0', lifespan=lifespan,
                  docs_url=None, redoc_url=None)
    app.state.store = store

    @app.middleware('http')
    async def headers(request, call_next):
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'"
        return response

    @app.exception_handler(FileNotFoundError)
    async def missing(request, exc):
        return JSONResponse({'detail': '案例、采集包或文件不存在'}, status_code=404)

    @app.exception_handler(ImportFailure)
    async def invalid(request, exc):
        return JSONResponse({'detail': str(exc)}, status_code=409)

    @app.get('/api/v1/health')
    def health():
        return {'status': 'ok', 'mode': 'ephemeral', 'version': '0.1.0'}

    @app.get('/api/v1/session')
    def session():
        with store.lock:
            return {'usedBytes': store.used, 'maxSessionBytes': settings.session_limit,
                    'maxUploadBytes': settings.upload_limit, 'maxUnpackBytes': settings.unpack_limit,
                    'ephemeral': True, 'shared': True}

    @app.get('/api/v1/cases')
    def cases():
        with store.lock:
            return [{**c, 'bundles': [r.public() for r in store.records.values() if r.case_id == c['id']]} for c in store.cases.values()]

    @app.post('/api/v1/cases', status_code=201)
    def create_case(body: CaseName):
        return store.create_case(body.name)

    @app.patch('/api/v1/cases/{case_id}')
    def rename(case_id: str, body: CaseName):
        with store.lock:
            case = store.case(case_id)
            case['name'] = body.name
            return dict(case)

    @app.delete('/api/v1/cases/{case_id}', status_code=204)
    def delete_case(case_id: str):
        store.delete_case(case_id)

    @app.post('/api/v1/cases/{case_id}/bundles', status_code=202)
    async def upload(case_id: str, request: Request, filename: str = Query(min_length=1, max_length=255)):
        if not filename.lower().endswith(('.tar.gz', '.tgz')):
            raise HTTPException(400, '仅支持 .tar.gz 或 .tgz 采集包')
        length = request.headers.get('content-length')
        if length and (not length.isdigit() or int(length) > settings.upload_limit):
            raise HTTPException(413, '压缩包大小超过限制')
        record = store.begin(case_id, Path(filename).name)
        try:
            # Raw request streaming avoids an unaccounted multipart spool file.
            with (record.folder / 'upload.tar.gz').open('wb') as output:
                async for chunk in request.stream():
                    if record.received + len(chunk) > settings.upload_limit:
                        raise HTTPException(413, '压缩包大小超过限制')
                    store.reserve(record, len(chunk))
                    await asyncio.to_thread(output.write, chunk)
                    record.received += len(chunk)
            store.enqueue(record)
            return record.public()
        except BaseException as exc:
            store.fail(record, '上传中断或大小超过限制，请重新上传')
            if isinstance(exc, ClientDisconnect):
                raise HTTPException(400, '上传连接已中断') from exc
            raise

    @app.get('/api/v1/bundles/{bundle_id}')
    def bundle_status(bundle_id: str):
        return store.get(bundle_id).public()

    @app.delete('/api/v1/bundles/{bundle_id}', status_code=204)
    def delete_bundle(bundle_id: str):
        store.delete_bundle(bundle_id)

    @app.get('/api/v1/bundles/{bundle_id}/summary')
    def summary(bundle_id: str):
        return store.parsed(bundle_id).summary

    @app.get('/api/v1/bundles/{bundle_id}/nodes')
    def nodes(bundle_id: str):
        return store.parsed(bundle_id).summary['nodes']

    @app.get('/api/v1/bundles/{bundle_id}/pods')
    def pods(bundle_id: str):
        return store.parsed(bundle_id).summary['pods']

    @app.get('/api/v1/bundles/{bundle_id}/resources/{name}')
    def resource(bundle_id: str, name: str):
        bundle = store.parsed(bundle_id)
        if name not in bundle.resources:
            raise FileNotFoundError(name)
        return bundle.resources[name]

    @app.get('/api/v1/bundles/{bundle_id}/files/{file_id}')
    def file_page(bundle_id: str, file_id: str, offset: int = Query(0, ge=0), q: str = Query('', max_length=500)):
        return store.parsed(bundle_id).file_page(file_id, offset, q)

    assets = settings.frontend_dir / 'assets'
    if assets.is_dir():
        app.mount('/assets', StaticFiles(directory=assets), name='assets')

    @app.get('/')
    def index():
        path = settings.frontend_dir / 'index.html'
        if not path.is_file():
            raise HTTPException(503, '前端尚未构建，请运行 npm run build')
        return FileResponse(path)

    return app

app = create_app()
