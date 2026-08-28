# 排课、排考与排座系统规格

## 目标

为教务主任提供可落地的排课、排考与班级排座能力：维护教师、学科和任教关系；按周生成无教师/班级冲突的课表；按指定起始日期展开为日期课表；基于考试试卷生成考试日期与监考安排；按班级名单生成、启用和查看座位表。

## 已确认假设

- 默认教学周为周一至周五，每天 8 节，界面允许调整。
- 排课输入以“任教关系 + 每周课时数”为准。
- 硬约束：同一班级、同一教师在同一时段只能出现一次。
- 同一学科同一天尽量不重复；无法完全满足时优先保证硬约束并返回未排课项。
- 日期课表从用户选择的周一开始，按周课表展开为带具体日期的表格。
- 排考以已创建考试下的试卷为科目来源，默认每天上午、下午两场，自动跳过周末。
- 排考按日期与场次生成时间轴，可配置起始日期、上午/下午时间和默认考场。
- 排座面向行政班教室，不绑定考试；支持按名册、蛇形、男女交错和随机四种自动规则。
- 座位容量不足时拒绝生成；空余座位保留为空。

## 技术栈与命令

- 后端：FastAPI、SQLModel、SQLAlchemy Async、Alembic、pytest。
- 前端：Vue 3、TypeScript、Element Plus、Pinia、Vite。
- 后端测试：`pytest -q`
- 后端检查：`python -m compileall app`
- 前端构建：`pnpm --filter @zhiheng/web build`

## 项目结构

- `backend/app/services/scheduling.py`：纯排课与排座算法。
- `backend/app/api/v1/scheduling.py`：基础资源、排课和日期课表 API。
- `backend/app/api/v1/seating.py`：座位生成、列表和启用 API。
- `backend/app/api/v1/exam_scheduling.py`：考试日程生成与查询 API。
- `backend/tests/`：算法单元测试。
- `frontend/packages/shared/`：前后端契约对应的 TypeScript 类型。
- `frontend/packages/api/`：API 客户端。
- `frontend/apps/web/src/views/`：排课与排座页面。

## 接口契约

- `GET /api/v1/scheduling/resources`：教师、学科、班级、任教关系。
- `POST /api/v1/scheduling/assignments`：新增或更新任教关系及每周课时。
- `POST /api/v1/scheduling/generate`：生成并保存周课表，返回未排课项和冲突统计。
- `GET /api/v1/scheduling/weekly`：按班级、学年、学期查询周课表。
- `GET /api/v1/scheduling/calendar`：按周一日期展开具体日期课表。
- `GET /api/v1/seating/arrangements`：查询班级历史座位表。
- `POST /api/v1/seating/generate`：按规则生成座位表。
- `PATCH /api/v1/seating/arrangements/{id}/activate`：启用指定座位表并归档旧版本。
- `POST /api/v1/exam-scheduling/generate`：按考试试卷生成考试日程与监考安排。
- `GET /api/v1/exam-scheduling/{exam_id}`：查询考试日期表。

所有接口沿用现有 `{ code, message, data }` 响应格式和租户隔离。

## 测试策略

- 单元测试：排课满足教师/班级无冲突、课时数正确、日期映射正确。
- 单元测试：座位容量校验、蛇形顺序、男女交错和固定随机种子。
- 单元测试：排考自动跳过周末、场次数正确、监考教师不重复占用。
- 集成级检查：FastAPI 路由可导入，Pydantic 输入边界生效。
- 前端：TypeScript 构建通过，浏览器检查核心表格与座位布局。

## 边界

- 始终：保留多租户过滤；生成前验证引用资源；返回未排入课程而非静默丢失。
- 本期不做：复杂走班、单双周课、教师个性化禁排时段、跨校区教室容量、考试考场座次。
- 不新增外部排课依赖，先使用可测试的确定性贪心算法。

## 验收标准

- 可以维护一条包含教师、学科、班级、学年和周课时的任教关系。
- 一键生成后，同一教师和班级没有时段冲突。
- 可以切换班级查看 5×8 周课表。
- 选择任意周一后生成带月日和星期的日期表。
- 可以选择班级、行列和规则生成座位表，容量不足有明确错误。
- 可以选择考试和起始日期，生成按日期分组的上午/下午考试时间轴。
- 新座位表启用后，同班旧座位表自动归档。
- 后端测试和前端生产构建通过。
