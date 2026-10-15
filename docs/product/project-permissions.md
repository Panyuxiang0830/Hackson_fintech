# 项目成员权限与管理界面

2026-10-16，REQ-016/resource_access_controls；用户确认的团队需求。

管理员按员工和数据集配置项目资格：已分配项目以卡片展示，搜索项目名称并添加，点击卡片的移除按钮撤权。修改自动保存并递增权限版本，写入审计。页面保留来源开关与密级，移除演示配置标题、demo后缀、部门说明及实现解释。

有项目标签的文档要求员工项目列表包含该项目；空列表不代表全部项目。未标项目的文档不受项目层限制。两者都必须通过原来源ACL、密级、部门及本地撤权规则；项目成员资格不能替代来源授权。SQL、Qdrant、相关资料展开、原文与交付统一使用这一规则。

目录包含原SwiftUI与新增五个项目，共六个：SwiftUI Telemetry Dashboard、Marathon Pacing Dashboard、Firebase Mobile Analytics、CloudWatch Monitoring、Pipeline Failure Alerts、Telemetry Pipeline Reliability。`config/project-permissions.example.json` 显式固定14份资源及内容哈希，保留正文、原ACL和既有密级/部门，仅修改项目元数据。目录是本轮人工整理的资料分组，不宣称原数据集已有完整企业项目目录；其他文本不批量打标签。

管理员目录接口沿用 `/api/admin/content-scopes` 的 `project_catalog`；`/api/admin/permissions` 的 `project_catalog` 操作登记目录、`project_membership` 操作增删资格。项目ID有数据集前缀并由服务端核对目录，用户不能自行授予项目。

运维工具 `scripts/apply_project_permissions.py` 默认预检，显式 `--apply` 后通过既有队列发布14份白名单。先备份文档、身份及审计，执行前后核对所有非白名单文档摘要不变。迁移旧SwiftUI项目时不自动恢复旧的项目拒绝状态。初始Jax分配SwiftUI、CloudWatch和Telemetry Reliability；Alex分配Marathon、Mobile Analytics和Pipeline Alerts。其他员工由管理员按需添加。

该变更把旧 `Actor.projects` 的“非空时全库白名单”语义改为“项目成员资格”；未标项目资料继续遵守原ACL。旧部署回退不理解新成员限制，出现问题应保持新策略并修复，不能在已标注项目数据上直接启动旧版放行策略。

部署与实际验收待完成后补充；自动回归覆盖无项目资格拒绝、空项目可读、添加/撤销生效、三种检索一致、原文拒绝、来源和密级不能被成员资格绕过、普通员工不能调用管理接口以及哈希/幂等。
