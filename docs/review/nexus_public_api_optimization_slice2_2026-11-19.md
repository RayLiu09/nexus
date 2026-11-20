# nexus-public-api 优化单元2验证

日期：2026-11-19。承接[单元1](nexus_public_api_optimization_slice1_2026-11-19.md)及用户授权，关联[本单元任务包](../task-packages/wk_nexus_public_api_optimization_slice2_task_package.md)。本单元完成服务端可选作答视图、真实远端故障定位及有边界的错误映射修复。变更在工作区，尚未提交、推送、部署、迁移；没有修改真实数据库业务数据。单Agent执行，保留其他工作区修改。

## 服务端行为与兼容性

`GET /open/v1/search`新增`response_view=full|answer`，默认full保持原结果字段与完整引用。answer返回canonical标题、score、正文、knowledge_type和chunk/ref续查ID，省略metadata、lineage、图片URI、locator、原始对象及大纲路径。每条正文默认2000字符，可在100–10000内配置；`content_chars`保留完整字符数，`content_truncated`标明是否截断。Top-K、阈值、collection、排序和所有检索范围均不变。没有缩短QA或Console默认响应。

优化发生在服务端：adapter的`include_lineage=False`避免读取normalized lineage列和复制旧快照里的大血缘，enrichment仅读取必要ref列并跳过大纲祖先路径。governance/quality仍从canonical ref恢复；范围、available/current-ref、权限hook、caller中途撤销/过期检查均在投影前执行。内部审计仍使用完整内部命中的chunk/ref/data-source及紧凑页码locator，原normalized副本不修改。权限hook仍为P0现有语义，没有新增或宣称组织隔离。

需要引用时用返回ID调用既有chunk/ref/章节或`POST /open/v1/evidence-resolutions`。真实API回归验证了answer后读取chunk证据仍能得到原正文前缀和locator，normalized资产仍含全部423个图片URI。服务端正文截断后再经skill本地投影，原长度和截断标记不会丢失。

新增`public_search_completed`安全日志及现有成功审计中的`response_view`、四段`stage_timings_ms`，覆盖scope、retrieval、enrichment_and_gates、projection，不记录自由问题词或正文。分段时长不含commit/响应序列化，不能当作完整HTTP耗时。

## 测量结果及边界

使用真实FastAPI ASGI HTTP路由、内存SQLite、真实adapter的Python后备排名路径与静态3维embedding，构造3条命中、同一ref的423个图片URI，vector metadata已通过既有compact流程处理。每种视图/形状预热2次，再交替测量20次；每次expire ORM对象，避免借助上一轮已加载lineage。测量不启动lifespan/Worker，不调用远端或生产数据库。HTTP字节为未压缩JSON响应正文。

| 合成样本 | full HTTP bytes | answer HTTP bytes | 响应体减少 | full本地P50/P95 | answer本地P50/P95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 每条700字符，正文全部保留 | 275,460 | 6,853 | 97.512% | 12.499 / 13.978ms | 11.928 / 12.767ms |
| 每条4200字符，返回前2000字符 | 335,453 | 17,988 | 94.638% | 13.286 / 14.060ms | 12.116 / 13.232ms |

两种形状的命中ID、score、顺序及正文前缀完全一致，answer捕获SQL未读取`normalized_asset_ref.lineage`，full仍读取。700字符场景证明收益不依赖删减有用正文；4200字符场景明确返回截断标记。本地P50仅减少约0.6–1.2ms，不能据此承诺线上按响应字节同比提速。该样本不是原411KB生产响应的逐字重放，也不覆盖PostgreSQL ANN、LiteLLM、链路带宽、压缩及模型推理；实际生产提速需部署后在同scope、同命中/缓存条件复测。来源数组小的响应，收益会更低。

可复跑[测量脚本](../testing/nexus-public-api-optimization-slice2-20261119/measure_search_projection.py)，原始字节/时延样本见[测量JSON](../testing/nexus-public-api-optimization-slice2-20261119/projection-measurement.json)。从仓库根目录执行：

```bash
nexus-api/.venv/bin/python docs/testing/nexus-public-api-optimization-slice2-20261119/measure_search_projection.py
```

## 真实远端500/503定位

读取的是10.100.11.51上的`nexus-api`容器，非本机Docker。镜像ID为`sha256:37c94ef8d53e2c305e35a1c7f60985418991e7572ade77056a7b350b285910a3`，启动时间`2026-11-19T01:31:59.321510736Z`。只读SSH/sudo会话已退出，没有重启或修改配置；认证材料不写文件或报告。

远端日志与[原基线](nexus_public_api_asset_baseline_2026-11-19.md)的trace逐项关联：

- 两次教学案例标签503：`baseline19-focused-teaching_case-02-r19-s59`与`r20-s60`都包含LiteLLM `/v1/embeddings`的HTTP429。两条trace共8条429日志，尚不能据此区分tag解析多次调用与重试。
- 十次教材500：`baseline19-focused-course_textbook-03-r1-s61`至`r19-s79`的奇数轮次全部存在同一异常链：`response.raise_for_status()`收到429 → `EmbeddingClientError` → search未处理 → 全局500。不是推测的数据库容量故障。
- 恢复请求`6a658efd5f604ca7b1c6fd21f279e444`在03:39:36 UTC得到embedding200，embedding约557.8ms、search总约633.56ms，命中3条；03:40:27的新会话首轮总约54.01ms。

脱敏证据见[远端trace关联](../testing/nexus-public-api-optimization-slice2-20261119/remote-error-correlation.json)。429已确认，具体是网关/供应商的哪项频率、并发、预算策略尚未确定。原十次连接中断与500相邻，但独立原因未证明；不能把换连接后恢复直接归因于连接池或新投影。

本单元只为公开search增加`EmbeddingClientError`→503、`error.message=search_embedding_unavailable`，保留trace并记脱敏事件；不返回空成功、不写成功检索审计、不重试、不改LiteLLM配置。真实embedding客户端通过受控429/超时注入，验证full/answer连续两次失败后同一TestClient后续恢复200，且每次只调用上游一次。它修复错误分类和异常处理，**不增加embedding容量，也不消除429本身**。ASGI恢复测试不等同于远端TCP复用复现；skill连接丢弃机制由单元1测试另行覆盖。

## 验证及Review Gate

- API共49项通过，分两组完成：`tests/test_search_qa_audit.py` 23项；`tests/test_search_qa_outline_fusion.py tests/test_agent_public_evidence.py tests/api/test_open_caller_mid_request.py tests/test_public_function_tools.py` 26项。隔离SQLite，沙箱外运行以避免本环境TestClient/AnyIO线程唤醒阻塞。
- adapter与query expansion共40项通过：`tests/index/test_pgvector_search.py tests/retrieval/test_query_expansion.py`，覆盖compact前后、full/轻量血缘、原对象不变及排名/治理值一致。
- skill执行器26项通过；新增服务端已截断响应的本地组合投影回归。保留单元1标签优先、来源标识、联网默认不入库和错误后丢弃连接能力。
- OpenAPI工具生成`--check`与skill分发资产一致，skill-creator `quick_validate.py`、Python AST、产物JSON及`git diff --check`通过。

Semantic Retrieval Integration Gate自查：来源未删除，旧full/QA/大纲回归通过，answer可按真实ID恢复证据。Permission And Audit Gate自查：投影位于准入/权限/Key复查后，审计保留actor/trace/chunk/ref/source/locator；非法参数422、认证401、中途撤销403、空scope不回退均有覆盖。API Contract Gate自查：新增参数显式可选、默认full兼容，生成工具与合同同步，503有稳定错误码消息。人工Review Gate按WORKFLOWS在合并前审核，本报告不代替批准。

## 启用及后续

新服务版本部署后，skill显式传`query.response_view=answer`才能减少HTTP体积；`--response-mode answer`仍仅控制本地上下文。检查原始响应`data.response_view=answer`确认生效，旧服务可能忽略新参数。默认full兼容，因此这一步可按调用方逐步启用；取消该参数即可恢复完整引用返回。

上线复测应保持相同query/scope/Top-K，比较full/answer实际bytes、P50/P95、命中和按需引用，分开记录embedding冷/热状态与429比例。当前远端仍运行旧镜像，本报告没有声称线上已优化。后续独立单元可先查LiteLLM限流/预算归属及标签embedding重复调用，再评估有边界的成功查询embedding复用；岗位/企业SQL和基地公开能力继续各自独立交付。
