# 命令与数据合同

插件根目录是当前 SKILL.md 向上两级；命令将 `PLUGIN` 替换为实际绝对路径。项目档案建议放在 `.acceptance/<唯一轮次>/`，目录不覆盖。以下是调用示例，不能原样使用占位路径。

```text
python3 PLUGIN/scripts/qa.py init --project PROJECT --session-dir RUN --goal 本轮目标 --scenario local-iteration
python3 PLUGIN/scripts/qa.py validate --plan RUN/plan.json
python3 PLUGIN/scripts/qa.py readiness --plan RUN/plan.json
python3 PLUGIN/scripts/qa.py run --plan RUN/plan.json --session-dir RUN
python3 PLUGIN/scripts/qa.py run --plan RUN/plan.json --session-dir RUN --case C1 --retry
python3 PLUGIN/scripts/qa.py check --plan RUN/plan.json --session-dir RUN --case B1
python3 PLUGIN/scripts/qa.py record --plan RUN/plan.json --session-dir RUN --observation OBSERVATION.json
python3 PLUGIN/scripts/qa.py report --session-dir RUN
python3 PLUGIN/scripts/qa.py gate --session-dir RUN
```

init/scan 只读发现，写档案，不运行项目脚本。init 空白方案不能执行，必须填本轮要求和用例。validate 校验结构、关系、预算和执行参数，不证明正确性。

check 在宿主原生操作前核对单用例前置、预算、尝试上限，并冻结方案，返回本次 check_id 和观察模板；允许执行不等于测试通过。record 需要对应检查记录，缺失/过期或未满足前置时仍保留实际行为与费用但标受阻，防止已经发生的投入被漏记。readiness/三类结论/发布 gate 的协议见 [程序验收协议](acceptance-protocol.md)。

run/record/report 退出码：0 本轮门禁满足；1 本轮门禁失败；2 受阻或证据不足。分段执行期间 2 很正常：有尚未执行的必需用例，继续独立用例，不将其当脚本崩溃。执行用例内容不受报告退出码控制，参考 session 中各项真实状态。

## plan.json

新方案 schema_version 为 1.1，必须填写 [acceptance 合同](acceptance-protocol.md)。旧 1.0 仅支持历史报告，新轮不能降级执行。其余字段格式：

- project_root：存在的项目绝对路径；goal：本轮任务。
- scenario：local-iteration / third-party / target-delivery。
- snapshot：init/scan 生成，digest、complete 等原样保存，不手编。
- environment：实际宿主、模型、工具/服务/浏览器版本及非敏感配置。不要存 token、密码或完整敏感环境变量。其变更需要新轮。未知能力明确标 unknown。
- limits：execution_seconds（执行累计）、max_attempts_per_case（1..10）、max_external_cost、currency；必须有限数值。
- allow_install：本地默认 false；必要且已授权的环境准备才调整。
- requirements：id、statement、status（confirmed/proposed/conflict）、required（布尔）、sources（非空来源字符串列表）。必需要求没有已确认来源时门禁证据不足。
- cases：下列结构；至少一项。不能让范围外用例成为门禁。
- feedback：可选，列表，每项 kind（fact/risk/suggestion/unknown）、statement、evidence；不影响确定性判定。可以在最终业务说明中补充，冻结后不要改原方案以新增反馈。

```json
{
  "id": "C1",
  "title": "审批角色规则",
  "dimension": "functional",
  "requirement_ids": ["R1"],
  "required": true,
  "in_scope": true,
  "expected": "未经授权角色不能审批",
  "preconditions": "使用隔离账号与测试申请",
  "steps": ["发起申请", "以不同角色尝试审批", "核验申请状态"],
  "cleanup": "仅删除本轮测试数据",
  "prerequisites": [],
  "executor": {
    "kind": "command",
    "argv": ["{python}", "tests/check_roles.py", "{evidence_dir}/result.json"],
    "cwd": ".",
    "adapter": "native",
    "result_path": "{evidence_dir}/result.json",
    "timeout_seconds": 30,
    "external_calls": false,
    "external_cost_bound": 0,
    "installs": false
  }
}
```

dimension 为 functional/reliability/environment/delivery/cost/evidence。编号为字母数字、下划线或连字符，长度 1..64。依赖必须存在且无环。

command argv 用数组，参数中只替换 `{python}`（当前解释器）、`{project_root}`、`{evidence_dir}`，不通过 shell 执行。cwd 在项目内。需要 shell 的项目脚本要作为明确 argv 命令提供并检查副作用。

结构化 result_path 必须在独立 `{evidence_dir}/` 中，避免读取旧报告。exit 只用于明确的构建/静态断言；不能用来承接一个未解析的测试套件。

## 观察记录

先创建 executor.kind=observation 的用例，仍需费用及安装声明。使用宿主实际工具操作后保存：

```json
{
  "case_id": "B1",
  "check_id": "本次操作前 check 返回的值",
  "status": "passed",
  "reason": "界面操作完成，数据回查与角色状态符合预期",
  "observed_by": {"host": "实际宿主", "model": "实际模型或 unknown"},
  "observed_snapshot": "从 plan.snapshot.digest 获取",
  "environment_hash": "用 qa_store.digest(plan.environment) 计算",
  "duration_seconds": 25,
  "external_cost_actual": null,
  "assertions": [{"expected": "申请状态为已批准", "actual": "页面及回查均为已批准", "passed": true}],
  "evidence_files": ["实际工具返回的截图或轨迹绝对路径"]
}
```

passed/failed/flaky 需有真实文件及断言，passed 不接受失败断言；blocked/skipped 需原因，可无截图。相对证据路径从观察 JSON 所在目录解析。文件被复制入档案并保存摘要，来源文件不修改。原始截图不自动脱敏，导入前检查；文本输出仅做常见密钥模式遮盖，不能保证识别所有敏感内容。

本工具验证记录/文件一致性，不独立判定图像内容或业务语义。观察者必须真实核验。声明费用上界按尝试累计；实际费用单列，超出预算体现在报告中。

## 档案与快照

inventory.json 是发现结果，plan.json 是代理编制方案，首次执行保存 frozen-plan.json 和 session.json。证据写 evidence/<case>/<attempt>/，report.md/report.json 由记录生成。

快照排除依赖、构建输出、缓存与本轮档案，读取上限为一万文件、128MiB，符号链接未展开标不完整。不能自动证明被排除产物、外部服务、模型及网络配置不变，需额外记录核验。完整性不足不判通过。锁定与摘要检查用于一致性，非防恶意篡改的签名审计。

当前不自动计算改动依赖图、不自动安装依赖、不直接调用模型，也不自动跨轮复用通过结果。规划技能负责影响分析，适用性不足则扩大必要覆盖。
