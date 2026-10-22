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
from .classification import load_rules


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
    load_rules(settings.classification_rules)
    store = Store(settings)

    @asynccontextmanager
    async def lifespan(app):
        store.start()
        yield
        store.close()

    app = FastAPI(title='Rancher Log Explorer', version='0.2.3', lifespan=lifespan,
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
        return {'status': 'ok', 'mode': 'ephemeral', 'version': '0.2.3'}

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

    @app.exception_handler(ValueError)
    async def bad_input(request, exc):
        return JSONResponse({'detail': str(exc)}, status_code=400)

    @app.get('/api/v1/bundles/{bundle_id}/overview')
    def overview(bundle_id: str):
        return store.parsed(bundle_id).overview

    @app.get('/api/v1/bundles/{bundle_id}/catalog/{kind}')
    def catalog(bundle_id: str, kind: str, limit: int = Query(50, ge=1, le=200), cursor: str = Query('', max_length=2000),
                q: str = Query('', max_length=500), namespace: str = Query('', max_length=253),
                node: str = Query('', max_length=253), status: str = Query('', max_length=100),
                scope: str = Query('', max_length=30), component: str = Query('', max_length=253),
                resource: str = Query('', max_length=253), pod: str = Query('', max_length=100),
                object_name: str = Query('', max_length=253), object_kind: str = Query('', max_length=100),
                object_uid: str = Query('', max_length=100), has_logs: bool = False, name: str = Query('', max_length=253), reason: str = Query('', max_length=253), group: str = Query('', max_length=40), directory: str = Query('', max_length=4096), component_group: str = Query('', max_length=40)):
        return store.parsed(bundle_id).catalog(kind, limit, cursor, q, namespace, node, status, scope,
                                              component, resource, pod, object_name, object_kind, object_uid, has_logs, name, reason, group, directory, component_group)

    @app.get('/api/v1/bundles/{bundle_id}/certificates')
    def certificates(bundle_id: str, limit: int = Query(50, ge=1, le=200), cursor: str = Query('', max_length=2000),
                     q: str = Query('', max_length=500), status: str = Query('', max_length=30),
                     purpose: str = Query('', max_length=30), basis: str = Query('current', max_length=20),
                     zone: str = Query('', max_length=100)):
        from .certificates import certificate_page
        return certificate_page(store.parsed(bundle_id), limit, cursor, q, status, purpose, basis, zone)

    @app.get('/api/v1/bundles/{bundle_id}/detail/{kind}/{entity_id}')
    def detail(bundle_id: str, kind: str, entity_id: str):
        return store.parsed(bundle_id).entity(kind, entity_id)

    @app.get('/api/v1/bundles/{bundle_id}/completeness')
    def completeness(bundle_id: str):
        return store.parsed(bundle_id).completeness()

    @app.get('/api/v1/bundles/{bundle_id}/files/{file_id}/info')
    def file_info(bundle_id: str, file_id: str):
        return store.parsed(bundle_id).file(file_id)

    @app.get('/api/v1/bundles/{bundle_id}/file-source')
    def file_source(bundle_id: str, path: str = Query(max_length=4096)):
        # Only indexed source paths can be resolved, never arbitrary filesystem paths.
        from .catalog import identity
        file = store.parsed(bundle_id).file(identity(path))
        if file['path'] != path:
            raise FileNotFoundError(path)
        return file

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
    def file_page(bundle_id: str, file_id: str, offset: int = Query(0, ge=0), q: str = Query('', max_length=500), direction: str = 'forward',
                  anchor: str = '', end: int | None = Query(None, ge=0)):
        return store.parsed(bundle_id).file_page(file_id, offset, q, direction, anchor, end)

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
