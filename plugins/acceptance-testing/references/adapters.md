# 工具适配与能力边界

执行工具不安装框架；发现项目已有测试框架后选择它的结构化报告。未知框架可以输出 native 或 JUnit，不编造“已适配”。命令/版本参数以本项目实际文档与帮助为准。

## 当前可解析格式

- `junit`：真实 testcase 节点；failure/error 判失败，skipped 判跳过，零节点受阻。用于已有 pytest/Jest/Vitest/Go 等能产生 JUnit 的配置，本插件不自带这些框架或报告扩展。
- `playwright`：官方 JSON suites/specs/tests 的最终 expected/unexpected/flaky/skipped；expectedStatus 非 passed 的预期失败不作为稳定业务通过。全局 errors 判失败，零测试受阻。
- `native`：`{"tests":[{"name":"业务断言名","status":"passed"}]}`；状态可 passed/failed/skipped/flaky，非空列表。实际断言脚本可记录 expected/actual 等额外内容。不能人工编造测试结果再称自动测试通过。
- `exit`：构建、类型、明确静态检查的退出码。零用例检查不适用于该类命令，所以不得用于未解析的测试套件。

结构化结果只能写到本次 `{evidence_dir}`。例如已有 pytest 支持 JUnit 时：`["{python}","-m","pytest","--junitxml={evidence_dir}/result.xml"]`。若项目 pytest 不存在，不自动安装。

Playwright 可使用项目已有配置或环境参数将 JSON 写入本次证据目录。CLI argv 不设置环境变量；需要时使用项目已有的适配脚本或 `node -e` 明确设置过程环境并启动现有框架，避免添加依赖或运行 npx 自动下载。也可使用宿主浏览器执行后导入 observation。自动化与 computer use 的观察格式相同，来源要说明。

## 宿主与模型

宿主负责模型调用、浏览器、computer use、工具认证与权限。插件负责路由和档案，不使用额外 LLM API，也不将能力声明当可用事实。scan 的 browser/computer_use=unknown 需由代理核实。

不支持视觉操作可保留命令/接口验证，并把 UI 覆盖标受限；不偷偷降标准。被测 AI 产品多个模型用固定样本与指标比较，记录真实模型标识和版本，支持范围明确。

当前跨模型/跨宿主的真实行为适配需实际前向测试；Python 离线自测只证明执行内核与样例，不证明所有模型能正确操作界面。
