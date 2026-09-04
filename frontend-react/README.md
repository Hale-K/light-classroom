# 前端

学校教务与平台超管同一套 Vite 应用。

```bash
pnpm install
pnpm dev          # http://localhost:5176
pnpm typecheck
pnpm build        # 产物 dist/
```

开发时 `/api/v1` 默认代理到 `http://127.0.0.1:8001`。页面路径见 [docs/frontend.md](../docs/frontend.md)。
