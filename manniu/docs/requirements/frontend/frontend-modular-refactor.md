# ManNiu 前台模块化重构方案

## 1. 背景与目标

当前前台只有 `research` 与 `stock-picker` 两个 feature，但 `App.tsx` 同时承担应用入口、路由、研究页编排、URL 状态、数据请求和用户操作；`stock-picker` 反向依赖 `research` 的组件与 API。目标是建立清晰的模块边界：

```text
app -> features -> shared
```

- `app` 只负责应用启动、路由和全局 Provider。
- `features` 负责独立业务流程，不直接依赖其他 feature。
- `shared` 负责跨业务复用的 UI、API 客户端、hooks、类型和工具。
- API DTO、领域模型和页面 ViewModel 分离。
- 保持现有 URL：`/`、`/stock-picker`、`/login`、`/public/api`。

## 2. 当前问题

### P0

1. `stock-picker/StockPickerPage.tsx` 直接引用 `research/components/TopBar` 和 `research/services/researchApi`。
2. `App.tsx` 内部的 `ResearchHomePage` 承担研究业务全部编排，根入口难以测试和懒加载。
3. `researchApi.ts` 混合研究列表、行情、财务、估值、技术面、个人状态和选股 API。

### P1

1. 页面组件同时处理请求、状态、DTO 映射、排序、导出和展示。
2. URL 参数解析与 `history.replaceState` 散落在页面内。
3. `App.css`、feature CSS 和 overrides 依赖全局选择器与加载顺序。
4. 请求、错误和 AbortController 逻辑重复。

### P2

1. `research/types.ts` 按页面而非领域集中所有类型。
2. feature 没有稳定的公共出口，外部可以直接依赖内部文件。
3. feature 缺少 service、mapper、hook 和页面交互级测试。

## 3. 目标目录

```text
src/
├── app/
│   ├── App.tsx
│   ├── routes.tsx
│   └── providers.tsx
├── shared/
│   ├── api/
│   │   ├── httpClient.ts
│   │   └── errors.ts
│   ├── ui/
│   │   └── TopBar.tsx
│   ├── hooks/
│   ├── types/
│   └── utils/
└── features/
    ├── research/
    │   ├── ResearchPage.tsx
    │   ├── components/
    │   ├── hooks/
    │   ├── services/
    │   ├── types/
    │   └── styles/
    └── stock-picker/
        ├── StockPickerPage.tsx
        ├── components/
        ├── hooks/
        ├── services/
        ├── types/
        ├── utils/
        └── styles/
```

## 4. 分八步实施

### 步骤 1：建立基线与特征测试

- 记录现有入口、URL、API 和 CSS 选择器。
- 保留并拆分现有 `App.test.tsx`，补充研究页、选股页和路由测试。
- 纯函数优先测试：DTO mapper、CSV 导出、URL 参数解析、数值格式化。

验收：`npm run build`、`npm run test` 通过。

### 步骤 2：统一 API 客户端

新增 `shared/api/httpClient.ts`，统一：

- `VITE_API_BASE_URL`。
- access token 注入。
- JSON 解析。
- 非 2xx 错误转换。
- `AbortSignal` 透传。

之后按业务拆分 service，禁止组件直接调用 `fetch`。

### 步骤 3：修正 feature 依赖方向

- 将 `TopBar` 移至 `shared/ui` 或 `app/layout`。
- 将选股 API、DTO 和类型从 `research` 移入 `stock-picker`。
- `stock-picker` 不再 import `research`。
- 为 feature 建立 `index.ts` 公共出口，外部不引用内部实现路径。

### 步骤 4：迁移研究页

将 `ResearchHomePage` 从 `App.tsx` 移入 `features/research/ResearchPage.tsx`。`App.tsx` 只保留应用入口和路由装配。

### 步骤 5：抽取请求 hooks

研究页拆为 `useResearchList`、`useStockOverview`、`useFinancialOverview`、`useValuation`、`usePersonalStockState`；选股页拆为 `useStockSelection`。页面组件只组合状态和视图。

### 步骤 6：拆分高复杂度组件

- `StockPickerPage` 拆为 Filters、Summary、Toolbar、Results。
- `TechnicalTrend` 拆为数据 hook、图表计算和展示组件。
- CSV 导出、日期处理、排序和 DTO 映射移至纯函数模块。

### 步骤 7：整理样式边界

- `App.css` 只保留 reset、主题变量和应用级样式。
- feature 样式放在对应 `styles/`。
- 以 feature 根 class 或 CSS Modules 隔离选择器。
- 合并并删除 `research-overrides.css`、`stock-picker-overrides.css` 的重复规则。

### 步骤 8：引入轻量路由与懒加载

使用 `react-router-dom` 声明路由，支持浏览器前进后退和页面级懒加载：

- `/` -> research
- `/stock-picker` -> stock picker
- `/login` -> API login
- `/public/api` -> API Lab

路由参数通过统一 query parser 管理，不在 feature 中直接拼接 URL。

## 5. 本次实施状态

- 已安装 `react-router-dom`，路由表位于 `src/app/routes.tsx`。
- 已保留 `/`、`/stock-picker`、`/login`、`/public/api`，并兼容旧的 `#universe` 入口。
- 已建立 `src/shared/ui/TopBar.tsx` 和 `src/features/stock-picker/services/stockSelectionApi.ts` 公共边界。
- 已建立 `src/shared/routing/queryParams.ts`，研究页的 URL 读写已集中到该工具。
- TopBar 的实际实现和搜索/账户 API 已迁移至 `src/shared/ui` 与 `src/shared/services`，旧 `research/components/TopBar.tsx` 已删除。
- 选股 DTO、行业列表和选股结果 API 已迁移至 `stock-picker/services/stockSelectionApi.ts`，research service 不再声明选股相关符号。
- 选股行业加载和查询状态已迁移至 `stock-picker/hooks/useStockSelection.ts`，页面保留展示、筛选和排序状态。
- 选股样式已合并为单一 `stock-picker.css`，并通过 `@scope (.stock-picker-page)` 隔离；旧 `stock-picker-overrides.css` 已删除。
- 当前 `npm run build` 和 `npm run test -- --run` 已通过。

## 5.1 本轮迁移定义与验收

本轮先完成步骤 3、5、7 的最小闭环，再继续扩大拆分范围：

1. `shared/ui/TopBar.tsx` 必须包含 TopBar 的实际实现，不能只是转出 `research` 的 re-export。
2. `stock-picker/services/stockSelectionApi.ts` 必须包含选股 DTO、行业 DTO、响应解析和 API 请求实现；`research/services/researchApi.ts` 不再声明或导出选股相关符号。
3. `stock-picker/hooks/useStockSelection.ts` 负责行业列表加载和选股查询状态；页面只保留筛选条件、排序和展示状态。
4. 选股页面的 CSS 统一挂在 `.stock-picker-page` 根节点下；旧的 `stock-picker-overrides.css` 合并后删除，避免加载顺序覆盖。
5. 迁移后执行依赖检查，`src/features/stock-picker` 不得出现 `../research` 或 `../../research` 导入。

不改变后端接口路径、请求字段、响应映射、现有 URL 和用户可见文案。迁移完成后必须通过 `npm run build` 与 `npm run test -- --run`。

## 6. 约束与验收

- 不改变后端 API 请求和响应契约。
- 不改变已有页面 URL 和用户可见功能。
- 每一步只改一个责任边界，并运行对应测试。
- 完成后执行：

```text
npm run build
npm run test
npm run lint
```

- 重点检查：无 `stock-picker -> research` 依赖、无 feature 组件直接 `fetch`、无全局 overrides 依赖、浏览器前进后退可恢复页面状态。

## 7. 回滚策略

每一步保持独立提交；若某一步失败，回滚该步骤对应文件和依赖变更，不回滚已验证的前置步骤。路由切换保留原 URL，必要时可以暂时保留旧入口作为 fallback。
