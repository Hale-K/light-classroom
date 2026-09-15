# 排课复杂任务 Supervisor 迭代计划

## 目标

只对“排课准备检查”和“排课失败诊断”启用受控的 Supervisor 多 Agent 协作。简单问候、单模块说明和普通查询继续走现有 Direct / 单 Agent 路径，避免无意义的延迟和 Token 消耗。

## 当前基线

当前系统是单 Agent 架构：`IntentGateway` 识别意图，`HarnessRouter` 选择工具权限和执行策略，`ReactLoop` 在一个 Agent 内循环调用工具，`execute_run()` 在后台运行一个 Assistant Turn。现有 `scheduling worker` 是业务 Worker，不作为子 Agent。

## 实施步骤

### 阶段一：Supervisor 契约（当前步骤）

- 定义 Supervisor 输入、子任务、子 Agent 结果和汇总结果的数据结构。
- 明确每个子 Agent 只能使用服务端注册的工具和本校权限。
- 不改变现有请求路由和回答结果。

验收：类型可独立测试；现有 Assistant、Run 和前端构建全部通过。

### 阶段二：排课准备检查

- 新增 `SchedulingReadinessSupervisor`。
- 并行执行学期/课位、课时、任教关系、规则四项只读检查。
- Supervisor 汇总为“已满足 / 缺失 / 下一步”，并写入 `AiRun.events`。
- 任何子任务失败只影响对应检查，不阻塞其他检查。

验收：输入“帮我检查排课准备情况”时，能返回稳定清单；不调用写入工具。

### 阶段三：排课失败诊断

- 新增 `SchedulingDiagnosisSupervisor`。
- 分别读取生成任务状态、准备数据、规则和历史事件。
- 区分观测事实、推断原因和可验证的恢复步骤。
- 通过事件流展示每个子 Agent 的开始、完成和失败状态。

验收：输入“为什么排课失败”时，能给出证据来源和下一步；不自动重试生成、不修改规则。

### 阶段四：接入 Router 和后台 Run

- 仅当意图为 `READINESS` 或 `DIAGNOSIS` 且复杂度达到阈值时选择 Supervisor。
- 复杂任务继续使用 `/assistant/runs`、Inbox 和 SSE；简单问题不进入 Supervisor。
- 为 Supervisor 设置总超时、子任务超时、最大并发数和取消传播。

验收：简单问题延迟不增加；复杂任务可在后台恢复、steer，并能查看事件轨迹。

### 阶段五：验证与上线保护

- 添加单元测试、超时/取消测试、权限隔离测试和重复请求测试。
- 验证所有子 Agent 不可自行增加工具、访问其他租户数据或执行写入。
- 记录耗时、Token、子任务成功率和降级原因。

验收：目标测试通过，现有回归测试通过，前端构建通过后再考虑灰度启用。

## 关键约束

- Supervisor 只负责拆解、调度和汇总，不直接绕过 Tool Gateway。
- 子 Agent 默认只读；规则写入仍必须经过独立确认流程。
- 不为简单请求启动多 Agent。
- 每个阶段单独提交，出现问题可以回滚到上一阶段。
