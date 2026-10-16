# 风险、契约、证据与计量协议（schema 1.2）

本协议由 `qa_policy.py`、`qa_ledger.py`、执行器和报告共同校验。所有宿主共用同一 CLI；不需要常驻服务、模型评审器或新测试框架。先读产品及架构，再填写适用性；程序能挡住已定义规则的遗漏，不能自动证明需求已经穷尽。

## 1. 方案适用性与样本

plan 增加 assurance。init 生成五项 unknown，需核实后填写：

| features 键 | 适用时必须覆盖的输入变体 | 常见对象 |
| --- | --- | --- |
| collections | empty / typical / limit | 列表、分页、批量、长度限制 |
| interfaces | accepted / boundary / rejected | API、模型输出、序列化、模块交接 |
| persistent_state | new / existing / repeat | 状态保存、历史迁移、重复执行 |
| async_jobs | success / error / interrupted | 后台任务、轮询、取消及恢复 |
| variable_output | typical / format_variation / rejection | 外部数据、文本格式、模型或其他非固定输出 |

每项 `{status, reason, sources}`。status 为 required / not_applicable / unknown；focused 可用 deferred。reason 是具体适用依据，sources 是非空来源列表。缺一项结构校验失败；unknown 或适用变体无必需用例，readiness/report 列缺口。每个边界单独要求三类契约输入，不能拿另一模块的成功填空。

这是小型基础矩阵，不要求笛卡尔积，也不自动增加冷安装、付费调用、压测。额外权限、安全、性能或交付风险继续按项目目标增加用例。便宜的技术检查可先跑；风险/样本方案未齐时不发放外部调用许可。

```json
{
  "claim": "representative",
  "reason": "验证本轮导出的合法、上界与拒绝输入",
  "sources": ["PRD.md:导出约定"],
  "features": {"interfaces": {"status": "required", "reason": "导出连接两个模块", "sources": ["ARCHITECTURE.md:导出"]}},
  "samples": [{"id": "boundary", "kind": "fixture", "path": "tests/data/boundary.json", "sha256": "文件内容的 SHA256", "purpose": "最大合法输入", "factors": {"interfaces": "boundary"}}],
  "boundaries": [{"id": "export", "producer": "schema.py:export_schema", "consumer": "importer.py:validate", "reason": "两端必须接受相同的合法数据"}]
}
```

上例只是字段节选，features 必须填写全部五项。样本路径相对项目，输入文件必须已存在、位于项目内并匹配摘要；在执行前准备，改变输入需新轮。kind=fixture / recorded / live 分别为离线构造、历史录制、实际场景输入；类型是来源声明，不能仅靠标 live 证明调用了真实服务。真实执行仍需证据和请求账本。

case 用 `sample_ids` 关联样本。样本数按内容摘要区分，同一文件换编号不增加代表性。技术样本用 native 或 contract：结果需 `sample_results: [{id, sha256, status}]`。stdout 的“全部通过”不能代替样本回执。已有 JUnit/Playwright 可继续做常规回归；需要承担样本矩阵时，用轻量项目适配器生成 native 回执，不安装另一套框架。

## 2. 跨模块契约

适用 interfaces 时，boundaries 列出真实生产方和消费方代码位置；对应 case 声明 `boundary_id`，使用 adapter=contract。普通 native 通过标记不能填补契约义务。

现有项目提供一个小适配命令：stdin 接受输入 JSON，stdout 返回：

```json
{"producer_accepts": true, "consumer_accepts": true,
 "producer_evidence": "真实生产 schema 的判定及定位",
 "consumer_evidence": "真实消费校验器的判定及定位"}
```

适配器必须调用真实 schema/校验器，不复制一份实现当作验证标准。语言不限，使用项目现有运行时。对于有意转换的边界，把转换后的产物作为边界输入，并验证真实转换行为；不能靠关闭比较放行。

`contract_check.py SPEC OUTPUT` 读取项目内 spec：

```json
{"boundary": {"id": "export", "producer": "contracts.py:producer_accepts", "consumer": "contracts.py:consumer_accepts"},
 "argv": ["{python}", "adapter.py"],
 "samples": [{"id": "limit", "path": "limit.json", "expected_producer": true, "expected_consumer": true}]}
```

完整示例见 [contract_demo.py](../scripts/contract_demo.py) 及 [示例项目](../tests/fixtures/contract-project/README.md)。case.argv 可为 `["{python}", "{plugin_root}/scripts/contract_check.py", "spec.json", "{evidence_dir}/result.json"]`。程序重新计算每对实际布尔判断：accepted/boundary 两端应接受；rejected 两端应拒绝；生产接受、消费拒绝必失败。输出绑定冻结边界、样本内容和分类，不信任一个手填 passed。spec 也在项目快照内。

默认使用离线构造/已脱敏录制输入，不请求模型生成更多样本。适配器本身仍是受信任的项目代码，程序不能证明其没有撒谎或调用网络；需检查其实现及副作用。

## 3. 逐点、逐样本观察证据

先 check，再填返回的 observation_template。保留每个断言的 checkpoint、expected、binding_id：binding_id 由冻结方案、用例、任务、检查点与样本生成。step 检查点的 expected 来自对应 action → feedback，不能换成其他任务的完成描述。其他检查点可在冻结前用 case.point_expectations 对象逐点写标准，未指定则使用 case.expected 加任务上下文。

断言填写 actual、passed、evidence_indices、locator；locator 指文件内具体截图区域、日志行、轨迹事件或数据位置。每个样本另有 `sample_evidence: [{id, sha256, evidence_indices, locator}]`。原始文件可以共用，但必须明确各样本的位置，不能只交一张“已完成”的截图。

交互 assertion 增加 trace_ids，指向 execution.trace 的唯一 id。每个轨迹项含：

```json
{"id": "T1", "sample_id": "boundary", "binding_id": "对应断言的绑定值",
 "planned_action": "check 模板给出的动作", "action": "实际执行的动作",
 "visible_result": "实际看到的反馈", "evidence_indices": [0], "locator": "trace.json:事件 6"}
```

每个检查点的每个样本都要有对应轨迹；无样本的局部检查仍需逐点轨迹。对每个点，planned_action 必须匹配冻结动作，轨迹绑定不能跨点复用。复用文件不等于复用旧结论。背景阅读、后台辅助和失败补救继续在 execution 中明确说明。

程序校验绑定、摘要、索引和对应关系，不能理解截图内容，也不能证明 actual 的语义真实。不同任务复制同一句实际结果，即使结构合法，仍需观察者判断；不要把此协议称作防造假系统。

## 4. 结论强度

| claim | 程序条件 | 可以说什么 |
| --- | --- | --- |
| single_run | 本轮必要检查通过 | 本次已定义检查通过；product_accepted 始终为 false |
| representative | 风险矩阵通过；每个任务的每个必需验收层面至少两份内容不同的输入有通过回执 | 声明样本覆盖下通过；两份是防止单样本冒充的下限，不是统计充分性 |
| sustained | representative 条件，加 repeat.min_runs 与 repeat.min_span_seconds | 声明次数及窗口内观察通过；不能推出未来稳定 |

sustained 需要至少两次实际通过，次数不超过 max_attempts_per_case，窗口正数且不超过约定时间预算。每条必要用例都满足；首次失败、受阻或重试不稳定不能被后来的成功抹掉。主动重试依然使用 run --retry 或新的 check；程序不会自动长时间轮询或追加付费运行。

product 门禁同时要求 product 范围、三类适用验收、风险/样本、有效证据、预算成立，以及 representative/sustained 强度。focused 永远不升级成产品验收。需要持续性声明时必须提前冻结 claim，不能验完后改报告措辞。

## 5. 统一计量与预留

limits 继续保留 execution_seconds、max_attempts_per_case、max_external_cost、currency，增加 max_external_calls / max_external_tokens（默认 0）。外部执行器声明 external_calls=true 及 external_call_bound、external_token_bound、external_cost_bound。请求数上界必须至少 1；未知价格也要有金额上界，免费要有真实的 0 记录。

check 在本地锁内预留请求、token、费用；另一个 check 看得到占用，重复 check 返回同一票据，不重复扣预算。record 消耗自己的票据后把占用转为实际尝试，失败、超时或缺失回执不自动退回，避免失联后无限重试。预算上界保守保留；要调整范围或预算，新建轮次。已发 check 尚未 record 时门禁显示未结算；未实际执行也导入 blocked/skipped 说明，不伪造成功。

所有观察都填写 usage，离线为 `{"requests": [], "reused_request_ids": []}`。外部调用每次都记，包括失败：

```json
{"requests": [{"id": "本轮唯一的实际请求编号", "status": "succeeded",
 "tokens": 1234, "cost": null, "evidence": "requests.json:请求编号及用量记录"}],
 "reused_request_ids": []}
```

status=succeeded / failed / unknown；结果 unknown 阻断通过。tokens 为非负整数或 null，cost 为非负数或 null。null 不等于 0：金额未知仍显示不完整，保留金额上界；token 未知保留 token 上界，没有对应上界则受阻。失败请求同样计入已知用量。费用单位使用 plan.limits.currency。

若复核同一请求的另一结论，在后续无新增外部调用用例中填写 reused_request_ids，必须引用本轮已记录编号；成本计一次。不同的新请求不能共用编号，重复登记会阻断。历史响应作为 recorded 样本输入，不能伪装成本轮真实请求。

外部 command 必须在 evidence_dir 写 usage.json（内容为上述 usage 对象），即使命令失败也尽量写出。执行器在失败/超时后仍读取，缺失保留预留并阻断。离线命令不需新侧文件，执行器保存显式空账本；若实际存在外部调用需正确声明和写账本。此工具不是网络代理，无法监测隐瞒的网络请求。

观察时长取“check 的程序时间到 record”与宿主声明 duration_seconds 中的较大值。报告分别展示命令时长、观察窗口、已知请求/token/金额及保守占用。窗口包含操作和等待，多个窗口累加不等于墙钟总时间。规划、阅读和宿主模型对话开销未自动计量，明确显示未计量，不能将测试账本解释为总开发成本。

## 升级

schema 1.0/1.1 只读历史，不能继续执行或通过新版 product gate。保留旧目录，init 建立新 schema 1.2 轮次；复用材料和离线输入，但补齐适用性、样本、绑定和账本。生成历史报告会更新 report 文件，如需保留旧报告请在档案副本上操作；不修改原 session/frozen-plan/evidence。
