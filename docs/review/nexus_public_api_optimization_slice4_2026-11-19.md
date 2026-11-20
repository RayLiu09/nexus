# 岗位 SQL 与分布分析优化单元4交付证据

日期：2026-11-19；单 Agent；本地实现完成，未提交/推送/部署/迁移。继承前三单元工作区，未修改真实业务数据。对应[任务包](../task-packages/wk_nexus_public_api_optimization_slice4_task_package.md)。

## 行为与统计合同

- 列表保持全部原响应字段、字面 AND 筛选、total、采集时间 DESC NULLS LAST / ID DESC。先查窄投影页ID，再读取完整行；统计仅在需要时间条件时连接一对一来源表。
- aggregate 新增 region；学历×经验、来源行业、区域最多三维交叉。把原5次统计查询（组数、组页、样本、两个缺失数）合并为1条共享分组 CTE 查询；从相同分组计数计算全部统计。NULL/空串/空格分组不合并，缺失数按NULL或trim空计算；空匹配及越界页仍返回全部统计。PostgreSQL SUM(bigint) 的 numeric 显式转int，保持API JSON整数合同。
- 新增 GET `/open/v1/market-jobs/salary-analysis` / `analyze_market_job_salaries`，top_n 1–100，复用 JobFilters。SQL只读取不同薪酬文本与频次，Python确定性规则解析，再查轻量TOP候选；不下载全量正文/来源JSON，不改原始薪酬。
- 默认仅明确周期的人民币月薪/年薪报价（年薪/12）；未标周期需显式 assume_monthly=true，返回影响数。日/时/周/次、面议、开放区间、缺失/非法格式等按原因排除，不假设工时或天数。多薪发放次数保留但不摊进月度基础报价。
- TOP按月薪下限、上限、ID降序；桶按未舍入范围中点，3千/5千/8千/1万/1.5万/2万/3万分界左闭右开。两位小数只用于展示。matched=eligible+excluded；桶数和=eligible。详情/真实来源通过job ID按需获取。
- region仅采集范围；行业保持原始企业行业文本，含多标签连写/重复值，不是标准产业归属。实际经验字段含本科/大专等来源错位值，学历字段有“实习”等异常，本单元不清洗或掩盖。已有学历/经验/行业维度没有假装成新增能力，通过skill明确其交叉统计用法。
- 新工具加入资源发现和market_jobs路由；工具59个/16标签，仍覆盖18类资源。岗位名足够时优先job_title；广义正文问题用q，两者不自动互换。skill先返回答案事实和统计，来源仍按需取证。

## 实际数据库与性能结果

强制只读连接10.100.11.182/nexus_dev；default_transaction_read_only=on，显式REPEATABLE READ / READ ONLY，20秒statement_timeout，断开后不保留事务。不启动真实应用lifespan、worker或种子，不执行API读取审计写入。SQL/执行计划及测试脚本见[本单元目录](../testing/nexus-public-api-optimization-slice4-20261119/)。

初次剖析164,706条岗位、1,312种非NULL薪酬文本，salary_raw存在164,671条。索引仅主键及来源的collected_at/source_job/upstream唯一键。固定received_to=`2026-11-19T06:19:25.766004Z`，同一只读事务中交替执行旧/新SQL各3轮，每轮验证列表全部字段、组顺序/计数、样本、缺失数完全等价；保存EXPLAIN ANALYZE BUFFERS JSON。分组维度为education×experience，列表pageSize=5，组页100。

| 查询条件 | 匹配记录/组数 | 旧聚合SQL总耗时中位数 | 新聚合SQL总耗时中位数 | 耗时下降 | 旧→新列表SQL总耗时中位数 |
| --- | ---: | ---: | ---: | ---: | ---: |
| q=电商 | 34,163 / 66 | 1,919.96 ms | 658.62 ms | 65.70% | 710.93→691.07 ms |
| job_title=电商 | 18,308 / 54 | 377.54 ms | 78.67 ms | 79.16% | 121.36→112.95 ms |
| job_title=电商 + region=杭州 | 1,652 / 32 | 226.75 ms | 51.15 ms | 77.44% | 98.38→95.21 ms |

以上为数据库客户端执行/取数时间之和，非生产HTTP或模型答复时间；小样本、低并发、共享数据库负载和缓存会影响结果，不是容量/SLA承诺。首次冷态list_count EXPLAIN为7,528ms，后续明显回落，不用这次冷读对新查询制造夸大的提升比。新计划确认job_groups CTE生产一次、两处消费；没有给一个宽子查询改名就声称数据库扫描减少。q宽正文扫描仍显著较贵；把q换job_title会改变匹配范围，不作为同义提速比较。

原始执行计划与数值在[baseline-profile.json](../testing/nexus-public-api-optimization-slice4-20261119/baseline-profile.json)和[comparison.json](../testing/nexus-public-api-optimization-slice4-20261119/comparison.json)。comparison里的SQL原生numeric计数通过default=str记录；API已显式转int并用PostgreSQL类型模拟回归验证，不应把原始SQL编码当作API响应。

## 薪酬结果与 skill 问题集

固定窗口“岗位名含电商”18,308条：严格周期模式eligible=0，原因是未标周期17,745、日/时等不支持527、面议23、开放区间13。无可换算项不代表无岗位。显式月薪假设下eligible=17,745（均受假设影响），excluded=563；真实只读SQL加解析、轻量TOP查询单次139.41ms，严格模式85.72ms，仅作单次观测。

| 假设月薪范围中点区间（元） | 岗位记录数 |
| --- | ---: |
| [0,3000) | 176 |
| [3000,5000) | 1,392 |
| [5000,8000) | 7,355 |
| [8000,10000) | 3,359 |
| [10000,15000) | 3,617 |
| [15000,20000) | 1,082 |
| [20000,30000) | 514 |
| [30000,+∞) | 250 |

TOP前两条报价5–10万，后续5–8万；它们也是未标周期按月薪的假设结果，不是已核实高薪事实。现有数据缺少显式周期，是比规则解析覆盖率更关键的数据质量缺口。

通过[问题集脚本](../testing/nexus-public-api-optimization-slice4-20261119/run_job_question_set.py)只读提取这18,308条所需的标题/维度/薪酬和最小provenance字段，排除岗位正文和raw_record，断开实际库后复制到隔离SQLite；启动lifespan=off的本地新API，经原skill执行器、生成Schema和连接池执行，answer预算12K。不是10.100.11.51远端新版本验收。21/21次HTTP成功，每题3次，未发生answer截断，统计和实际只读SQL一致。完整[答复/调用/来源投影hash](../testing/nexus-public-api-optimization-slice4-20261119/skill-question-results.json)。

| 问题 | 结果与检查 | 隔离HTTP P50（每项3次） |
| --- | --- | ---: |
| 电商岗位学历×经验分布 | 54组，50+4完整分页；学历缺失309、经验缺失469，逐组与源字段Counter核对 | 第1/2页29.6 / 69.6 ms |
| 电商岗位来源行业TOP | 1,534组，当前页10组；行业缺失1,723，非完整行业分布 | 76.3 ms |
| 电商岗位采集区域分布 | 35组一次完整返回；北京1,781/深圳1,767/广州1,729/杭州1,652/上海1,592，非实际工作地统计 | 23.8 ms |
| 电商岗位明确周期的月薪分布和TOP | 有岗位18,308，可换算0；返回全部排除原因 | 23.8 ms |
| 显式按未标周期为月薪的分布和高薪TOP | 有效17,745、排除563，8桶完整及TOP10；与实际SQL结果完全一致 | 28.6 ms |
| 杭州电商岗位学历×经验交叉 | 1,652条32组，学历缺失35、经验缺失59；验证区域过滤先于分组 | 16.9 ms |

隔离HTTP使用本机SQLite且无正文，适合验证工具链/合同，不与远端PostgreSQL HTTP基线比较。每题3个样本的P95在JSON中只是最近秩最大值，不作为稳定尾延迟基线。

## 回归与合同自查

- 108项API测试通过：岗位新分析/原业务消费、生成工具、上单元基地回归、中途Key撤销；新分析测试覆盖薪酬单位/年薪/多薪/边界、排除原因、保守下限排名、不同文本同金额的ID排序、原薪酬详情兼容、字面筛选/时间窗口、空结果/越界页/NULL/空串、JSON整数合同、401/过期403/撤销403/写方法405、脱敏actor/trace读取审计。
- 原skill 26项通过；OpenAPI生成与分发产物无漂移；skill quick_validate、Python语法与git diff --check通过。quick_validate需系统python3（已含yaml），API虚拟环境无PyYAML；不为校验器改应用依赖。
- 新GET使用原require_api_caller与audit_read，返回前复查撤销/过期。审计仅route/actor/trace/数量，不记录q、薪酬明文、源URL或正文。沿用P0全公开面Caller合同；没有新增逐路由permission_scope或组织过滤，不能宣称新增细粒度权限隔离。
- 默认列表/详情和旧分组维度兼容，region及salary-analysis为增量合同，静态路由排在动态job_id前；不改变Console内部接口、表结构、治理、归一化或语义索引。readme/ARCHITECT/SPEC/API/skill均更新。

验证命令：

```bash
nexus-api/.venv/bin/pytest nexus-api/tests/test_market_job_analytics.py nexus-api/tests/test_agent_public_business.py nexus-api/tests/test_public_function_tools.py nexus-api/tests/test_open_ecommerce_demo_bases.py nexus-api/tests/api/test_open_caller_mid_request.py -o addopts='' -q -o faulthandler_timeout=30
python3 -m unittest discover -s skills/nexus-public-api/tests -p 'test_*.py'
nexus-api/.venv/bin/python scripts/generate_public_function_tools.py --check
python3 /home/bjbodao/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/nexus-public-api
```

API测试在允许本机线程/网络的执行环境下运行，全部使用SQLite；沙箱中TestClient线程唤醒受限的问题不归类为业务性能缺陷。数据库脚本仅在已授权真实库地址、只读模式下运行；profile原始证据不重复覆盖，compare/run_job_question_set依赖已保存的baseline-profile冻结窗口。

## 后续优化与 Review Gate

1. 部署后在10.100.11.51用相同窗口/题集补测HTTP与并发，分离数据库、审计commit、序列化/传输与模型耗时。当前没有远端部署验收数据。
2. 对宽q的正文子串扫描，下一小单元可在隔离数据库副本对比pg_trgm GIN、索引体积和写入成本后再决定迁移；本次未添加或执行索引。列表保留精确total，本轮仅约3%–7%改善，不夸大。
3. 若业务需要正式产业/行业归类或学历经验标准化，先确定权威字典、复合行业多归属计数及异常字段治理口径；不能直接把现有字符串分布换成标准产业统计。薪酬周期优先在上游增加显式字段，减少月薪假设依赖，后续再评估持续统计的持久化投影。

API Contract与Permission And Audit已提供实现自查/自动验证证据；人工Review Gate仍须合并前完成，不以本报告替代人工批准。用户本轮未授权提交/推送/部署，本地交付到此完成。
