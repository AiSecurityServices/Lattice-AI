# React + TypeScript + Vite

This template provides a minimal setup to get React working in Vite with HMR and some Oxlint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Oxc](https://oxc.rs)
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/)

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the Oxlint configuration

If you are developing a production application, we recommend enabling type-aware lint rules by installing `oxlint-tsgolint` and editing `.oxlintrc.json`:

```json
{
  "$schema": "./node_modules/oxlint/configuration_schema.json",
  "plugins": ["react", "typescript", "oxc"],
  "options": {
    "typeAware": true
  },
  "rules": {
    "react/rules-of-hooks": "error",
    "react/only-export-components": ["warn", { "allowConstantExport": true }]
  }
}
```

See the [Oxlint rules documentation](https://oxc.rs/docs/guide/usage/linter/rules) for the full list of rules and categories.

## UI 设计规范

本前端采用「浅色极简事务风（Linear / Notion 风）」，对应以下 agent skill（已安装到 `$CODEX_HOME/skills`）：

- `redesign-existing-projects`：升级已有项目时先审计再修，不重写。
- `minimalist-ui`：暖单色、细 `1px` 描边、克制饱和度、tabular 数字、bento 网格。
- `design-taste-frontend`：通用硬性规则 + 可调拨杆（本项目取 `DESIGN_VARIANCE ≈ 2`、`MOTION_INTENSITY ≈ 2`、`VISUAL_DENSITY ≈ 8`）。

完整重构方案见 `../docs/superpowers/plans/2026-08-26-lattice-ai-ui-refresh-plan.md`。

设计 token 集中在 `src/index.css` 的 `:root`（`--bg / --surface / --border / --text / --accent / --radius-* / --space-* / --shadow-* / --z-*`）。约定：

- 使用语义 token，不要在组件里散落裸 hex。
- 卡片用 hairline 描边，不滥用阴影；浮动层（抽屉 / 下拉 / 弹窗 / FAB）才用 `--shadow-*`。
- 数字 / ID / 日志用等宽字体 + `tabular-nums`。
- 主操作按钮用炭黑（`--primary`），强调色 `--accent` 只用于聚焦 / 链接 / 激活态 / 状态标签。
- 所有交互元素补齐 hover / active / focus / loading / empty / error 状态；破坏性操作用 `ConfirmDialog`，不用 `window.alert`。
