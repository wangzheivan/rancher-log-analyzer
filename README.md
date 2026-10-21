# Rancher Log Explorer

Rancher 官方日志采集包的中文可视化工具，支持：

- 按案例管理多个节点的采集包，上传 `.tar.gz` / `.tgz` 文件。
- 案例内采集包管理、可搜索的节点卡片、Pod / Node 详情、关联事件与资源快照。
- 独立 Pod 日志页支持命名空间与 Pod 搜索、容器实例选择；组件日志与业务日志分类展示。
- 查看采集完整性；SQLite 临时索引支持大规模清单的服务端分页。
- 按用途分类和原始目录浏览文件，分块读取大日志并搜索关键字。

详细的本地开发、配置、API 和测试说明见 [使用与开发说明](docs/USAGE.md)。

## Docker 部署

安装 Docker 后，在项目根目录构建镜像并启动容器：

```bash
docker build -t rancher-log-analyzer:local .

docker run -d \
  --name rancher-log-analyzer \
  --restart unless-stopped \
  --cpus=2 --memory=1g \
  -p 8080:8080 \
  rancher-log-analyzer:local
```

访问 `http://localhost:8080`；部署在服务器上时，通过 `http://<服务器IP>:8080` 访问。已有镜像时，将命令中的 `rancher-log-analyzer:local` 替换为完整镜像地址即可，私有仓库需先执行 `docker login <镜像仓库地址>`。

临时数据保存在容器内 `/data`，容器重启会清空。上传与解压大小等配置可通过 `docker run -e` 设置，详见 [配置说明](docs/USAGE.md#限制与展示语义)。

## Kubernetes 部署

准备可访问集群的 `kubectl`、Helm，以及可供节点拉取的镜像仓库；使用构建脚本时还需要 Docker 和 Python 3。以下命令在项目根目录执行，示例参数请替换为自己的环境。

```bash
export KUBE_CONTEXT="your-cluster-context"
export IMAGE_REPOSITORY="registry.example.com/your-project/rancher-log-analyzer"
export IMAGE_TAG="0.2.1-$(date +%Y%m%d-%H%M%S)"
kubectl config use-context "$KUBE_CONTEXT"
```

### 构建镜像并部署

脚本会构建并推送两个标签：唯一的具体版本（如 `0.2.1-20261021-165252`）和 `latest`。每次发布都会覆盖 `latest`，具体版本标签保留。Helm 使用具体版本部署，便于核验和回滚：

```bash
docker login registry.example.com
bash scripts/deploy.sh
```

### 使用已有镜像部署

镜像已推送到仓库时，可直接执行：

```bash
helm upgrade --install rancher-log-analyzer ./charts/rancher-log-analyzer \
  --kube-context "$KUBE_CONTEXT" \
  --namespace rancher-log-analyzer --create-namespace \
  --set-string "image.repository=${IMAGE_REPOSITORY}" \
  --set-string "image.tag=${IMAGE_TAG}" \
  --wait --timeout 180s
```

私有镜像需先在目标命名空间创建拉取 Secret，并在部署命令后添加 `--set 'imagePullSecrets[0].name=your-pull-secret'`。

部署后访问 `http://<可达节点IP>:30080`，上传采集包即可查看。默认使用单副本和 `emptyDir`，无需 PVC 或 StorageClass；配置可通过 [Helm values](charts/rancher-log-analyzer/values.yaml) 调整。

**所有访问者共用临时工作区，服务重启或升级会清空上传数据。**
