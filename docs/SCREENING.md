# 问题发现：离线规则初筛（0.3.0）

问题发现针对当前选择的采集包，不合并案例内其他包，不查询在线集群，不执行修复，也不调用 AI。结果是可复核的采集证据，不是实时健康状态或自动根因结论。

## 阅读结果

- **快照与配置发现**：采集时的对象状态、主机采样、服务状态及配置。证书单独注明按分析时刻检查采集副本。
- **日志中的历史信号**：在指定扫描范围内命中的历史记录，不因此认定当前仍有故障。保留原文时间；只有明确 UTC/偏移的时间才规范化，其他时间不猜测时区。
- **未能完成的检查**：缺失、损坏、截断、无法解析或适用性不明确的证据。不能解释为正常。

严重程度为高风险、需关注、提示、无法判断，不计算健康评分。检查覆盖可展开查看各类别的通过、有发现、无法判断及不适用数量；“通过”只限相应采集证据。关键快照展示服务角色和状态、etcd成员/leader证据；资源卡片只属于采集节点。

列表每页50条，支持类别、级别、命名空间、节点及关键字组合筛选。每条发现附现象、阈值或适用条件、核查建议、原文入口及对象详情跳转。Pod/Node事件优先按UID关联，没有UID时明确标注名称关联；预览最多3条，展开每页10条。没有关联事件不代表从未异常。事件宽表支持可选列为空，原始列与相对时间保留。

日志按规则、对象和证据类型归并，次数是命中次数，不是独立事故数。同一文件字节位置去重，示例每页最多10条，正文通过已有安全文件阅读器定位；长行分段保留字节位置。摘要及证据预览有长度上限，完整内容保留在源文件中。

## 首批规则与边界

| 类别 | 检查内容 |
| --- | --- |
| 集群与Pod | Node Ready及压力/网络Conditions；核心与业务Pod失败、等待原因、未就绪、OOMKilled和关联事件；支持Node Describe的Conditions回退。 |
| 节点服务 | systemd实际active/sub状态，区分server/agent及独立运行时。enabled和日志存在不作为运行证明；server不要求独立agent同时启动。 |
| 初始化 | swap快照、IPv4转发、桥接适用性、可用配置中的cgroup驱动、网络管理服务冲突和关键sysctl信息；配置文件一致不证明已生效。 |
| 资源 | vmstat间隔CPU/I/O wait、top回退、每核负载、available内存、磁盘、inode、文件句柄、swap及ps STAT僵尸进程。 |
| etcd | 采集成员leader证据、端点健康、成员启动标识、端点错误、告警、数据库配额及明确etcd上下文的慢请求/心跳日志。 |
| 其他历史信号 | 内核/容器OOM、明确磁盘I/O错误、文件系统只读、空间或文件句柄耗尽、CNI/sandbox失败、TLS证书时间异常。 |

Completed/Succeeded不报异常，历史重启次数不直接表示当前故障。普通Pending、初始化和终止中作提示，有明确Warning事件时升级关注。核心组件明确失败、Node NotReady、必需服务失败、etcd无leader/不健康和严重资源阈值列为高风险；业务Pod异常与未就绪列为关注。

独立containerd/Docker服务失败在RKE2/K3s下先作关注，因为集群可能使用发行版管理的内嵌运行时。无法确定节点角色时不猜测必需服务。

不将`vm.swappiness=60`、SELinux/AppArmor开启、防火墙开启或某模块未出现在`lsmod`中直接判为故障。swap需结合版本和kubelet设置；桥接参数需结合CNI。sysctl/swap快照不证明持久配置，时间同步服务运行也不证明已同步。当前采集器缺少有效配置时，cgroup等检查显示无法判断。

etcd follower的`IS LEADER=false`正常，单成员不自动判故障；member的`started`只是启动标识。健康输出与成员客户端URL核对，未探测端点保持覆盖不足。多份metrics按来源分别计算配额，不能把不同来源的DB大小和配额混算。单次累计计数不推算近期速率、选举频率或当前延迟。etcd慢请求规则不会把kubelet的慢stats采集当作etcd错误，也不会把监控代理当作etcd组件。

配置及核查建议参考官方资料，并按版本和场景使用：

- [Kubernetes运行时、转发与cgroup](https://kubernetes.io/docs/setup/production-environment/container-runtimes/)
- [Kubernetes swap](https://kubernetes.io/docs/concepts/cluster-administration/swap-memory-management/)
- [Node Conditions](https://kubernetes.io/docs/reference/node/node-status/)
- [RKE2网络相关已知问题](https://docs.rke2.io/known_issues)
- [etcd metrics语义](https://etcd.io/docs/v3.5/metrics/)
- [etcd慢请求说明](https://etcd.io/docs/v3.5/faq/#what-does-the-etcd-warning-apply-entries-took-too-long-mean)

## 默认阈值与配置

阈值为项目初筛配置，不是Kubernetes通用强制标准。CPU非空闲包含I/O wait/steal；负载含不可中断等待，不等于CPU使用率。vmstat首条启动以来平均值排除，剩余样本取均值；top只使用最后一帧并注明快照。内存使用available；磁盘忽略伪文件系统和loop，重复挂载归并，多个真实文件系统卡片取最大占用。文件句柄使用系统file-nr，不以采集器shell的ulimit代替服务限制。

| 配置键 | 关注 / 高风险 |
| --- | --- |
| cpu | ≥85 / ≥95 % |
| iowait | ≥10 / ≥25 % |
| load | ≥1 / ≥2（1分钟负载/逻辑CPU） |
| memoryAvailable | <15 / <5 % |
| disk / inode / fileHandles | ≥85 / ≥95 % |
| etcdQuota | ≥80 / ≥95 % |

通过环境变量`ANALYSIS_THRESHOLDS`覆盖指定内置阈值，例如`{"cpu":[80,95],"memoryAvailable":[15,5]}`。只允许已知键及有限数字，不执行用户脚本或正则。Helm使用`analysis.thresholds`传入对应对象。

| 环境变量 | 默认值 | Helm值 |
| --- | --- | --- |
| MAX_ANALYSIS_BYTES | 33554432（32 MiB） | analysis.resultBytes |
| ANALYSIS_SCAN_BYTES | 134217728（128 MiB/轮） | analysis.scanBytes |
| ANALYSIS_SCAN_FILES | 200（文件/轮） | analysis.scanFiles |
| ANALYSIS_FILE_BYTES | 8388608（8 MiB窗口/文件/轮） | analysis.fileBytes |

包ready后自动排队，不阻止正常展示。结构化记录按批处理；正文单任务读取最多2 MiB，执行后重新排队，让新导入有机会插入。默认从尾部扫描：etcd、核心与系统、异常Pod当前日志优先，previous最后。正常业务Pod正文不自动全量扫描。

页面展示候选目录是否建立完整、访问/完成文件数、扫描字节及剩余范围。达到任一轮次/文件窗口预算会暂停为partial；“继续扫描”先覆盖未访问文件，再处理更早的窗口，不重复计数。完成只针对候选范围，不表示所有业务日志被检查或集群健康。

分析数据库与回滚日志共用32 MiB预留，计入会话配额；主数据库保守限制为预算约一半，给事务回滚留空间。预留在包存续期间保留，页面同时显示实际数据库大小。空间不足时不使采集包导入失败；结果预算耗尽时保留已提交发现并明确未完成，可调整配置后重新分析。取消后可继续，重新分析清除该包旧结果；同包仅有一个任务。删除案例/包取消关联任务并安全清理；服务重启清空全部临时数据与结果。

## API及测试

- `GET /api/v1/bundles/{id}/analysis`：状态、规则版本、处理耗时、统计、阈值、关键快照及检查/扫描覆盖。
- `POST /api/v1/bundles/{id}/analysis`：JSON `{"action":"continue|cancel|restart"}`。运行中重复请求不会启动第二个任务。
- `GET /api/v1/bundles/{id}/analysis/findings`：`limit`默认50、最多200，`cursor`、`q`、`category`、`severity`、`evidence_type`、`namespace`、`node`。返回`items/total/nextCursor/previousCursor`；游标绑定规则运行和筛选，固定本次列表范围，返回第一页可查看新增结果。
- `GET /api/v1/bundles/{id}/analysis/findings/{findingId}`：发现、证据及关联事件。`cursor`为证据游标，`event_cursor`为事件游标；每页分别最多10条。

规则版本为`screening-1`。发现保留规则ID、对象/UID、来源、字节位置、判断条件、建议及适用的官方资料，便于后续迭代和人工复核。

合成验收命令：

```bash
python3 scripts/make-scale-fixture.py
python3 scripts/make-test-fixture.py
python3 scripts/make-analysis-fixture.py
E2E_BASE_URL=http://127.0.0.1:18080 npm run test:e2e --prefix frontend

python3 scripts/make-scale-fixture.py --abnormal-pods 1000 --output /tmp/rancher-abnormal-scale.tar.gz
python3 scripts/accept-scale.py --container <测试容器名> \
  --archive /tmp/rancher-abnormal-scale.tar.gz --analysis --expected-abnormal 1000
```

真实包浏览器验收需显式提供绝对路径`DISPLAY_ARCHIVE`。测试只删除自己创建的案例，真实包、截图及备份保持Git忽略。
