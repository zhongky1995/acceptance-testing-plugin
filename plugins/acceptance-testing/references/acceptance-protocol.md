# 程序验收协议 1.1

Python 标准库 CLI 是所有 Agent 的共同入口。技能负责理解与取证；程序负责范围、关系、先行检查、记录完整性和放行判断。无需新增模型、MCP 服务或数据库。

## 调用与接手

1. `qa.py init --project PROJECT --session-dir RUN --goal GOAL` 生成 schema 1.1 空白方案。默认 scope=product；明确局部检查可加 `--scope focused`。两者都需填写真实范围理由与来源，模板不会自动确认标准。
2. 按本文填写 acceptance，并照常填写 requirements/cases。`qa.py validate --plan PLAN` 校验结构；`qa.py readiness --plan PLAN` 返回自动推导的 obligations、缺口和例外（缺口时退出 2）。未覆盖交互不阻断独立技术执行，但不能放行完整产品。
3. `run` 执行命令；观察前 `check --plan PLAN --session-dir RUN --case ID`，取得 allowed、check_id、检查点和 observation_template。按真实执行补模板并通过 `record` 导入。
4. `report --session-dir RUN` 重新核验证据、冻结计划和先行记录，输出分项结论。其他 Agent 接手相同 RUN 即可；无须依赖聊天记忆，不自动重跑已有用例。
5. 发布/交付控制端调用 `gate --session-dir RUN`（默认要求 product）：0=本轮产品门禁满足，1=必需测试失败，2=范围不足或证据不足。仅检查本轮限定任务的控制端可明确使用 `--scope focused`。

**宿主应根据 gate 的退出码或 report.json.product_accepted 决定后续动作，而不是解析 Agent 的“已通过”文字。** 该插件不自带部署能力；若外部流程不调用 gate，它不能替外部流程强制拦截发布。

## acceptance

```json
{
  "scope": "product",
  "reason": "验收作者保存并继续编辑草稿的完整任务",
  "sources": ["PRD.md:草稿任务"],
  "surfaces": ["gui", "api"],
  "layers": {
    "implementation": {"status": "required"},
    "need_fit": {"status": "required"},
    "interaction": {"status": "required"}
  },
  "journeys": [{
    "id": "J1", "title": "保存并继续编辑", "role": "作者",
    "trigger": "需要暂时离开编辑页", "entry": "/editor",
    "outcome": "再次打开时能继续编辑已保存的内容",
    "requirement_ids": ["R1"], "sources": ["PRD.md:草稿任务"],
    "steps": [
      {"id": "S1", "action": "保存当前内容", "feedback": "可见已保存状态"},
      {"id": "S2", "action": "离开后重新打开", "feedback": "内容与保存前一致并可编辑"}
    ],
    "patterns": [{"name": "显式保存与状态反馈", "decision": "adopt", "reason": "让作者能判断是否可以离开", "source": "项目编辑规范"}],
    "states": {
      "loading": {"status": "required"},
      "empty": {"status": "required"},
      "error": {"status": "required"},
      "interrupted": {"status": "required"},
      "permission": {"status": "required"}
    }
  }],
  "surface_exclusions": []
}
```

- surfaces：gui / cli / api / background / unknown。未知会形成缺口。发现 HTML/界面源码或常见前端依赖而未声明 gui 时，程序要求说明。确为非产品示例等可在 surface_exclusions 填 path、reason、sources；例外始终展示。扫描是有限线索，不能证明所有前端都已发现。
- layers 三项不能省略。product 必须包含实现与需求适配，有用户入口时交互必需。focused 可将未评估板块设 deferred，并填 reason/sources；无论限定检查是否通过，product_accepted 都为 false。
- not_applicable 也必须提供 reason/sources；有 gui、cli 或 unknown 时不能把交互设为不适用。API/后台服务无用户入口时可声明不适用。
- journeys 是本轮要验收的关键任务，全部纳入对应必需层面的覆盖计算。需求适配或交互必需却没有任务时不能通过。标准、路径、范围变更需要新轮，不自动推测“所有关键任务”已经列全。
- states 固定核对五类状态；实际不适用可填 `{"status":"not_applicable","reason":"具体理由","sources":["依据"]}`，缺字段仍算漏项。focused 局部检查可用同结构 status=deferred 表明本轮未评估；product 不允许延期适用状态。patterns 每项 decision 为 adopt/adapt/not_applicable，需说明取舍；不强制复制任何设计系统。

## 用例归属与自动覆盖

cases 在原结构上增加：

```json
{"assessment": {"layer": "interaction", "journey_id": "J1", "checkpoints": ["entry", "comprehension", "feedback", "completion", "step:S1", "step:S2", "state:loading", "state:empty", "state:error", "state:interrupted", "state:permission"]}}
```

未分类用例仅计入 implementation，不能自动填补另外两类。程序为每条任务推导：

| 层面 | 必需检查点 |
|---|---|
| implementation | outcome |
| need_fit | goal_alignment、workflow_fit |
| interaction | entry、comprehension、feedback、completion、每个 step:编号、每个适用 state:名称 |

每个点必须对应 `required=true` 且 `in_scope=true` 的用例，并关联任务要求。将用例改为可选、全部删去、只保留后端用例都无法补齐覆盖。没有任务的纯技术 focused 方案只需本轮 implementation/outcome。

need_fit 和 interaction 使用 observation；可以在同一份真实材料或轨迹上评估多个检查点。普通浏览器自动回归仍可用 command，但它只证明实现层。分析和交互执行可使用已有自动化工具，取证后仍需结构化导入。

需要需求适配的任务，交互 check 会自动等待其 goal_alignment 和 workflow_fit 的所有必要用例稳定通过，无须 Agent 手工加依赖。其他技术用例可继续。

## 观察证据

沿用 contracts.md 的快照、环境、时间费用、断言和文件字段，另加：

```json
{
  "check_id": "本次 check 返回的值",
  "method": "ui_walkthrough",
  "actor_kind": "agent",
  "assertions": [{"checkpoint": "entry", "expected": "能从编辑页找到保存入口", "actual": "实际观察到的行为与结果", "passed": true, "evidence_indices": [0]}],
  "execution": {
    "surface": "gui", "entry": "实际访问入口", "backend_bypass": false,
    "source_access": "implementation-informed", "assistance": [],
    "trace": [{"action": "实际动作", "visible_result": "实际可见结果", "evidence_indices": [0]}]
  }
}
```

这是字段示意，不是可直接登记为通过的记录；须提供该用例全部检查点。evidence_indices 为 evidence_files 的零基索引，可多点复用，但每点都要有非空预期与实际。method：analysis / ui_walkthrough / human_observation；actor_kind：agent / human。交互不接受仅 analysis，Agent 不能标为 human_observation。实现知识 source_access：none / implementation-informed，assistance 记录提示、人工补救或空列表。

check_id 绑定冻结方案、版本、环境、用例和尝试次数，成功导入后消耗；不能跨用例或重试复用。缺检查、缺点、证据索引无效、后台绕过、缺实际轨迹等记录会保留实际成本与证据并标 blocked。不能事后补一张 check 将此前观察变成通过，应重新进行本次观察。blocked/skipped 的受阻说明不要求虚构轨迹。

report 再读取原始 observation 与先行记录，不只相信 session 的状态字段。检查点分别展示实际断言结论；同一点失败后重试成功仍为不稳定。部分点通过不会改变整条必需用例失败或不稳定的门禁结论。证据文件与摘要一致仍不能证明图片内容、声明的人类身份或语义判断属实；这不是对同权限恶意篡改的签名审计系统。

## 旧档案

schema 1.0 可生成带限制的历史报告，不能在新版执行或获得新版整体通过。保留旧档案；新建 schema 1.1 轮次，复用需求资料但重新取得所需执行证据。不要修改旧 schema 字段或原冻结记录来假装完成升级。
