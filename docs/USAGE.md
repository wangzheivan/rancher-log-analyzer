# Rancher Log Explorer

中文 Rancher 官方日志采集包浏览工具。将多个节点的采集包放进一个排障案例，在浏览器查看集群资源快照、节点配置、Pod、主机信息、etcd 输出及原始日志。

React + TypeScript / FastAPI，单进程临时共享工作区。**所有访问者共用案例，服务重启会清空上传数据。** 当前版本不提供账户、自动诊断、AI 分析、跨包合并和时间对比。

原始采集日志不包含在 GitHub 仓库中。真实样本测试和浏览器验收需要自行提供采集包；不含样本时，相关后端样本测试会跳过。

## WSL 本地运行

需要 Python 3.12、Node.js 22（容器构建使用该版本）和 npm。所有命令在 WSL 中、项目根目录执行。

```bash
python3 -m venv .venv
.venv/bin/pip install -c requirements.lock -r requirements-dev.txt
npm --prefix frontend ci
npm --prefix frontend run build
.venv/bin/python server.py
```

访问 http://localhost:8080。后端开发运行 `.venv/bin/uvicorn backend.app:app --host 127.0.0.1 --port 8080 --reload`，前端开发运行 `npm --prefix frontend run dev`；Vite 将 `/api` 代理到后端。开发自动重载同样会清空临时数据。

创建案例后上传官方 `.tar.gz` / `.tgz`。多个文件会逐个上传，后台串行解压和解析。包内允许嵌套目录，但必须识别出唯一采集根目录（`summary.txt` 或 `collector-output.log`）；多个节点应分别上传。

将本地已解压的采集目录打包以供上传，不改变源文件：

```bash
python3 scripts/package-sample.py --source /path/to/extracted-bundle
# 输出 /tmp/rancher-sample.tar.gz
```

## 容器与 Kubernetes

先在 Docker Desktop 启用当前 WSL 发行版的集成，并在 WSL 登录有推送权限的 Harbor 账户：

```bash
docker login registry.example.com
export KUBE_CONTEXT=your-cluster-context
export IMAGE_REPOSITORY=registry.example.com/your-project/rancher-log-analyzer
kubectl config use-context "$KUBE_CONTEXT"
IMAGE_TAG=0.1.0-20261020-03 bash scripts/deploy.sh
```

脚本检查 Deployment 和 Service 的 Helm 归属，构建镜像、推送 Harbor，再在 显式指定的 `KUBE_CONTEXT` 上下文安装/更新独立命名空间中的同名 Release：`rancher-log-analyzer`。每次代码更新使用新的 `IMAGE_TAG`。

镜像仓库通过 `IMAGE_REPOSITORY` 指定；文档中的 `registry.example.com` 和 `192.0.2.10` 为示例占位地址，需要替换为自己的环境配置。镜像构建上下文白名单只包含应用源代码与依赖清单，排除采集日志、测试产物和凭据。

部署后通过任一可达节点访问：

`http://<可达节点 IP>:30080`。节点地址由部署环境提供，不包含在仓库中。

```bash
kubectl --context "$KUBE_CONTEXT" -n rancher-log-analyzer get pods,svc
helm --kube-context "$KUBE_CONTEXT" -n rancher-log-analyzer status rancher-log-analyzer
```

如果 Harbor 项目需要拉取认证，使用已经配置在目标命名空间的 Secret：

```bash
IMAGE_TAG=<新的镜像版本> bash scripts/deploy.sh \
  --set 'imagePullSecrets[0].name=harbor-pull'
```

镜像能否匿名拉取取决于目标仓库配置；私有项目需要配置对应的拉取凭据。应用不挂载 Kubernetes ServiceAccount 凭据，不读取实时集群数据；kubectl 仅用于安装与验收。

Chart 配置位于 `charts/rancher-log-analyzer/values.yaml`：默认 NodePort `30080`、单副本、Recreate 策略、非 root 用户、只读根文件系统、健康探针、`emptyDir` 12 GiB、内存限制 1 GiB。不依赖 PVC 或 StorageClass。**不要增加副本数或 Uvicorn worker 数**，当前会话状态为单进程内存数据。升级也会重置案例。

临时文件仅写入 `DATA_DIR/session`。启动时清空这个专用子目录，不删除 `DATA_DIR` 其他内容。不要把原始采集数据放在该子目录内。

## 限制与展示语义

| 配置环境变量 | 默认值 | Helm values |
| --- | --- | --- |
| `MAX_UPLOAD_BYTES` | 1 GiB | `limits.uploadBytes` |
| `MAX_UNPACK_BYTES` | 5 GiB | `limits.unpackBytes` |
| `MAX_SESSION_BYTES` | 10 GiB | `limits.sessionBytes` |
| `MAX_ARCHIVE_FILES` | 20,000 条归档条目，含目录 | `limits.archiveFiles` |
| `MAX_ARCHIVE_DEPTH` | 32 层 | `limits.archiveDepth` |
| `DATA_DIR` | `/tmp/rancher-log-analyzer`；容器 `/data` | 固定挂载 `/data` |
| `FRONTEND_DIR` | `frontend/dist`；容器 `/app/frontend/dist` | 镜像内置 |

会话配额统计上传暂存文件和已解压文件的实际内容字节；导入成功后删除压缩包，失败、取消和删除会释放空间。归档路径穿越、绝对路径、链接、特殊文件、重复路径、过大扩展头及 gzip 完整性错误会被拒绝。归档解压流另有上限，避免过量填充与扩展元数据。

- 主机内存、磁盘和负载只属于当前采集节点；其他节点的容量来自 Node 对象，不等于使用量。
- 每个采集包的集群快照保持独立。etcd 输出只代表采集到的端点；缺失数据不推断为健康。
- Completed 不计为异常 Pod；历史重启次数只展示，不直接判为当前故障。
- 当前样本验证了 RKE2；K3s、RKE、kubeadm 按相应目录布局发现数据，尚未经过这些发行版真实样本验收。
- 结构化资源表每个预览最多读取 256 KiB，累计预算 16 MiB；超出预算会提示查看原文。主机与 etcd 卡片原文各预览 8 KiB，完整内容从“查看原文”读取。
- 文件内容每次最多扫描 2 MiB、返回 250 条，长行按最多 64 KiB 分段，支持跨分段和跨读取页的关键字匹配。无匹配但还有内容时可继续搜索。二进制文件仅展示元信息；非法 UTF-8 字节使用替换字符。
- 首屏仅请求摘要、结构化数据和文件索引，不载入 Pod、journald 等完整日志；单文件搜索不建立全文索引。

## API 与扩展

API 前缀 `/api/v1`；接口定义可通过 `/openapi.json` 查看，无外部 CDN 文档页面。

| 接口 | 用途 |
| --- | --- |
| `GET /health`、`GET /session` | 健康与配额 |
| `GET/POST /cases`、`PATCH/DELETE /cases/{id}` | 案例管理 |
| `POST /cases/{id}/bundles?filename=node.tar.gz` | 原始二进制请求体流式上传，响应 202 |
| `GET/DELETE /bundles/{id}` | 导入状态或删除/取消 |
| `GET /bundles/{id}/summary` | 当前包摘要与文件索引 |
| `GET /bundles/{id}/nodes`、`/pods` | 结构化节点与 Pod |
| `GET /bundles/{id}/resources/{name}` | 资源表与原文来源 |
| `GET /bundles/{id}/files/{fileId}?offset=0&q=error` | 文件分块读取与单文件搜索 |

文件标识由摘要索引提供，客户端不能指定服务端文件路径。导入状态为 `uploading → queued → extracting → parsing → ready`，失败为 `failed`；删除执行取消并清理。

解析与浏览逻辑位于 `backend/parsers`，导入安全处理位于 `backend/archive.py`，会话与任务管理位于 `backend/store.py`。后续诊断规则可消费解析结果与来源路径，不需要将 UI 与分析逻辑耦合。

## 测试

```bash
.venv/bin/python -m pytest -q
npm --prefix frontend run build
helm lint charts/rancher-log-analyzer
helm template rancher-log-analyzer charts/rancher-log-analyzer >/tmp/rancher-log-chart.yaml

# 安装一次 WSL 浏览器及运行依赖
cd frontend
npx playwright install --with-deps chromium
cd ..
python3 scripts/package-sample.py --source /path/to/extracted-bundle
python3 scripts/make-test-fixture.py
# 保持本地后端在 8080 运行，另开 WSL 终端
npm --prefix frontend run test:e2e
```

浏览器测试创建、重命名并删除自己创建的案例；建议在空白测试工作区运行。真实样本测试只在项目存在原始样本目录时执行，否则跳过。截图写入 `artifacts/`；失败保留 Playwright trace。

在实际集群运行同样的浏览器验收：

```bash
E2E_BASE_URL=http://192.0.2.10:30080 npm --prefix frontend run test:e2e
```

重启清空验证在空白验收工作区中执行：

```bash
.venv/bin/python scripts/verify-cluster.py \
  --context "$KUBE_CONTEXT" --base-url http://192.0.2.10:30080
```

脚本创建自己的验收案例并上传真实样本，通过终止应用进程触发同一个 Pod 内的容器重启，验证 emptyDir 仍在时旧会话也被清空。工作区已有案例时拒绝执行，完成后可再导入演示数据。

官方采集器：[使用说明](https://github.com/rancherlabs/support-tools/tree/master/collection/rancher/v2.x/logs-collector)、[采集范围](https://github.com/rancherlabs/support-tools/blob/master/collection/rancher/v2.x/logs-collector/collection-details.md)。
