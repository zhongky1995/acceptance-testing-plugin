# 验收测试插件

面向通过 AI 开发产品的非技术负责人。读取项目产品、架构和已有测试，按本轮目标选择验证方法，复用环境执行，保存证据并生成验收报告。

Evidence-based acceptance testing for AI-built products: risk-based planning, existing-environment reuse, technical and business checks, budget controls, and verifiable reports.

当前源码版本：**0.2.0**，增加独立交互验收与程序防漏检查，使用 schema 1.1。正式发行安装示例仍使用 v0.1.0；源码更新与发行标签分别管理。本地执行工具依赖 **Python 3.10+ 标准库**，没有额外模型 API、数据库服务或第三方 Python 库。

[下载发行包](https://github.com/zhongky1995/acceptance-testing-plugin/releases) · [自动验证](https://github.com/zhongky1995/acceptance-testing-plugin/actions/workflows/validate.yml) · [反馈问题](https://github.com/zhongky1995/acceptance-testing-plugin/issues)

## 使用

安装后调用「验收总控」，或直接描述任务：

> 用验收测试检查 `/你的项目绝对路径`。这是持续开发中的本地项目，本轮重点验证审批规则和相关回归。复用已有环境，先说明预计投入，完成实际测试后给我报告。

只要方案：

> 为这个项目形成验收标准和测试方案，先不执行。

接手第三方程序：

> 验收这个第三方交付的程序，先核对产品、架构、依赖和运行说明，使用现有环境，缺少条件时给出最小补齐路径。

交付评估：

> 这套程序准备私有化交付，检查目标环境里的安装复制、升级恢复、维护负担和成本，并区分实测与估算。

用户亲自测试：

> 启动本地环境让我亲自试用，只检查能否访问。

最后一类请求只启动环境，不自动代跑测试或调用付费服务。

## 插件内容

| 技能 | 用途 |
|---|---|
| 验收总控 | 选择场景、安排流程、控制预算、继续及复测 |
| 测试规划 | 阅读材料、确定标准与来源、按风险选择用例 |
| 技术验证 | 构建、单元、集成、接口、数据及按需专项 |
| 业务验收 | 业务定义与各方价值、规则、完整用户任务、真实效果及问题定位 |
| 交互验收 | 入口、理解、动线、可见反馈、完成与异常恢复 |
| 交付评估 | 按需检查环境、复制、依赖、稳定性和成本 |
| 验收报告 | 依据记录解释结果、缺陷、反馈与未测范围 |

技能按需读取，共用场景规则、数据合同和执行工具。默认一个 Agent，不因技能数量增加派单。

## 实际支持范围

- 文件与工具发现、方案校验、冻结标准、命令执行、超时/累计时间与尝试限制。
- JUnit、Playwright JSON、native 结构化结果解析；明确的构建/静态命令可用退出码适配。
- 宿主浏览器、computer use 或人工执行的断言及原始文件导入。
- 失败/受阻/跳过/未执行/不稳定分别记录；证据摘要与当前文件快照核验。
- 需求对应、六维报告、费用上界与已知实际费用、继续与新轮复测。
- 独立计算实现、需求适配、交互三类结论；按任务推导检查点，核验观察前记录和逐点证据，区分整体验收与限定检查。

业务验收先核对定义与标准依据，再检查实现是否兑现，并按范围核验真实受益者效果。必要检查写入门禁用例，分析与原始证据关联；不自动调用模型评判商业价值。详见[业务分析与校验](plugins/acceptance-testing/references/business-validation.md)。

测试框架和浏览器能力来自项目及宿主，本插件不自动安装。性能、安全、AI 评测等采用按需方法与已有工具，不自带完整测试平台。当前不自动跨轮复用门禁通过结果、不自动解析完整改动依赖图，也不自带业务代码修复或发布流程。

文件快照不能证明外部服务/模型/配置未变；观察者必须核验环境。费用和安装声明需要如实填写，执行工具不是网络/系统沙盒。宿主模型使用费无法取得时标未知，不能宣称总费用为零。

## 不同 Agent 如何避免漏项

程序从计划推导必要检查点，不接受一个“已完成”标记代替：只列后端测试、将必要交互改成可选、遗漏任务步骤/适用状态，都无法满足 product 门禁。界面文件/前端依赖会触发需要核对的线索；未发现线索不证明没有前端。

实际观察前由 check 生成绑定本轮版本、环境、用例和尝试的记录；导入时核对每个检查点的预期、实际、证据定位及操作轨迹。接手者继续同一档案，程序保留失败和已完成项。数据合同见 [程序验收协议](plugins/acceptance-testing/references/acceptance-protocol.md)。

日常技术小修复可有依据地使用 focused 范围，复用环境，只跑必要检查。即使该范围通过，也不会得到 product_accepted=true。接入发布流程时，由控制端调用：

```sh
python3 plugins/acceptance-testing/scripts/qa.py gate --session-dir /实际验收档案目录
```

退出 0 才表示本轮产品验收门禁满足。程序能核验流程和证据结构，不能独立证明图片语义、用户身份或 Agent 声明真实；Agent 走查不能替代真实用户观察。外部系统绕过 gate 或同权限修改整个工具不在此本地插件的约束范围内。

旧 schema 1.0 档案保留为历史；新版可解释历史但不能沿用旧协议执行或取得新版整体通过，应新建轮次补齐本轮证据。

## 安装与更新

项目包含本地目录 `.agents/plugins/marketplace.json`，插件位于 `plugins/acceptance-testing/`，同时提供便携 manifest 与 Codex 兼容 manifest。

在支持插件命令的 Codex 中安装固定发行版本：

```sh
codex plugin marketplace add zhongky1995/acceptance-testing-plugin --ref v0.1.0
codex plugin add acceptance-testing@acceptance-testing-local
```

来源名称 `acceptance-testing-local` 保留首版兼容性；它同样可以来自 GitHub。若已有该名称的本地来源，继续使用或通过客户端管理来源，避免重复添加。

命令以当前客户端帮助为准；终端里的旧版 Codex 可能没有插件命令，桌面应用随附版本可能不同。可先检查 `codex plugin --help`，再选择支持插件的客户端。

也可下载发行页的 `acceptance-testing-marketplace-0.1.0.zip`，解压到自选位置，用解压目录添加本地来源，然后安装同名插件。克隆整个仓库后也可以这样安装：

```sh
git clone https://github.com/zhongky1995/acceptance-testing-plugin.git
cd acceptance-testing-plugin
git checkout v0.1.0
codex plugin marketplace add .
codex plugin add acceptance-testing@acceptance-testing-local
```

桌面应用也可从本地来源找到「验收测试」并安装。安装和更新后在新聊天使用；如果列表未刷新，重新打开插件目录或按客户端要求重启。不要为此自行改写其他插件配置。

发行页提供插件 ZIP、目录来源 ZIP 和 `SHA256SUMS`。支持直接导入插件 ZIP 的宿主可使用前者；Codex 本地来源使用后者或 GitHub 仓库。公开仓库不等于已进入官方插件目录。

更新时按客户端流程更新来源和插件；需要固定版本时使用发行标签。不要仅替换部分脚本，也不要覆盖目标项目的验收档案。

## 报告

每轮档案保存在目标项目 `.acceptance/<轮次>/` 或指定独立目录，含方案、冻结副本、运行记录、证据和 report.md/report.json。插件升级不覆盖项目档案。

整体结论只代表本轮门禁：通过、失败、证据不足。功能、稳定性、环境、复制、成本和证据维度分别展示。范围外不视为失败，也不意味着通过。

执行内核没有遥测、上传接口或独立模型连接。宿主 AI、浏览器和项目命令仍按各自的数据规则运行。日志会做有限的敏感字段遮盖，分享报告前仍需检查原始证据；不要把客户数据或凭证提交到公开仓库。

产品范围见 [产品说明](docs/PRODUCT.md)，开发边界见 [架构说明](docs/ARCHITECTURE.md)，验证记录见 [验证说明](docs/VERIFICATION.md)。

## 开发验证

在仓库根目录运行：

```text
python3 -m unittest discover -s plugins/acceptance-testing/tests -v
python3 plugins/acceptance-testing/scripts/demo.py --output dist/demo-new
python3 scripts/package.py
```

演示只修复隔离样例，保留缺陷前后的两轮报告，不修改真实用户项目。独立验证路径受用户模型与成本规则约束。

演示应输出「初轮：failed；修复后新轮：passed」，报告位于指定输出目录的 before/after 子目录。输出目录需尚不存在，避免覆盖历史证据。样例故意含本人审批缺陷，仅用于验证插件。

贡献方式见 [CONTRIBUTING.md](CONTRIBUTING.md)。本项目采用 [MIT 许可证](LICENSE)。
