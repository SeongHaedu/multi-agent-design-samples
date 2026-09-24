# kiro/ — Kiro 用

Kiro の Agent Skills と Sub-agents を使って `agentcore-log-investigation`
ワークフローを実行するための構成です。

## できること

- `reproduce/` でデプロイした AgentCore Runtime のログを、4 ステップの
  ワークフロー型 Skill (目的確認 → ログ取得と要約 (Sub-agent) → 結論提示 →
  結論のレビュー (Sub-agent)) で調査します。
- ログの取得・要約・レビューはすべて専用の Sub-agent (`error-investigator`、
  `latency-investigator`、`reviewer`) に委譲し、main agent の context には
  ログの生データを一切読み込みません。

## 構成

```
kiro/
├── README.md
└── .kiro/
    ├── skills/
    │   └── agentcore-log-investigation/
    │       └── SKILL.md            4 ステップのワークフロー本体 (agentskills.io 準拠)
    └── agents/
        ├── log-investigator.json   main agent。resources で上記 Skill を明示的に参照する
        ├── error-investigator.json エラー調査用 Sub-agent
        ├── latency-investigator.json レイテンシ調査用 Sub-agent
        └── reviewer.json           結論レビュー用 Sub-agent
```

Kiro の Agent 設定ファイルは JSON と Markdown のどちらの形式でも書けます。両方
同じフィールド (`name` / `description` / `tools` / `excludedTools` / `prompt`
/ `model` / `resources`) を持ちます。本リポジトリでは、`prompt` フィールドが
指示本文をどこに置くかという点で Markdown 形式に曖昧さが残ると判断し、
フィールドの意味が一意になる JSON 形式を使っています。

- Custom Agents (Sub-agents を含む): https://kiro.dev/docs/custom-agents/ 、
  https://kiro.dev/docs/custom-agents/subagents/
- Agent Skills (agentskills.io 準拠。frontmatter に `name` と `description`
  が両方必須): https://kiro.dev/docs/skills/

`tools` / `excludedTools` フィールドは存在が確認できましたが、具体的なツール
識別子の一覧 (ファイル書き込みを表す文字列など) は公開ドキュメントで確認
できませんでした。そのため `reviewer.json` の「ファイルを書き込まない」制約は
`prompt` 内の指示文だけで運用しており、Claude Code 版の `reviewer.md`
(`tools: Read` のみを frontmatter で指定し、構造的に書き込みを禁止) のような
構造的な強制ではありません。

カスタムエージェントは既定では Skill を読み込みません。`log-investigator.json`
だけが `resources: ["skill://agentcore-log-investigation"]` を持ち、この
エージェントを起動したときに Skill の本文が読み込まれます。3 つの Sub-agent は
それぞれの `prompt` に完全な指示を持っているため、Skill を参照する必要はありません。

`tools/logs_insights.py` と `tools/span_filter.py` はこのディレクトリの外
(リポジトリ ルートの `tools/`) にあります。3 つの Sub-agent の `prompt` はいずれも
`../tools/...` という相対パスで参照する前提になっています。そのため、Kiro は
必ずこの `kiro/` ディレクトリを起点 (cwd) にして起動してください。

## 実行手順

1. リポジトリ ルートで依存パッケージをインストールします (未実施の場合)。

   ```bash
   cd /path/to/multi-agent-design-samples
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. `reproduce/README.md` の手順で AgentCore Runtime をデプロイし、ログを
   蓄積させます。

3. Kiro CLI (`kiro-cli`) をインストールします (未実施の場合)。

   ```bash
   # macOS / Linux
   curl -fsSL https://cli.kiro.dev/install | bash

   # Windows (PowerShell)
   irm 'https://cli.kiro.dev/install.ps1' | iex
   ```

   Homebrew での配布は公式に非対応と明記されています。インストール後、ブラウザ
   認証が必要です。認証し直す場合は `kiro-cli login`、問題の診断には
   `kiro-cli doctor` を使います。

   出典: https://kiro.dev/docs/getting-started/installation/ 、
   https://kiro.dev/docs/cli/setup/

4. このディレクトリに移動し、`log-investigator` エージェントを指定して
   Kiro CLI を起動します。

   ```bash
   cd kiro
   kiro-cli --agent log-investigator
   ```

   出典 (特定のエージェントを指定して起動する構文):
   https://kiro.dev/docs/cli/chat/

5. 調査内容を伝えます。`log-investigator` は起動時に
   `agentcore-log-investigation` Skill を読み込んでいるため、調査内容を伝える
   だけでワークフローが始まります。

   ```
   > AgentCore Runtime 上のエージェントが失敗している。原因を調べてほしい。
   ```

6. Step 1 の Checkpoint でログ グループ名・対象期間・調査目的を確認し、
   `(c)ontinue` で進めます。以降、Step 2 (Sub-agent によるログ取得)、Step 3
   (結論提示)、Step 4 (Sub-agent によるレビュー) を Checkpoint ごとに承認して
   進めます。

## Amazon Bedrock との関係

Kiro は Amazon Bedrock によって動作しており、クロスリージョン推論でリクエスト
を分散させます。原文: "Kiro is powered by Amazon Bedrock, which uses cross-region
inference to distribute requests across the Regions." モデルの切り替えは
チャット インターフェースのドロップダウンから行います。

出典: https://kiro.dev/docs/models/available-models/ 、
https://kiro.dev/docs/models/ (取得日 2026-09-24)

> [!NOTE]
> 一般ユーザーが自分の AWS アカウントを Kiro に接続する手順や、リージョン・
> 認証情報を自分で設定する手順は、上記のページには記載が見当たりませんでした
> (未確認)。Kiro は Claude Code や Codex CLI と異なり、モデル呼び出しに
> ユーザー自身の AWS 認証情報を渡す設定 (BYO-AWS-credentials に相当するもの)
> が公開ドキュメント上で確認できていません。この点を除けば、Kiro のモデル呼び出し
> は Amazon Bedrock 上で行われています。

## 前提条件

- Kiro CLI (`kiro-cli`) がインストールされ、ブラウザ認証が完了している必要が
  あります。
- Python 3.10 以上、および リポジトリ ルートの `requirements.txt`
  (`boto3` のみ) がインストールされている必要があります。
- `tools/logs_insights.py` の実行に必要な IAM 権限は、リポジトリ ルートの
  README.md を参照してください。
