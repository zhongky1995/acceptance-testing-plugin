# 项目 CI 接入：按风险选择，交付另设产品门禁

CI 用项目已有命令持续检查改动。模板只需 Python 3.10+ 标准库，按需启动项目原有环境；不安装新测试框架、不接模型 API。插件自身 CI 与被测项目 CI 是两套配置，各自控制自己的仓库。

## 接入与文件

先确认本轮需要配置 CI。插件路径从当前技能向上两级取得；以下占位路径要替换：

```sh
python3 PLUGIN/scripts/qa_ci.py init --project PROJECT
```

生成 `.acceptance-ci/ci.py`、`policy.json`、同版验收内核 `engine/`，以及 `.github/workflows/acceptance-ci.yml`。文件在目标仓库内提交，CI 不需要额外下载插件或登录模型。init 先检查全部目标，有同名文件就停止，不覆盖已有工作流或配置。

已有 CI 的项目优先：

```sh
python3 PLUGIN/scripts/qa_ci.py init --project PROJECT --runner-only
```

仅生成执行器/配置/内核，将运行步骤并入原工作流；复用原有运行时、依赖缓存与服务，避免重复开流水线。已有生成目录更新时在临时目录生成新版并审阅差异，保留项目定制；不要用删除旧目录再覆盖的方式丢失配置。

在项目 `.gitignore` 中忽略 `.acceptance/`。该目录用于本轮报告和日志，不作为源码提交。工作流默认只上传选择报告，保存七天；原始日志和业务证据不自动上传。

## 配置实际检查

编辑 policy.json 的四组 commands 以及真实风险路径；空命令故意不算通过。最小命令格式：

```json
{"argv": ["{python}", "-m", "unittest", "discover", "-s", "tests"],
 "timeout_seconds": 60, "external_calls": false, "installs": false}
```

已有 Node 项目可用 `["npm", "run", "test:unit"]` 等真实脚本；命令来自该项目而不是照抄例子。参数数组直接执行，不经过 shell；可用 `{python}`、`{project_root}`、`{qa}`（随模板复制的 qa.py）。cwd 可指定项目内相对目录。多步骤环境/服务启动与清理由项目现有脚本管理，执行器会清理自己命令进程组，不能依靠遗留后台进程跨命令保持服务。

| 组 / trigger | 自动触发条件 | 典型检查 |
| --- | --- | --- |
| fast / always | 每次都执行 | 快速构建、静态检查、单元或冒烟 |
| integration / changed | 对应接口/数据/依赖路径变化 | 集成、契约、迁移及恢复回归 |
| experience / changed | 页面、交互或业务约定路径变化 | 项目已有的浏览器、用户任务及异常状态回归 |
| delivery / delivery | 明确手动选择交付检查 | 在当前 CI 环境生成本轮必要证据，最后执行产品 gate |

目录模式是可修改的起点。根据项目架构核对后端、前端、共享对象、业务规则、依赖和文档对应的检查，不仅依据文件扩展名。共享规则变化同时触发相关组；可以增加 changed 检查组。status=not_applicable 需具体 reason 与非空 sources，报告展示依据。fast 始终 required，至少保留一组 changed 和一组 required 的 delivery，防止配置为空还通过。

CI 的命令退出码表示对应自动检查的结果。需要确认零用例、跳过及逐样本回执时，使用随附 qa.py 的 native/JUnit/Playwright/contract 适配器，不仅依赖测试命令的退出码。浏览器回归通过也不会自动产生需求适配或产品验收结论。

## 选择规则与成本

- `change`：fast 加触及路径的 changed 组。Git 比较使用 NUL 分隔且禁用重命名折叠，删除以及重命名的旧/新路径都参与选择。
- `full`：全部适用自动组；不自动运行交付或付费服务。
- `delivery`：全部适用组和交付组，再由程序调用固定的 `qa.py gate`，不能靠在配置中删除 gate 来放行。

比较基线缺失、浅克隆拿不到基线、基线不是 HEAD 祖先、出现未映射路径或 CI 配置变化时，扩大到所有自动组。不会把未知改动当作安全的小改。`.acceptance-ci/` 与 `.github/` 的任何改动都扩大覆盖。模板浅取两个提交，避免默认下载全部历史；需要时按项目成本调整 checkout，无法比较仍按上述规则扩大。

在已初始化项目的根目录执行：

```sh
python3 .acceptance-ci/ci.py plan --base BASE_SHA
python3 .acceptance-ci/ci.py run --base BASE_SHA
python3 .acceptance-ci/ci.py run --profile full --output .acceptance/full-selection.json
python3 .acceptance-ci/ci.py run --profile delivery --output .acceptance/delivery-selection.json
```

plan 只读分析，不执行测试；run 保存报告。报告路径与对应日志目录不可覆盖，复测用新路径或先归档。默认累计预算 480 秒，每命令还有超时；配置上限 540 秒，工作流上限十分钟。基础或较早检查失败/缺命令后停止更深层投入，剩余 selected 组明确 not_run，不算通过。无自动重试，旧报告不能代替新运行。

所有命令必须声明 external_calls=false、installs=false；模板拒绝声明付费调用或安装的命令。这是副作用声明检查，不是网络沙盒。真实环境准备使用项目已有、授权的最小安装和缓存流程，置于已有工作流环境步骤，不要求本地项目重新冷安装。需要收费服务的专项单独安排，并使用验收内核的时间/请求/token/费用预算；不要塞进每次 PR 的自动组。

模板不提供任何付费服务密钥；workflow 为 pull_request 而非 pull_request_target、令牌仅 contents:read、不持久化 checkout 凭证，并取消同分支过时运行。GitHub 运行分钟、项目启动及已有服务费用仍按对应账号规则计量；不能把无新增模型调用说成总成本为零。

## 完整产品门禁

change/full 通过时 `product_accepted` 始终 false，只说明本轮自动检查通过。手动 delivery 的 commands 负责在当前提交、当前 CI 目录和环境建立 schema 1.2 的真实验收档案，位置由 product_session 指定（默认 `.acceptance/ci`）。随后执行器强制运行：

```sh
python3 .acceptance-ci/engine/qa.py gate --session-dir .acceptance/ci
```

必须满足 product 范围、representative/sustained 强度、适用需求/交互与技术检查、原始证据、版本环境和预算。缺档案、focused、只有单次成功、旧版本/环境或缺观察都会阻断。无需界面的服务可以有依据地声明交互不适用；需要人工或 computer use 的证据则安排实际执行，不能由 CI 自动编造。

快照和环境包含本机绝对路径，其他电脑的历史档案不能原样上传后冒充本次证据。只复制 report.json、手填 product_accepted 或复用旧 CI artifact 都不能获得 gate 通过。需要真实业务观察但暂时没有条件时，保留缺口，不扩大自动检查的结论。

模板不自动发布或部署。实际发布工作流必须依赖交付检查成功，或者由已有发布控制端调用 gate；只运行 change/full 的分支合并保护不会自动变成上线许可。

## GitHub 强制合并保护

新仓库先跑一次模板，确认固定检查名 **Acceptance CI**。在 GitHub 仓库 Settings → Branches / Rules 中，针对实际默认分支：

1. 要求通过 PR 合并，添加 **Acceptance CI** 为必要检查，来源选 GitHub Actions。
2. 要求分支跟上目标分支的最新提交；启用管理员也必须遵守/禁止绕过。
3. 保留已有必要检查和审查要求，禁止强推及删除主分支。
4. 查看一条尚未通过或失败的 PR，应显示合并被阻止；只有必要检查全部通过后才能合并。

模板不自动修改其他项目的远端权限。默认分支不是 main 时修改 push.branches；pull_request 不限制分支，避免默认分支变更后遗漏检查。复用现有工作流时需要保留那个作业的固定名字，将它加入相应保护。

工作流与固定作业没有 paths 过滤或条件跳过，也没有 continue-on-error；程序内部按风险选择，CI 失败直接让固定检查失败。这样避免必需工作流被过滤后一直 Pending，或依赖失败导致作业 skipped 却形成错误放行。[GitHub 必需检查说明](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/collaborating-on-repositories-with-code-quality-features/troubleshooting-required-status-checks)。

插件仓库自身的必要检查是 `validate (3.10)`、`validate (3.14)`，已绑定 GitHub Actions 并启用 strict 与管理员执行。业务项目应配置自己的检查，不复制这两个插件测试名称。

## 验证范围

可运行 `PLUGIN/scripts/ci_demo.py --output NEW_DIRECTORY`：隔离无界面示例先对说明变更只跑 fast，再修改真实消费契约；普通样本仍成功，但上界输入触发 integration 后 CI 失败。该示例验证选择、执行和阻断，不代表目标项目已完成 CI 接入，也不代表真实用户体验通过。
