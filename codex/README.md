# codex/ — Codex CLI (OpenAI) 用

Codex CLI の Skills と Subagents を使って `agentcore-log-investigation`
ワークフローを実行するための構成です。

## できること

- `reproduce/` でデプロイした AgentCore Runtime のログを、4 ステップの
  ワークフロー (目的確認 → ログ取得と要約 (subagent) → 結論提示 → 結論の
  レビュー (subagent)) で調査します。
- ログの取得・要約・レビューはすべて専用の subagent (`error-investigator`、
  `latency-investigator`、`reviewer`) に委譲し、main agent の context には
  ログの生データを一切読み込みません。

## 構成

```
codex/
├── README.md
├── AGENTS.md                        Codex が実行ごとに読み込む短い案内。
│                                     Skill の存在と subagent 名を伝えるだけ
├── .agents/
│   └── skills/
│       └── agentcore-log-investigation/
│           └── SKILL.md             4 ステップのワークフロー本体
└── .codex/
    └── agents/
        ├── error-investigator.toml  エラー調査用 subagent
        ├── latency-investigator.toml レイテンシ調査用 subagent
        └── reviewer.toml             結論レビュー用 subagent
```

Codex CLI には Kiro (`.kiro/skills/`) や Claude Code (`.claude/skills/`) と
同種の Skills 機能があり、SKILL.md 形式 (frontmatter に `name` と
`description` が必須) に対応しています。ただし配置パスの命名は異なり、
`.agents/skills` という共通ディレクトリ名を使います。Codex は現在の作業ディレクトリ
から repo root まで `.agents/skills` を再帰的に探索します。

- Skills: https://learn.chatgpt.com/codex/skills-and-plugins 、
  https://learn.chatgpt.com/codex/build-skills
- Subagents (`.codex/agents/<name>.toml`。必須フィールドは `name` /
  `description` / `developer_instructions`):
  https://learn.chatgpt.com/docs/agent-configuration/subagents
- AGENTS.md の仕様 (実行ごとに再構築、キャッシュなし。ディレクトリを下方向に
  走査してマージする):
  https://learn.chatgpt.com/docs/agent-configuration/agents-md

Skill の呼び出しは `$agentcore-log-investigation` のような `$` メンションで
明示するか、`description` に基づく暗黙のマッチングで行われます。暗黙のマッチング
は `agents/openai.yaml` の `allow_implicit_invocation: false` で無効化できます
(本リポジトリでは設定していないため既定で有効です)。

> [!NOTE]
> `reviewer.toml` の「ファイルを書き込まない」制約は `developer_instructions`
> 内の指示 (MUST_NOT) だけで運用しています。Claude Code 版の `reviewer.md`
> (`tools: Read` のみを frontmatter で指定し、構造的に書き込みを禁止) とは
> 異なり、Codex の Subagent TOML には利用ツールを制限するフィールドが公開
> ドキュメント上で確認できませんでした。

`tools/logs_insights.py` と `tools/span_filter.py` はこのディレクトリの外
(リポジトリ ルートの `tools/`) にあります。3 つの subagent はいずれも
`../tools/...` という相対パスで参照する前提になっています。そのため、Codex は
必ずこの `codex/` ディレクトリを起点 (cwd) にして起動してください。

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

3. Codex CLI をインストールします (未実施の場合)。GitHub README に記載されて
   いる方法は次のいずれかです。

   ```bash
   npm install -g @openai/codex
   # または
   brew install --cask codex
   # または
   curl -fsSL https://chatgpt.com/codex/install.sh | sh
   ```

4. このディレクトリに移動して Codex を起動します。

   ```bash
   cd codex
   codex
   ```

5. 調査内容を伝えます。`description` による暗黙のマッチングで Skill が呼ばれる
   はずですが、明示的に呼び出す場合は `$agentcore-log-investigation` を先頭に
   付けます。

   ```
   > $agentcore-log-investigation AgentCore Runtime 上のエージェントが失敗している。原因を調べてほしい。
   ```

6. Step 1 の Checkpoint でログ グループ名・対象期間・調査目的を確認し、
   `(c)ontinue` で進めます。以降、Step 2 (subagent によるログ取得)、Step 3
   (結論提示)、Step 4 (subagent によるレビュー) を Checkpoint ごとに承認して
   進めます。

## Amazon Bedrock の設定

Codex CLI は Amazon Bedrock でホストされている OpenAI のモデルに接続する
設定を公式にサポートしています。

出典: https://learn.chatgpt.com/codex/amazon-bedrock、
https://learn.chatgpt.com/docs/config-file/config-advanced、
https://learn.chatgpt.com/docs/config-file/config-reference (取得日 2026-09-24)

- 接続方式は 2 種類あります。クロスリージョン推論 (CRIS) 用の Bedrock Runtime
  (`model_provider = "amazon-bedrock-runtime"`、エンドポイントは
  `https://bedrock-runtime.{region}.amazonaws.com/openai/v1`) と、リージョン内
  推論用の Bedrock Mantle (`model_provider = "amazon-bedrock"`、エンドポイントは
  `https://bedrock-mantle.{region}.api.aws/openai/v1`) です。
- `~/.codex/config.toml` に `model_provider` と `model` (例:
  `model = "global.openai.gpt-6-astra"`) を設定します。
- 認証は Bedrock API キー (`AWS_BEARER_TOKEN_BEDROCK` と `AWS_REGION`)、または
  AWS SDK の標準認証チェーンのいずれかを使います。ChatGPT へのサインインや
  `OPENAI_API_KEY` は使いません。
- Mantle 経由で確認できたモデル例: `openai.gpt-6-astra`、`openai.gpt-6-sol`、
  `openai.gpt-6-luna`、`openai.gpt-5.6-sol`、`openai.gpt-5.6-terra`、
  `openai.gpt-5.6-luna`、`openai.gpt-5.5`、`openai.gpt-5.4`。
- Fast Mode は Amazon Bedrock 経由では使えません。GovCloud リージョンの Mantle
  エンドポイントには対応していません。

> [!NOTE]
> https://learn.chatgpt.com/codex/amazon-bedrock への到達はリダイレクト経由
> (developers.openai.com/codex/amazon-bedrock) と推定されており、リダイレクト
> の発生自体は未確認です。内容は config-advanced / config-reference の
> 記述と整合していることを確認しています。モデル ID や対応リージョンは変わる
> 可能性があるため、実行前に上記の公式ドキュメントで最新の内容を確認してください。

## 前提条件

- Codex CLI (npm / Homebrew / インストーラのいずれか) がインストールされて
  いる必要があります。
- Amazon Bedrock でモデルを呼び出すための AWS 認証情報 (上記「Amazon Bedrock
  の設定」を参照) が必要です。
- Python 3.10 以上、および リポジトリ ルートの `requirements.txt`
  (`boto3` のみ) がインストールされている必要があります。
- `tools/logs_insights.py` の実行に必要な IAM 権限は、リポジトリ ルートの
  README.md を参照してください。
