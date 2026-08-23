# Issue tracker: GitHub

本仓库的 issues 与 specs 存放在 GitHub Issues，所有操作使用 `gh` CLI。

**仓库归属：issues 建在 `haneball17/MaaGakumasu`（origin，用户 fork），不要建到 upstream（`SuperWaterGod/MaaGakumasu`）。** 仓库内运行 `gh` 时会从 remote 自动推断，若推断到 upstream 需显式加 `-R haneball17/MaaGakumasu`。

前置条件（本机尚未满足时）：

- 安装 CLI：`winget install GitHub.cli`（装后重开终端）。
- fork 仓库需在 GitHub 网页 Settings → Features 启用 Issues。

## 约定

- **创建 issue**：`gh issue create --title "..." --body "..."`（多行 body 用 heredoc）。
- **读取 issue**：`gh issue view <number> --comments`，用 `jq` 过滤评论并取 labels。
- **列出 issues**：`gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'`，按需加 `--label` / `--state` 过滤。
- **评论**：`gh issue comment <number> --body "..."`。
- **加/去标签**：`gh issue edit <number> --add-label "..."` / `--remove-label "..."`。
- **关闭**：`gh issue close <number> --comment "..."`。

## Pull requests as a triage surface

**PRs as a request surface: no.** _（若本仓库开始把外部 PR 当功能请求处理，把此处改为 `yes`；`/triage` 会读这个标志。）_

设为 `yes` 后，PR 走与 issue 相同的标签和状态机，使用 `gh pr` 等价命令：

- **读 PR**：`gh pr view <number> --comments` 与 `gh pr diff <number>`。
- **列出待 triage 的外部 PR**：`gh pr list --state open --json number,title,body,labels,author,authorAssociation,comments`，只保留 `authorAssociation` 为 `CONTRIBUTOR` / `FIRST_TIME_CONTRIBUTOR` / `NONE` 的（丢弃 `OWNER` / `MEMBER` / `COLLABORATOR`）。
- **评论/标签/关闭**：`gh pr comment`、`gh pr edit --add-label`/`--remove-label`、`gh pr close`。

GitHub 的 issue 与 PR 共用一个编号空间，裸 `#42` 可能是任一种：先 `gh pr view 42`，失败再 `gh issue view 42`。

## 当技能说 "publish to the issue tracker"

创建一个 GitHub issue。

## 当技能说 "fetch the relevant ticket"

运行 `gh issue view <number> --comments`。

## Wayfinder 操作

供 `/wayfinder` 使用。**map** 是单个 issue，**child** issues 作为 tickets。

- **Map**：单个打 `wayfinder:map` 标签的 issue，body 持有 Notes / Decisions-so-far / Fog。`gh issue create --label wayfinder:map`。
- **Child ticket**：作为 GitHub sub-issue 链到 map（`gh api` 调 sub-issues endpoint）。sub-issues 未启用时，把 child 加进 map body 的 task list，并在 child body 顶部写 `Part of #<map>`。标签：`wayfinder:<type>`（`research`/`prototype`/`grilling`/`task`）。认领后把 ticket assign 给驱动的开发者。
- **Blocking**：优先用 GitHub **原生 issue dependencies**（UI 可见的规范表达）。加边：`gh api --method POST repos/<owner>/<repo>/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`，其中 `<blocker-db-id>` 是 blocker 的数字 **database id**（`gh api repos/<owner>/<repo>/issues/<n> --jq .id`，不是 `#number` 也不是 `node_id`）。GitHub 会回报 `issue_dependencies_summary.blocked_by`（仅开放 blocker，作为实时闸门）。dependencies 不可用时，退回 child body 顶部的 `Blocked by: #<n>, #<n>` 行。ticket 在所有 blocker 关闭后才算解除阻塞。
- **Frontier 查询**：列出 map 的开放 children（`gh issue list --state open`，限定 map 的 sub-issues / task list），丢掉有开放 blocker（`issue_dependencies_summary.blocked_by > 0`，或 `Blocked by` 行里有开放 issue）或有 assignee 的；按 map 顺序取第一个。
- **Claim**：`gh issue edit <n> --add-assignee @me`，这是会话的第一个写操作。
- **Resolve**：`gh issue comment <n> --body "<answer>"` → `gh issue close <n>` → 把上下文指针（gist + 链接）追加到 map 的 Decisions-so-far。
