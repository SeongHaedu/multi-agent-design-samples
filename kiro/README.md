# kiro/ — Kiro 用

Kiro の Agent Skills と Sub-agents を使って `agentcore-log-investigation` ワークフローを実行するための構成です。

## できること

- `reproduce/` でデプロイした AgentCore Runtime のログを、4 ステップのワークフロー型 Skill (目的確認 → ログ取得と要約 (Sub-agent) → 結論提示 → 結論のレビュー (Sub-agent)) で調査します。
- ログの取得・要約・レビューはすべて専用の Sub-agent (`error-investigator`、`latency-investigator`、`reviewer`) に委譲し、main agent の context にはログの生データを一切読み込みません。

## 構成

```
kiro/
├── README.md
└── .kiro/
    ├── steering/
    │   └── language.md             日本語での応答ルール (inclusion: always)
    ├── skills/
    │   └── agentcore-log-investigation/
    │       └── SKILL.md            4 ステップのワークフロー本体 (agentskills.io 準拠)
    └── agents/
        ├── log-investigator.json   main agent (tools: subagent, read, write)
        ├── error-investigator.json エラー調査用 Sub-agent (tools: read, write, shell)
        ├── latency-investigator.json レイテンシ調査用 Sub-agent (tools: read, write, shell)
        └── reviewer.json           結論レビュー用 Sub-agent (tools: read のみ)
```

Kiro の Agent 設定ファイルは JSON と Markdown のどちらの形式でも書けます。両方同じフィールド (`name` / `description` / `tools` / `excludedTools` / `prompt` / `model` / `resources`) を持ちます。本リポジトリでは、`prompt` フィールドが指示本文をどこに置くかという点で Markdown 形式に曖昧さが残ると判断し、フィールドの意味が一意になる JSON 形式を使っています。

- Custom Agents (Sub-agents を含む): https://kiro.dev/docs/custom-agents/ 、https://kiro.dev/docs/custom-agents/subagents/
- Agent Skills (agentskills.io 準拠。frontmatter に `name` と `description` が両方必須): https://kiro.dev/docs/skills/

## Sub-agent への委譲とツールの割り当て

main agent が Sub-agent を起動するには、`tools` に `subagent` を含める必要があります。これが無いと委譲できません ("Without it, the agent can't delegate.")。`log-investigator.json` は `"tools": ["subagent", "read", "write"]` を指定しています。`read` は Step 3 で Sub-agent の成果物を読むために、`write` は Step 3 で結論を `conclusion.md` に保存するために必要です。ログの生データを取得するツール (`shell`) は持たせていないため、main agent は構造的にログを直接取得できません。

Sub-agent 側のツールは、それぞれの定義ファイルで絞ります。

| Sub-agent | tools | 理由 |
|---|---|---|
| `error-investigator` | `read`, `write`, `shell` | `../tools/logs_insights.py` の実行と Markdown の保存に必要です |
| `latency-investigator` | `read`, `write`, `shell` | 同上です |
| `reviewer` | `read` | ファイルの書き込みを構造的に禁止します |

`reviewer.json` に `read` だけを割り当てているため、この Sub-agent は `prompt` の指示文に頼らず、構造的にファイルを書き込めません。

## 承認プロンプトを省く設定

Sub-agent の起動やコマンド実行のたびに承認を求められると、Skill の Checkpoint で取る承認と二重になります。ユーザーの合意は Checkpoint で取る設計のため、ツールの実行そのものは `permissions` で許可しています。

```json
"permissions": {
  "rules": [
    { "capability": "subagent", "match": ["error-investigator", "latency-investigator", "reviewer"], "effect": "allow" },
    { "capability": "fs_read", "match": ["**"], "effect": "allow" }
  ]
}
```

`capability` に指定できるのは `fs_read` / `fs_write` / `shell` / `web_fetch` / `web_search` / `mcp` / `subagent` / `all` です。`effect` は `allow` (確認なしで実行)、`ask` (確認する)、`deny` (常に拒否) の 3 つで、どのスコープにあっても `deny` が優先されます。

各エージェントに与えた許可は次のとおりです。書き込みとコマンド実行は `match` で範囲を絞っています。

| エージェント | 許可した capability と match |
|---|---|
| `log-investigator` | `subagent` (3 つの Sub-agent 名)、`fs_read` (`**`)、`fs_write` (`outputs/**`) |
| `error-investigator` | `shell` (`python3 *`)、`fs_read` (`**`)、`fs_write` (`outputs/**`) |
| `latency-investigator` | 同上 |
| `reviewer` | `fs_read` (`**`) のみ |

起動のたびに確認したい場合は、該当するルールの `effect` を `ask` に変えてください。

> [!NOTE]
> 旧形式の `toolsSettings.subagent` (`availableAgents` / `trustedAgents`) は CLI 3.0 と IDE 1.0 で非推奨になり、権限の指定は `permissions` に移りました。本リポジトリでは `permissions` を使い、あわせて旧形式の `allowedTools` も併記しています。kiro-cli 2.24.0 のように `permissions` へ移行する前のバージョンでも承認プロンプトを省けるようにするためです。旧形式の設定ファイルは `/upgrade-agent` で変換できます。

出典: https://kiro.dev/docs/custom-agents/subagents/ 、https://kiro.dev/docs/custom-agents/configuration-reference/

カスタムエージェントは既定では Skill もステアリングも読み込みません。`log-investigator.json` だけが `resources: ["file://.kiro/skills/**/SKILL.md", "file://.kiro/steering/**/*.md"]` を持ち、このエージェントを起動したときに Skill の本文と `.kiro/steering/language.md` (日本語での応答ルール) が読み込まれます。3 つの Sub-agent はそれぞれの `prompt` に完全な指示を持っているため、Skill を参照する必要はありません。

出典 (カスタムエージェントでステアリングを読み込むには `resources` に追加が必要): https://kiro.dev/docs/steering/

## 使用するモデル

4 つのエージェント定義はいずれも `"model": "claude-opus-5"` を指定しており、Claude Opus 5 を使います。`model` を省略した場合は Kiro の既定モデルが使われます。

`tools/logs_insights.py` と `tools/span_filter.py` はこのディレクトリの外 (リポジトリ ルートの `tools/`) にあります。3 つの Sub-agent の `prompt` はいずれも `../tools/...` という相対パスで参照する前提になっています。そのため、Kiro は必ずこの `kiro/` ディレクトリを起点 (cwd) にして起動してください。

## 実行手順

1. リポジトリ ルートで依存パッケージをインストールします (未実施の場合)。

   ```bash
   cd /path/to/multi-agent-design-samples
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. `reproduce/README.md` の手順で AgentCore Runtime をデプロイし、ログを蓄積させます。

3. Kiro CLI (`kiro-cli`) をインストールします (未実施の場合)。

   ```bash
   # macOS / Linux
   curl -fsSL https://cli.kiro.dev/install | bash

   # Windows (PowerShell)
   irm 'https://cli.kiro.dev/install.ps1' | iex
   ```

   Homebrew での配布は公式に非対応と明記されています。インストール後、ブラウザ認証が必要です。認証し直す場合は `kiro-cli login`、問題の診断には `kiro-cli doctor` を使います。

   出典: https://kiro.dev/docs/getting-started/installation/ 、https://kiro.dev/docs/cli/setup/

4. このディレクトリに移動し、`log-investigator` エージェントを指定して Kiro CLI を起動します。

   ```bash
   cd kiro
   kiro-cli --agent log-investigator
   ```

   出典 (特定のエージェントを指定して起動する構文): https://kiro.dev/docs/cli/chat/

5. 調査内容を伝えます。`log-investigator` は起動時に `agentcore-log-investigation` Skill を読み込んでいるため、調査内容を伝えるだけでワークフローが始まります。

   ```
   > AgentCore Runtime 上のエージェントが失敗している。原因を調べてほしい。
   ```

6. Step 1 の Checkpoint でログ グループ名・対象期間・調査目的を確認し、`(c)ontinue` で進めます。以降、Step 2 (Sub-agent によるログ取得)、Step 3 (結論提示)、Step 4 (Sub-agent によるレビュー) を Checkpoint ごとに承認して進めます。

## 前提条件

- Kiro CLI (`kiro-cli`) がインストールされ、ブラウザ認証が完了している必要があります。
- Python 3.10 以上、および リポジトリ ルートの `requirements.txt` (`boto3` のみ) がインストールされている必要があります。
- `tools/logs_insights.py` の実行に必要な IAM 権限は、リポジトリ ルートの README.md を参照してください。
