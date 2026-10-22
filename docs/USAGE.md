# Rancher Log Explorer

中文 Rancher 官方日志采集包浏览工具。将多个节点的采集包放进一个排障案例，在浏览器查看集群资源快照、节点配置、Pod、主机信息、etcd 输出及原始日志。

React + TypeScript / FastAPI，单进程临时共享工作区。**所有访问者共用案例，服务重启会清空上传数据。** 当前版本不提供账户、自动诊断、AI 分析、跨包合并和时间对比。

原始采集日志不包含在 GitHub 仓库中。浏览器回归使用可生成的合成采集包；不含原始样本时，相关后端真实样本测试会跳过。

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
IMAGE_TAG="0.2.1-$(date +%Y%m%d-%H%M%S)" bash scripts/deploy.sh
```

脚本检查 Deployment 和 Service 的 Helm 归属，构建镜像、推送 Harbor，再在 显式指定的 `KUBE_CONTEXT` 上下文安装/更新独立命名空间中的同名 Release：`rancher-log-analyzer`。每次代码更新使用新的 `IMAGE_TAG`。发布时先推送具体版本，再将同一镜像推送为 `latest`；每次覆盖 `latest`，具体版本标签保持唯一、不重复覆盖。`IMAGE_TAG` 不允许填写 `latest`。Helm 继续引用具体版本；Docker 使用 `latest` 时，更新前先执行 `docker pull <仓库/镜像>:latest`，再重建容器。

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

Chart 配置位于 `charts/rancher-log-analyzer/values.yaml`：默认 NodePort `30080`、单副本、Recreate 策略、非 root 用户、只读根文件系统、健康探针、`emptyDir` 12 GiB、内存限制 1 GiB。不依赖 PVC 或 StorageClass。**不要增加副本数或 Uvicorn worker 数**，案例与任务状态保存在单进程内存，资源元数据保存于临时 SQLite。升级也会重置案例。

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

会话配额统计上传暂存文件、已解压文件和元数据索引的实际内容字节；导入成功后删除压缩包，失败、取消和删除会释放空间。归档路径穿越、绝对路径、链接、特殊文件、重复路径、过大扩展头及 gzip 完整性错误会被拒绝。归档解压流另有上限，避免过量填充与扩展元数据。

- 主机内存、磁盘和负载只属于当前采集节点；其他节点的容量来自 Node 对象，不等于使用量。
- 每个采集包的集群快照保持独立。etcd 输出只代表采集到的端点；缺失数据不推断为健康。
- Completed 不计为异常 Pod；历史重启次数只展示，不直接判为当前故障。
- 当前样本验证了 RKE2；K3s、RKE、kubeadm 按相应目录布局发现数据，尚未经过这些发行版真实样本验收。
- 新页面从增量解析的完整元数据索引分页查询，不沿用旧资源预览截断。单个 JSON 对象上限4 MiB、字符串上限256 KiB、嵌套最多64层；无法完整解析会提示并使用可用文本回退。主机与 etcd 卡片原文各预览 8 KiB，完整内容从“查看原文”读取。
- 文件内容每次最多扫描 2 MiB、返回 250 条，长行按最多 64 KiB 分段，支持跨分段和跨读取页的关键字匹配。无匹配但还有内容时可继续搜索。二进制文件仅展示元信息；非法 UTF-8 字节使用替换字符。
- 首屏仅请求轻量概览，文件与资源目录按页查询，不载入 Pod、journald 等完整日志；单文件搜索不建立全文索引。

## API 与扩展

API 前缀 `/api/v1`；接口定义可通过 `/openapi.json` 查看，无外部 CDN 文档页面。

| 接口 | 用途 |
| --- | --- |
| `GET /health`、`GET /session` | 健康与配额 |
| `GET/POST /cases`、`PATCH/DELETE /cases/{id}` | 案例管理 |
| `POST /cases/{id}/bundles?filename=node.tar.gz` | 原始二进制请求体流式上传，响应 202 |
| `GET/DELETE /bundles/{id}` | 导入状态或删除/取消 |
| `GET /bundles/{id}/summary` | 旧兼容全量摘要，常规页面不使用 |
| `GET /bundles/{id}/nodes`、`/pods` | 结构化节点与 Pod |
| `GET /bundles/{id}/resources/{name}` | 资源表与原文来源 |
| `GET /bundles/{id}/files/{fileId}?offset=0&q=error` | 文件分块读取与单文件搜索 |

文件标识由分页目录索引提供，客户端不能指定服务端文件路径。导入状态为 `uploading → queued → extracting → parsing → indexing → ready`，失败为 `failed`；删除执行取消并清理。

元数据目录逻辑位于 `backend/catalog.py`，格式解析位于 `backend/parsers`，导入安全处理位于 `backend/archive.py`，会话与任务管理位于 `backend/store.py`。后续诊断规则可消费解析结果与来源路径，不需要将 UI 与分析逻辑耦合。

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
python3 scripts/make-scale-fixture.py
python3 scripts/make-test-fixture.py
# 保持本地后端在 8080 运行，另开 WSL 终端
npm --prefix frontend run test:e2e
```

浏览器测试创建并删除自己创建的合成案例；建议在空白测试工作区运行。真实样本测试只在项目存在原始样本目录时执行，否则跳过。截图写入 `artifacts/`；失败保留 Playwright trace。

在恢复后的实际工作区运行只读浏览器验收（预期日志数按复现包调整）：

```bash
EXISTING_WORKSPACE=1 EXPECTED_NESTED_LOGS=8 E2E_BASE_URL=http://192.0.2.10:30080 \
  npm --prefix frontend run test:e2e -- reproduction.spec.ts
```

重启清空验证在空白验收工作区中执行：

```bash
.venv/bin/python scripts/verify-cluster.py \
  --context "$KUBE_CONTEXT" --base-url http://192.0.2.10:30080
```

脚本创建自己的验收案例并上传真实样本，通过终止应用进程触发同一个 Pod 内的容器重启，验证 emptyDir 仍在时旧会话也被清空。工作区已有案例时拒绝执行，完成后可再导入演示数据。

官方采集器：[使用说明](https://github.com/rancherlabs/support-tools/tree/master/collection/rancher/v2.x/logs-collector)、[采集范围](https://github.com/rancherlabs/support-tools/blob/master/collection/rancher/v2.x/logs-collector/collection-details.md)。

## 0.2 展示增强与分页索引

Pod 工作负载的日志按钮跳转到独立 Pod 日志页。命名空间和 Pod 候选项由服务端搜索，每页50项；默认只列有采集日志的对象，也可以包含无日志 Pod。已从资源快照消失的 Pod 按日志中的 UID 单独保留。“未关联日志”展示无法唯一识别归属的文件。业务日志、系统/平台日志与未分类日志可分别筛选。

支持官方扁平 `命名空间-Pod`、`-previous` 文件，以及 `命名空间_Pod_UID/容器/实例号.log` 和未压缩轮转文件。扁平文件依据清单唯一匹配，容器不明确时显示“合并日志”；嵌套文件保留 UID、容器与实例号，默认选较大实例号，不将其推断为实时运行实例。旧 UID 不关联到同名新 Pod。压缩或二进制源文件只展示位置与元信息。

日志默认从末尾读取最多250条；支持开头、末尾、前后读取和不区分大小写的单文件搜索。每次最多扫描2 MiB，无匹配时可以沿游标继续。超长行分段标识，不在浏览器累积完整日志，不建立全文索引。组件与系统日志页复用同一阅读器，按节点、组件或文件名筛选。

Pod / Node 详情优先读取 JSON，使用 Describe 的对象区间补充。详情包含容器和 Init Container、镜像、探针、资源请求/限制、挂载、调度及 Conditions（以采集内容为准）。未提供的字段明确标记；详情原文入口从对应对象区间开始读取。Node 的关联 Pod 按页加载。详情返回保留 URL 中的列表筛选和分页；关联事件优先按 UID，只有名称时明确标注，原始相对时间不转换为绝对时间。

采集完整性按资源、详情与事件、Pod 日志、组件日志、主机、网络、etcd 和配置分类。状态区分已采集、有效无数据、部分可用、失败、未发现、不适用和无法判断；不适用需有采集输出依据，未发现不会解释为不适用或健康。Pod 日志覆盖数量不等于健康率。

元数据保存于每包独立的临时 SQLite 数据库；JSON 增量读取、文本按行处理，不使用旧预览截断内容作索引。导入失败不会把不完整清单报告为完整。原始采集内容不修改。数据库、解压文件和上传临时文件均计入会话配额。索引预留默认128 MiB，成功后按实际大小结算；超过预算导入失败并清理。仍然要求单进程和串行导入。

新增环境变量：

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `MAX_INDEX_BYTES` | `134217728` | 每包元数据索引预算 |
| `LOG_CLASSIFICATION_RULES` | `[]` | 日志分类规则 JSON 数组 |

显式分类规则优先于内置规则，同一规则中条件为 AND、规则按顺序匹配，使用精确命名空间和名称前缀，避免运行自定义正则表达式：

```bash
docker run -d --name rancher-log-analyzer -p 8080:8080 \
  --cpus=2 --memory=1g \
  -e MAX_INDEX_BYTES=134217728 \
  -e LOG_CLASSIFICATION_RULES='[{"namespace":"platform","scope":"system"},{"podPrefix":"shop-","scope":"business"}]' \
  rancher-log-analyzer:local
```

Helm 中使用 `limits.indexBytes` 和 `logClassificationRules`：

```yaml
limits:
  indexBytes: "134217728"
logClassificationRules:
  - namespace: platform
    scope: system
  - componentPrefix: kubelet
    scope: system
```

### 新分页接口

`GET /api/v1/bundles/{id}/overview` 只返回有上限的概览；常规页面和案例轮询不调用旧全量摘要接口。

`GET /api/v1/bundles/{id}/catalog/{kind}` 支持 `pods`、`nodes`、`namespaces`、`logPods`、`logs`、`components`、`events`、`resources`、`files`。返回 `items、total、nextCursor、previousCursor`；默认50条、最多200条。游标绑定筛选条件，改变条件后从首页查询。支持 `q、namespace、node、status、scope、component、resource、pod、name、object_kind、object_name、object_uid、has_logs`，按类别适用。`pod=unassociated` 查询未关联日志。

`GET /api/v1/bundles/{id}/detail/{pods|nodes}/{entityId}` 返回摘要、结构化对象与 Describe 来源区间。

`GET /api/v1/bundles/{id}/completeness` 返回完整性分组及有上限的来源示例。

`GET /api/v1/bundles/{id}/files/{fileId}` 支持 `direction=forward|backward`、`anchor=start|end`、`offset`、`end`、`q`；返回双向字节游标。文件必须先通过索引定位，禁止任意路径访问。旧只读接口保留兼容，只有主动调用时才组装完整结果。

### 可重复验收

```bash
python3 scripts/make-scale-fixture.py
python3 scripts/make-test-fixture.py
# 启动专用测试容器；不要对正在使用的容器执行测试清理。
docker run -d --name rancher-validation --cpus=2 --memory=1g \
  -p 127.0.0.1:18080:8080 rancher-log-analyzer:local
python3 scripts/accept-scale.py
E2E_BASE_URL=http://127.0.0.1:18080 npm run test:e2e --prefix frontend
docker rm -f rancher-validation
```

规模脚本创建合成案例并在完成后删除。测量结果写入 Git 忽略的 `artifacts/`。浏览器测试使用合成采集包，截图与 trace 也不提交。

### 升级前备份

服务仍使用共享临时会话；升级会清空数据。可先将现有案例和采集根目录导出到 Git 忽略目录，再升级并重导入：

```bash
python3 scripts/backup-workspace.py --context "$KUBE_CONTEXT" \
  --base-url "http://<节点IP>:30080" --output .data/upgrade-backup
# 执行升级，确认服务为空工作区后：
python3 scripts/restore-workspace.py --base-url "http://<节点IP>:30080" \
  --input .data/upgrade-backup
```

备份脚本匹配完整文件清单；同名目录重复时，只有全部文件内容 SHA256 一致才视为可互换副本，否则停止升级。每个案例及采集包仍分别保留记录；恢复脚本仅允许恢复到空工作区。备份包含原始采集数据，必须保留在私有本地目录。它不改变临时会话模式。

分类路径依据 [Rancher 官方采集脚本](https://github.com/rancherlabs/support-tools/blob/master/collection/rancher/v2.x/logs-collector/rancher2_logs_collector.sh)。官方脚本的扁平日志来自 `kubectl logs --all-containers`，本地 CRI 目录用于 Agent/API 不可用等采集分支；页面不把这些来源解释为实时集群信息。

## 0.2.1 展示体验调整

概览上方默认显示“案例内采集包”，每页10份，包含采集节点、时间、状态与解压体积；可切换、删除或取消导入。其他页面通过“管理采集包”展开。“新建案例”保持独立可见。切换案例或采集包清空包内筛选、目录和日志选择；同包详情返回恢复原有筛选与分页。

节点恢复卡片展示，每页12张；搜索支持名称和采集到的 IP。卡片展示容量、可分配资源、系统版本、Conditions 和关联 Pod 数量，点击名称进入详情。资源快照恢复左侧类型数量、右侧搜索表格；类型和记录分别分页。存在有效文本采集表时使用原始列，JSON 继续优先用于 Pod/Node 详情；只有 JSON 时使用稳定的展示列。搜索覆盖可见资源列，不将索引内部字段作为列展示。

独立事件页面已移除，详情中的关联事件每页10条；旧事件页链接转到资源快照的 events 类别。事件元数据接口仍兼容，原始文件保持可访问。

原始文件分为采集元信息、主机、网络、资源清单、资源详情、Pod日志、组件日志、运行时、etcd、配置与证书、其他；每个文件只属于一个用途，总数和体积覆盖全部采集文件。用途、目录前缀和路径关键字可组合筛选，文件每页50条；目录按展开查询下级，不传输整棵目录树。分类显示全包数量与体积，目录统计按所选用途计算，文件结果显示组合筛选后的数量与体积。

命名空间按名称排序，以清单、资源对象、有效 Describe 对象和可识别日志为依据。只有采集器预设的 Describe 文件名、不含对象的输出不会被当作真实命名空间；没有日志的有效命名空间仍可选择。候选项每页50条，可以直接搜索后续页中的名称。

普通 Linux 文件名中的冒号（例如 `etcd-metrics-127.0.0.1:2381.txt`）已兼容；盘符路径、绝对路径、路径穿越、反斜杠、链接和特殊文件仍拒绝。无需修改原压缩包或重命名采集文件。

分页接口补充：

- `/catalog/fileGroups`：用途分类、文件数与字节数。
- `/catalog/fileDirectories?directory=rke2&group=podLogs`：指定目录下的子目录及其匹配文件统计。
- `/catalog/files?group=podLogs&directory=rke2/podlogs&q=keyword`：组合筛选；`bytes` 为匹配结果总大小。
- `/catalog/nodes?q=192.0.2.10&limit=12`：名称/IP 搜索，记录包含 `podCount`。
- `/catalog/resources?resource=pods`：响应附带 `columns、source、state、note`，列顺序与表格来源保持一致。

所有新目录接口仍返回 `items、total、nextCursor、previousCursor`，最大页长200，不读取日志全文。

浏览器体验回归默认使用合成包；设置 `UX_ARCHIVE` 可改用私有真实样本（测试约定为324文件、76 Pod、3节点、14命名空间、112个Pod日志文件）：

```bash
UX_ARCHIVE=/path/to/private-bundle.tar.gz E2E_BASE_URL=http://127.0.0.1:18080 \
  npm --prefix frontend run test:e2e -- ux.spec.ts
```

测试只删除自己创建的案例。真实包、备份、界面截图和部署参数不得提交公开仓库。

## macOS 文件选择兼容

文件选择窗口不再使用复合扩展名 `accept` 过滤，以避免 macOS Chrome / Edge 原生类型匹配把合法 `.tar.gz` 文件置灰。窗口会显示所有文件，选择后仍只接受 `.tar.gz` / `.tgz`（扩展名不区分大小写），并校验上传大小；错误格式提示具体文件名，不发送请求。不依赖浏览器给出的 MIME 类型。

请选择未解压的原始采集包；`.tar` 和文件夹仍不支持。后端的 gzip/tar 内容验证、解包安全和配额限制继续生效，改后缀不能绕过校验。

WSL 浏览器自动化覆盖选择后的上传与校验，不能代替 macOS 原生文件选择器验收。部署后需要在 Mac Chrome / Edge 中点击“上传采集包”，确认原包可选并完成上传。


## 状态、组件来源与证书检查（0.2.3）

Pod 状态使用固定颜色：Running 绿色，Completed/Succeeded 蓝色，等待、初始化及终止中橙色，失败或错误红色，未知灰色。Running 但容器未全部就绪时单独提示；历史重启次数不直接表示当前故障。

Pod 日志文件列表以 Pod 名称和命名空间为主，容器与实例信息为辅。官方扁平日志通常由采集器合并该 Pod 的所有容器输出，因此显示“未区分容器”，不推断实际容器；当前、上一次、CRI 采集实例及原始路径继续保留。

“组件与系统日志”按 Kubernetes 核心、RKE2/K3s 服务、容器运行时、主机系统、网络与 DNS、Rancher 管理分组。识别采用明确服务名、目录及受约束的 Pod 名称，不把整个系统命名空间全部纳入；监控、Fleet、NeuVector 等其他平台 Pod 仍在 Pod 页。核心组件 Pod 的两个入口引用同一文件，不拼接正文。`-- No entries --` 表示有效无记录，二进制 sysstat 文件只显示元信息。原有 `LOG_CLASSIFICATION_RULES` 仍控制 Pod 的系统/业务范围，不把自定义范围当作核心组件身份。

新增接口：

- `GET /api/v1/bundles/{id}/catalog/componentLogs`：组件文件分页，支持 `component_group`、`node`、`component`、`q`；`catalog/components` 支持分组和节点候选过滤。
- 日志新增 `componentGroup`、`serviceComponent`、`sourceType`、`componentReason`，原有日志及原文接口继续保留。
- `GET /api/v1/bundles/{id}/certificates`：分页参数 `limit`（默认50，最多200）、`cursor`、`q`、`status`、`purpose`、`basis=current|collected`、`zone`（IANA 时区）。响应包含 `items/total/nextCursor/previousCursor`、整体状态 `counts`、`checkedAt`、`referenceTime` 和 `referenceMessage`。状态为 `valid/expiring/expired/notYetValid/unknown`，用途为 `ca/client/server/other`；统计是整个包在所选时间基准下的数量，不随列表筛选变化。

证书仅从 `certs` 目录的 `.crt/.cer/.pem` 候选文件解析 OpenSSL 文本；PEM/DER 等未支持的内容保留无法判断提示。每文件解析最多1 MiB，多证书分别编号，索引纳入原有配额。展示 CA、Subject、Issuer、SAN、生效及到期时间；不解析私钥，不验证证书链、吊销、密钥匹配或在线使用情况。

证书以 UTC 判断和展示：到期时刻即为已过期，90天内到期含第90天边界，生效时刻起有效。剩余天数向下取整；临近到期不代表已过期。默认用服务端当前时间，每次新查询重新计算；同一次分页固定检查时刻，点击“刷新检查”返回第一页并重算。历史判断优先使用包中明确时区或偏移；`CST` 等歧义缩写不会猜测，需在页面输入如 `Asia/Shanghai` 的时区。夏令时歧义或不存在的本地时间拒绝判断。

合成展示回归包可通过 `python3 scripts/make-display-fixture.py` 生成，浏览器测试前还需生成已有 `make-scale-fixture.py` 和 `make-test-fixture.py` 的测试包；全部为合成数据。

macOS 文件选择兼容已由用户在 Mac Chrome 和 Edge 原生窗口复测：可以正常选择并上传采集包。
