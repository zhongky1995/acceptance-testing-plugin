# 参与改进

先阅读 [产品范围](docs/PRODUCT.md)、[架构说明](docs/ARCHITECTURE.md) 与 AGENTS.md。改进应帮助负责人获得可信验收结论，并保留环境复用和成本控制。

## 反馈问题

在 Issues 中提供插件版本、Python 版本、宿主与操作系统、最小复现步骤、预期和实际结果。分享脱敏后的方案或报告即可；不上传密钥、客户数据、完整私有代码或未检查的截图。

## 提交改进

说明解决的具体问题、范围与验证方法。修改执行、预算、门禁或报告规则时，应加入能区分错误与正确行为的回归用例。文档小改动不要求增加测试。

本地验证只使用 Python 标准库和隔离样例：

```sh
python3 -m unittest discover -s plugins/acceptance-testing/tests -v
python3 plugins/acceptance-testing/scripts/demo.py --output dist/demo-contribution
python3 scripts/package.py
```

演示输出目录需不存在；预期初轮 failed、修复后的新轮 passed。GitHub Actions 在 Python 3.10 与 3.14 上执行这些检查。不为验证额外安装业务依赖或调用收费服务。

核心约束：不得将未执行/跳过视为通过，不得在执行后降低标准，不得删除首次失败，不得把模拟依赖的结果说成真实服务结果。新增适配器必须处理零测试、失败、跳过、不稳定与缺失报告。

新增来源和示例时确认可以公开分发，保留必要的许可与来源。仓库与发行包采用根目录 LICENSE 中的 MIT 许可证。
