# LightRoom 部署

## 适用场景

用于部署和维护 LightRoom（light-classroom）生产环境，包括代码发布、数据库迁移、容器重启和线上验证。

## 发布流程

1. 确认工作区、当前分支和未提交改动。
2. 在 `feature/assistant` 完成修改并提交，提交信息使用 `fix:`、`feat:` 或 `chore:` 前缀。
3. 切换到 `prod`，合并 `feature/assistant`，确认合并结果后构建前端和后端镜像。
4. 发布前备份线上数据库。生产数据库参数必须从服务器 `.env` 或容器环境读取，禁止猜测用户名、库名或密码。
5. 在 API 容器中执行 Alembic 迁移：

   ```bash
   docker exec light-classroom-api-api-1 alembic upgrade head
   ```

6. 迁移成功后重启 API 和 worker：

   ```bash
   docker restart light-classroom-api-api-1 light-classroom-api-worker-1
   ```

7. 检查健康状态和最近日志：

   ```bash
   docker ps
   docker logs --tail=100 light-classroom-api-api-1
   curl -fsS http://127.0.0.1:8000/health
   ```

## 数据库安全

- 任何迁移前先执行 `pg_dump`，备份文件写入服务器备份目录。
- 不删除表、不重建数据库、不执行 `DROP`，除非用户明确要求并已确认备份可恢复。
- PostgreSQL 默认仅通过 Docker 内网访问。需要外部管理时优先使用 SSH 隧道，不直接开放 5432 到公网。
- 数据库时区应统一核对：`SHOW timezone;`。时间字段若保存 UTC，接口或前端必须明确转换到 `Asia/Shanghai`，不能仅依赖数据库时区设置。

## 故障排查

- 出现“菜单权限加载失败”时，先查看 API 日志中的数据库字段错误，再检查 Alembic 当前版本和 head。
- 出现“求解进程失去心跳”时，检查任务 worker、Redis 连通性、心跳线程和多 seed 超时配置。
- 重启容器不会删除数据库数据；只有卷删除、表删除或显式清库操作可能造成数据丢失。
- 迁移失败时保留错误日志和数据库备份，禁止绕过迁移直接修改生产表结构。

## 完成标准

- `prod` 分支包含待发布提交。
- 数据库备份文件存在且非空。
- Alembic 成功升级到 head。
- API、worker 容器运行正常，健康检查返回 200。
- 登录、超管页面、排课页面至少各验证一次。
