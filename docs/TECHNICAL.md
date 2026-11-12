# GluePaw 技术文档

> English version: [TECHNICAL.en.md](TECHNICAL.en.md) — **由 AI 机器翻译，仅供参照，以中文版为准。**

本文档面向想读懂或修改源码的开发者。用户向的说明见 [README](../README.md)，隐私设计细节见 [PRIVACY.md](PRIVACY.md)。

## 1. 概览

GluePaw 是一个 PySide6 桌面应用，由三部分组成：

1. **采集层**：监听系统剪贴板，判定内容风险等级
2. **存储层**：普通内容加密入 SQLite；敏感内容只进内存
3. **展示层**：竖版弹窗，支持搜索、收藏、多选、置顶、明暗主题

设计上刻意保持「单进程 + 单数据库」：没有后台服务、没有网络、没有多进程通信。

## 2. 架构

```
                    ┌─────────────────────────────┐
   系统剪贴板 ──────▶│  app.py  Vault              │
                    │  · dataChanged → capture     │
                    │  · 每秒 tick → sweep         │
                    │  · 热键队列轮询               │
                    └──────────┬──────────────────┘
                               │
                    ┌──────────▼──────────────────┐
                    │  repository.py               │
                    │  · 风险判定 → 选存放位置      │
                    │  · 收藏 / 敏感 / 删除 状态机   │
                    │  · 合并内存 + 数据库视图       │
                    └───────┬───────────┬──────────┘
                            │           │
              ┌─────────────▼──┐   ┌────▼─────────────┐
              │ ephemeral.py   │   │ store.py          │
              │ 仅内存 + 倒计时 │   │ SQLite + 密文      │
              └─────────────┬──┘   └────┬─────────────┘
                            │           │
                            └─────┬─────┘
                                  ▼
                         vaultcrypto.py
                    Fernet 加密 / HMAC 盲索引 / 密钥
```

## 3. 模块职责

| 文件 | 职责 | 关键点 |
| --- | --- | --- |
| `main.py` | 入口 | 单实例锁、日志、初始主题 |
| `app.py` | 装配与调度 | 剪贴板监听、托盘、热键轮询、定时清理 |
| `config.py` | 路径与默认值 | `%LOCALAPPDATA%\GluePaw` |
| `vaultcrypto.py` | 加密 | DPAPI 保护主密钥、Fernet、盲索引 |
| `store.py` | 持久化 | 建表、去重 upsert、定期清理 |
| `ephemeral.py` | 内存暂存 | 会话密钥、monotonic 计时 |
| `repository.py` | 业务状态机 | 全部隐私规则都在这里 |
| `sensitive.py` | 内容识别 | 三级判定 + Luhn / 身份证校验 |
| `hotkey_win.py` | 全局热键 | 独立线程 + 消息循环 + 队列 |
| `theme.py` | 主题 | 双色板 + `@token` QSS 模板 |
| `icons.py` | 图标 | 全部用 QPainter 绘制，不依赖 emoji |
| `ui_main.py` | 主窗口 | 卡片、多选、置顶、搜索高亮 |
| `ui_settings.py` | 设置页 | 隐私、清理、外观三块 |

## 4. 数据模型

```sql
CREATE TABLE items (
  id                   INTEGER PRIMARY KEY AUTOINCREMENT,
  content              BLOB    NOT NULL,   -- Fernet 密文
  blind                TEXT    NOT NULL,   -- HMAC 盲索引，唯一
  sensitive            INTEGER NOT NULL,   -- 0/1
  favorite_at          REAL,               -- NULL = 未收藏
  sensitive_expires_at REAL,               -- 墙钟时间；NULL = 无倒计时
  ttl_snapshot         REAL,               -- 出生时的保留时长
  auto_clear_months    INTEGER,            -- 出生时的清理周期；NULL = 不清理
  source_app           TEXT,               -- 预留
  size                 INTEGER NOT NULL,
  created_at           REAL NOT NULL,
  last_used_at         REAL NOT NULL,
  use_count            INTEGER NOT NULL DEFAULT 1
);
```

### 为什么存「快照」

`ttl_snapshot` / `auto_clear_months` 记录的是**这条内容被捕获时**的设置。
用户之后把保留时长从 3 分钟改成 10 分钟，不会让已经在倒计时的内容延长——
这样行为可预测，也符合「以记录时的设置为准」的产品规则。

### 去重

`blind` 是 HMAC-SHA256 盲索引，唯一索引。同一内容重复复制时：

- 已存在 → 更新 `last_used_at`、`use_count += 1`
- 敏感内容 → 重置倒计时，而不是产生第二条

## 5. 核心状态机

一条记录只有两种落点：`mem`（内存）和 `db`（数据库）。

| 当前状态 | 事件 | 结果 |
| --- | --- | --- |
| 敏感·未收藏·倒计时中 | 到点 | 删除 + 清空匹配的系统剪贴板 |
| 敏感·未收藏 | 收藏 | 加密入库，倒计时继续走 |
| 敏感·已收藏·倒计时中 | 取消收藏 | 退回内存，**继承剩余时间** |
| 敏感·已收藏·倒计时已结束 | 取消收藏 | **立即删除**（二次确认） |
| 敏感·已收藏 | 倒计时到点 | 不删除，只标记过期 |
| 普通·未收藏 | 定期清理 | 按记录自己的周期淘汰 |
| 任何·已收藏 | 定期清理 | 豁免 |
| 关闭隐私模式 | — | 内存条目全部转存数据库，取消倒计时 |
| 普通 → 敏感（隐私开） | 手动切换 | 移入内存，按当前设置重新计时 |
| 普通 → 敏感（隐私关） | 手动切换 | 只打标记，不设倒计时 |

实现位置：`repository.py` 的 `capture` / `favorite` / `unfavorite` / `set_sensitive` / `set_privacy`。

## 6. 加密与密钥

```
用户密码（Windows 登录）
        │ DPAPI
        ▼
   key.bin（32 字节主密钥，文件中是 DPAPI 密文）
        │
        ├── Fernet(AES-128-CBC + HMAC-SHA256)  →  content 字段
        └── HMAC-SHA256(派生索引密钥)          →  blind 字段
```

- **主密钥**：`os.urandom(32)`，首次运行生成；Windows 上用 `CryptProtectData` 包一层
- **内容加密**：Fernet，随机 IV，自带完整性校验
- **盲索引**：`HMAC(key, 内容)`，不可逆，防字典攻击
- **会话密钥**：`SessionCipher` 每次进程启动随机生成，只用于内存暂存区

## 7. 线程模型

- **主线程**：Qt 事件循环，处理 UI、剪贴板、SQLite
- **热键线程**：`RegisterHotKey` + `GetMessage` 阻塞等待，收到 `WM_HOTKEY` 后
  往 `queue.Queue` 投递；主线程用 60ms 的 `QTimer` 轮询取出

数据库只在主线程访问，因此没有额外锁；剪贴板的 `dataChanged` 也在主线程触发。

## 8. 界面结构

```
MainWindow (QWidget, frameless, 9:16)
├── header_bar：搜索框 / 齿轮 / 多选 / 图钉 / 关闭
├── tab_bar：历史记录 | 收藏
├── QStackedWidget
│   ├── 列表页：QScrollArea → 按天分组 → ClipCard × N
│   └── 设置页：SettingsPage
└── footer_widget / selection_bar（二选一显示）
```

### 卡片 ClipCard

- 布局：预览文字独占一行，第二行是「状态 + 操作按钮」
- 富文本：搜索时用 `<span>` 给命中片段加底色；打码状态下不渲染富文本
- 阴影：`QGraphicsDropShadowEffect`，颜色随主题
- 多选模式：左侧出现复选框，点击卡片任意位置切换选中

### 置顶

切换 `Qt.WindowStaysOnTopHint` 需要重建原生窗口，因此 `set_pinned()` 会保存
位置、改 flags、再 `show()` 恢复。置顶期间关闭「失焦自动隐藏」，
并且确认弹窗也会被设为置顶，避免被主窗口盖住。

## 9. 主题系统

`theme.py` 维护 `LIGHT` / `DARK` 两个字典，QSS 模板里用 `@token` 占位，
运行时 `re.sub` 替换成具体颜色：

```css
QFrame#Card { background: @surface; border: 1px solid @border; }
```

切换主题 = 重新生成整份 QSS + `setStyleSheet` + 重建卡片（阴影颜色不同）。

主题来源有三种：跟随系统（`QStyleHints.colorScheme()`，失败则读注册表）、
强制浅色、强制深色，保存在 `settings.theme_mode`。

## 10. 搜索与高亮

当前实现是**内存过滤**：`store.list_items()` 会解密全部记录，
`Repository.list_items()` 合并内存条目后做 `in` 判断。

在几千到几万条的规模下足够快；条目再多时可以考虑：

- 惰性解密 / 分页
- SQLite FTS5（注意中文分词需要 trigram 或自建分词）
- 盲索引 token 表（支持按词精确匹配，但不支持子串）

高亮：命中片段用富文本 `<span style="background-color:...">` 标注，
文本先做 HTML 转义，换行转 `<br>`。

## 11. 测试

- `selftest.py`：纯逻辑，不依赖 GUI。覆盖敏感识别、加解密、去重、
  收藏状态机、隐私模式迁移、定期清理、搜索。
- `smoketest.py`：`QT_QPA_PLATFORM=offscreen` 下装配整个应用，
  打开设置页、刷新列表，验证 Qt 层没有异常。

## 12. 扩展点

### 平台适配

`hotkey_win.py` 是 Windows 专用。macOS 可用 `pynput` 或 `Quartz` 事件监听；
Linux X11 可用 `pynput`，Wayland 需要走 `org.freedesktop.portal.GlobalShortcuts`。
剪贴板监听目前依赖 Qt 的 `dataChanged`，跨平台部分已经具备。

### 图片 / 富文本

`items.kind` 字段目前固定为 text。扩展时建议：

- 图片存加密文件或 BLOB，数据库只存引用
- 预览区按类型渲染
- 大小上限单独控制

### AI 检索（未实现）

建议采用「本地检索 + 模型回答」的路线，而不是把历史全量发给 API：

1. 本地关键词/向量检索出候选条目
2. 过滤掉敏感与内存中的条目
3. 只把命中的少量片段拼进 prompt
4. 要求模型标注引用的条目编号，点击可复制

这样既能保持隐私边界，也能控制 token 成本。

## 13. 已知技术债

- 全局热键线程在退出时依赖 `PostThreadMessage`，极端情况下可能残留线程
- `setWindowFlags` 重建窗口时可能有轻微闪烁
- 卡片数量很大时（接近 300）阴影与富文本渲染会变慢
- 没有对 `instance.lock` 做崩溃恢复测试
- 平台判断散落在各处，值得抽一个 `platform/` 包
