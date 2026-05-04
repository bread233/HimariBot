# HimariBot AI Coding Rules

## Language

- 回答用户时使用中文。
- 代码、变量名、函数名保持项目原有风格。
- 不要用英文长篇解释，除非用户要求。

## Safety Rules

- 默认只做最小 patch。
- 修改前必须先执行 `git status`。
- 修改前必须说明计划修改哪些文件。
- 不允许整文件重写。
- 不允许格式化整个文件。
- 不允许删除现有 CSS、HTML、script、函数，除非用户明确要求。
- 不允许修改用户没有指定的功能。
- 如果预计修改超过 30 行，必须先停止并说明修改计划，等待确认。
- 修改后必须执行 `git diff --stat` 和 `git diff`，并总结改动。
- 不要自动提交 commit，除非用户明确要求。

## Repository Notes

- 当前工作分支应为 `ai/openhands-test`。
- 主要项目路径是 `/workspace/HimariBot`。
- NoneBot 插件代码位于 `src/plugins/`。
- 修仙 Web 页面主要文件：
  - `src/plugins/nonebot_plugin_xiuxian_2/xiuxian/xiuxian_web/templates/game.html`

## game.html Rules

- `game.html` 是大文件，禁止整文件重写。
- 修改 `game.html` 时必须先用 `grep`、`sed`、`python` 或类似命令定位相关函数和局部行号。
- 一次最多读取相关区域 150 行。
- 默认只修改目标函数内部。
- 宗门页面逻辑优先定位 `renderSect(sect)`。
- 宗门任务展示逻辑优先定位 `taskContentHtml`。
- 未确认后端 API 名称前，不要新增真实 onclick 调用。
- 找不到字段或接口时，必须停止并说明需要用户确认的信息，不要猜。

## Required Workflow

For every coding task:

1. Run `pwd`.
2. Run `git status`.
3. Confirm current branch.
4. Locate relevant files with search commands.
5. Read only the relevant snippets.
6. Explain the minimal plan.
7. Make the smallest safe change.
8. Show `git diff`.
9. Stop and wait for user review.
