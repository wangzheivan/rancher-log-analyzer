# Rancher Log Explorer

Rancher 官方日志采集包的中文可视化工具，支持：

- 按案例管理多个节点的采集包，上传 `.tar.gz` / `.tgz` 文件。
- 展示集群概览、节点、Pod、Kubernetes 资源及主机与 etcd 信息。
- 按目录浏览原始文件，分块读取大日志并搜索关键字。

详细的本地开发、配置、API 和测试说明见 [使用与开发说明](docs/USAGE.md)。

## Kubernetes 部署

准备可访问集群的 `kubectl`、Helm，以及可供节点拉取的镜像仓库；使用构建脚本时还需要 Docker 和 Python 3。以下命令在项目根目录执行，示例参数请替换为自己的环境。

```bash
export KUBE_CONTEXT="your-cluster-context"
export IMAGE_REPOSITORY="registry.example.com/your-project/rancher-log-analyzer"
export IMAGE_TAG="0.1.0"
kubectl config use-context "$KUBE_CONTEXT"
```

### 构建镜像并部署

脚本会构建、推送镜像，并通过 Helm 安装或更新应用：

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
