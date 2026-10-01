# 架构

Python 标准库实现，无外部服务、数据库或第三方包。
app.py 提供 create_request 和 approve，申请状态保存于传入对象。
check_rules.py 是可重放规则验证，输出插件 native JSON。
运行方式：python3 check_rules.py --output 本次结果路径。
