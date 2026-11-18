# 桐弦声检故障判读册

GaussianNB与分层交叉验证、混淆矩阵和后验解释。为桐弦研究协作组的12位分析与业务人员提供从样本核对、独立worker计算到批准快照交付的完整工作流。

## 真实业务场景

合成声学特征→故障类型判读→复检批注；真实训练/验证分离、训练内标准化、类先验展示。团队原先将 `acoustic-bayes-202611-01.csv` 复制到多份人工表格，复核时再逐项对照。三个痛点是口径不可追溯、重复计算易错、业务说明与结果脱节。上游提供合成业务观察，系统承担研究和复核，下游业务人员读取批准快照。全部演示数据是固定随机种子生成的模拟数据。

## 业务模块

1. 业务总览：批次、样本、任务与批准交付账册。
2. 声检批次：创建/修改来源说明、查看样本、用真实业务字段追加记录；列表分页。
3. 分析配置：冻结来源、参数和全部样本，进入Redis队列。
4. 完整结果：真实算法摘要、专属诊断、全部CSV导出和可恢复失败态。
5. 复检批注：分析师草案→负责人批准→阅读者下载批准快照。
6. 连续监测：冻结研究模型、登记设备、按事件时间接收现场报文、形成/更正/撤销告警段、追查样本依据。
7. 审计：登录、来源修改、worker完成、业务说明批准、模型冻结与告警事件。

## 连续监测口径

检修现场用声检做连续监测，单次高后验容易误报，因此告警以“一段”为单位而不是单条报文：

- **冻结模型**：只有已完成的研究可冻结为模型版本（`POST /runs/{id}/freeze`），保存标准化参数、类先验、均值/方差与校验和；后续研究改动不会漂移已冻结版本。后验仍不校准，只是段内证据，不是检修结论。
- **按事件时间判读**：报文携带 `event_time`，接收与判读均以事件时间排序，与到达顺序无关；未来时间报文拒收。
- **成段规则**：同设备、同模型版本、同故障类型，十分钟内连续出现三次判读才形成一段告警（`segment_window_minutes=10`、`trigger_count=3`）。正常判读结束该段；类型变化、模型版本划界或同类判读中断超过十分钟也结束该段。段结束时告警转为 `closed` 并记录结束事件；若迟到记录补入间隔使该段重新连续，告警以 `reopened` 事件恢复生效，而不是留在已结束状态。
- **迟到重排**：比该设备已接收水位线早但不超过五分钟的报文照常接收并重排，告警段依据更新为 `corrected` 事件；早于水位线五分钟以上的报文 `expired` 拒收并保留原因。水位线只随已接收报文前进，拒收报文不会反过来推进水位线。
- **告警补偿**：已发出的告警不会静默改写或删除。重排后段不再成立时转为 `revoked` 并写撤销事件；重新成立时写 `reopened`。每个告警修订的 `raised/corrected/closed/reopened/revoked` 事件以去重键唯一，重试与恢复不会重复发出同一事件。
- **幂等与隔离**：`(device_id, message_key)` 唯一，重复报文不增判读；内容不一致的同号报文整条拒收。所有规则按设备分区，报文编号跨设备可复用。
- **可恢复**：接收、判读、告警分别提交；服务启动与 worker 轮询都会对全部设备执行一次只读重建，补齐中断的判读与告警，且不会重复通知。
- **模型换版**：绑定记录带 `effective_from`，按事件时间选择版本；同一告警段绝不混用两个模型版本，换版时历史报文按新时间线重判，受影响的生效告警以更正/撤销事件处理。
- **可追查**：告警详情返回样本依据（报文编号、事件时间、特征、后验）、所属模型版本与校验和、研究任务、以及完整事件时间线；阅读者只读也可查看。

## 快速启动

```bash
cp .env.example .env
docker compose config --quiet
docker compose up -d --build
# 可重复执行，不覆盖人工修改
docker compose exec -T backend python -m scripts.seed_demo
```

访问 [前端](http://localhost:18245)；[API文档](http://localhost:19245/docs)。数据库仅演示用途映射 `17745`。首次准备依赖和初始化数据库需要等待健康状态：`docker compose ps`，五个服务均需healthy。

| 组件 | 技术与职责 |
|---|---|
| frontend | 原生 HTML / CSS / JS ES Modules，Nginx代理 `/api/` |
| backend | Python3.11 / FastAPI / SQLAlchemy / JWT |
| worker | 独立Python进程，Redis BLPOP队列，持久化结果/CSV/心跳 |
| db | MySQL8，命名卷持久化 |
| redis | Redis7，AOF命名卷 |

恰好五服务，均配置healthcheck；后端/worker依赖数据库与Redis健康，前端依赖后端健康；worker与后端共享 `artifacts` 命名卷。重置演示环境：`docker compose down -v --remove-orphans`，会删除本项目卷。

## 账号与权限

所有演示账号密码：`Research2026!`。

| 邮箱 | 角色 | 权限 |
|---|---|---|
| admin@acoustic-bayes.demo | admin | 全部录入/执行、批准业务说明 |
| analyst@acoustic-bayes.demo | analyst | 录入来源/样本、执行、提交说明，无批准权 |
| viewer@acoustic-bayes.demo | viewer | 只读、导出结果及已批准快照 |

时间在数据库/API中以UTC存储，总览与审计页面明确转换为Asia/Shanghai北京时间。

JWT有效期8小时；PBKDF2盐化哈希保存密码；角色每请求从数据库读取。访客写操作403，匿名访问业务数据401，重复样本409，非法业务字段422，重复批准409。每客户端/路径写请求90次/分钟，超限429。生产使用需修改JWT及演示数据库凭据。

## 实体与字段

AcousticBatch / AcousticSample / ClassifierRun / InspectionNote 是核心实体；另有User和Audit。连续监测新增：`monitor_models`、`monitor_devices`、`monitor_bindings`、`monitor_messages`、`monitor_alarms`、`monitor_alarm_events`。数据库实际表：`acoustic_batches` → `acoustic_samples` → `classifier_runs` → `inspection_notes`。样本以固定字段JSON保存，后端按以下字段严格验证，不接受未知字段替代必填值：均方根振幅（`rms`）、频谱质心 Hz（`centroid`）、峭度（`kurtosis`）、复核类型（`label`）。

实体贯穿 `backend/src/models`、`schemas`、`services`、`controllers`、`routes`，以及 `frontend/src/api/research.js`、`stores/research.js` 和 `pages`。`Source.key` 与 `(Record.source_id, reference)` 为自然键；来源改名不会修改已冻结任务输入。业务说明在创建时保存结果快照，批准后从该快照导出。

## 算法与口径

GaussianNB与分层交叉验证、混淆矩阵和后验解释，全部计算位于 `backend/src/services/algorithm.py`，前端不拟合模型、不生成模拟结果。输入是冻结业务观察及参数，输出summary、专属诊断、逐行计算明细、seed与输入SHA256。CSV包含全部结果行；页面仅预览前30行。参数：

- `folds`：分层交叉验证折数，默认 `3`。
- `smoothing`：方差平滑系数，默认 `1e-09`。

分层交叉验证，每折只在训练行拟合均值与方差；后验概率是模型分布，不是检修结论。

失败态：业务字段缺失/非有限数值、参数越界、样本不足、退化特征或结构错误均明确拒绝或将任务标failed，错误消息保存在任务中。可回到来源或配置修正后重新执行，历史失败记录保留。

已知边界：独立同分布、特征条件独立和高斯类条件是假设；后验未校准。演示数据刻意有分离度，准确率不代表真实设备效果。使用分层折外验证，不提供外部最终测试集。

## 演示数据与一天剧本

固定seed=42，3个来源 ` TX-202611-01/02/03`，每来源240条，共720条业务记录；三个账号和首轮种子任务。自然键检查后仅插入缺失数据，连跑seed不重复、不覆盖用户修改。`SEED_DEMO=true` 时启动自动执行；失败日志但不阻塞服务。首轮任务同样由独立worker真实计算。

首轮研究完成后，种子会自动把它冻结为模型版本 `M-202611-01`，登记三台设备（`TX-MOTOR-01/02/03`），并回放一段合成报文流：一号机留下一条生效告警并因迟到记录更正依据；二号机先告警、后被迟到正常记录撤销；三号机形成一段正常结束的告警；另有一条超限报文被拒收留因。若首轮任务尚未算完，worker 会在完成后再补种，重复执行不会新增或改写。

1. 09:00 负责人查看三份来源和720条样本。
2. 09:10 分析师选择 `TX-202611-01 秋季常规组`，核对 `acoustic-bayes-202611-01.csv`。
3. 09:15 在“声检批次”核对均方根振幅（`rms`）、频谱质心 Hz（`centroid`）、峭度（`kurtosis`）、复核类型（`label`），追加编号 `TX-NEW-001` 的样本。
4. 09:20 新建“十一月复核研究”，按默认参数冻结241条输入。
5. 09:21 独立worker消费Redis队列，返回实算结果与输入校验和。
6. 09:25 分析师查看专属诊断及逐行结果，并下载CSV复算。
7. 09:30 提交“十一月业务复核意见”，负责人核对并批准。
8. 09:40 viewer下载批准快照，查看审计中的worker完成与批准事件。
9. 09:45 负责人打开“连续监测”，核对种子已冻结的 `M-202611-01` 与三台设备的告警段；如需换版，用“冻结研究为监测模型”创建新版本，再按事件时间绑定。
10. 09:50 viewer追查 `TX-MOTOR-02` 已撤销告警：样本依据、撤销事件与模型版本；分析师可点“回放一段演示报文”追加一段现场流，观察新告警段与正常判读结束。

## 目录与本地开发

```text
frontend/src/api, stores, types, components/common, hooks, pages, router, utils, constants
backend/src/routes, controllers, services, models, schemas, middlewares, utils, constants, config
backend/scripts/seed_demo.py
backend/migrations/001_initial.sql
```

本地后端：Python3.11虚拟环境安装 `backend/requirements.txt`，设置 `DATABASE_URL`、`REDIS_URL`、`ARTIFACT_DIR`，在backend目录运行 `uvicorn src.main:app --reload`；另开终端运行 `python -m src.worker`。原生前端无需编译，推荐以Compose Nginx访问，保证 `/api/` 代理。前端为Google Fonts双字体、oklch色板，离线字体回退serif；1280/768/390响应布局。

| 环境变量 | 默认与说明 |
|---|---|
| COMPOSE_PROJECT_NAME | `acoustic-bayes`，隔离容器/网络/命名卷 |
| FRONTEND_PORT / BACKEND_PORT / DB_PORT | `18245 / 19245 / 17745` |
| SEED_DEMO | `true` |
| JWT_SECRET | `.env.example`演示值，部署前修改 |
| DATABASE_URL / REDIS_URL | Compose内部连接，定义在compose的env锚点 |
| ARTIFACT_DIR | `/artifacts`，后端worker共享 |

连续监测相关 API：`POST /runs/{id}/freeze`、`GET /monitor/models`、`POST /monitor/devices`、`POST /monitor/devices/{id}/binding`、`POST /monitor/devices/{id}/messages`（现场网关报送，可带 `received_at` 便于回放）、`GET /monitor/devices/{id}/messages`、`GET /monitor/alarms`、`GET /monitor/alarms/{id}`、`POST /monitor/recover`。写入需负责人或分析师，读取登录后即可。

共享枚举：`backend/src/constants/enums.py` 与 `frontend/src/constants/enums.js` 都定义 admin/analyst/viewer、queued/running/completed/failed、draft/approved。后端service检查对应字符串；README为全量值说明。共享前端组件table/status/chart/business跨总览、结果、配置与复核复用；actions hook和format utils负责交互/格式。后端errors与rate_limit是两个中间件。

测试及截图在批根 `test-artifacts/gb-0041/`，不混入源码。独立算法oracle、HTTP完整流程和真实Playwright浏览器流程见该目录 `TESTING.md`。License：MIT。
