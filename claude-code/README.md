# claude-code/ — Claude Code (Amazon Bedrock 版) 用

Claude Code の Agent Skills と Subagents を使って `agentcore-log-investigation`
ワークフローを実行するための構成である。

## できること

- `reproduce/` でデプロイした AgentCore Runtime のログを、4 ステップの
  ワークフロー型 Skill (目的確認 → ログ取得と要約 (subagent) → 結論提示 →
  結論のレビュー (subagent)) で調査する。
- ログの取得・要約・レビューはすべて専用の subagent (`error-investigator`、
  `latency-investigator`、`reviewer`) に委譲し、main agent の context には
  ログの生データを一切読み込まない。

## 構成

```
claude-code/
├── README.md
└── .claude/
    ├── skills/
    │   └── agentcore-log-investigation/
    │       └── SKILL.md           4 ステップのワークフロー本体
    └── agents/
        ├── error-investigator.md  エラー調査用 subagent (tools: Bash, Read, Write)
        ├── latency-investigator.md レイテンシ調査用 subagent (tools: Bash, Read, Write)
        └── reviewer.md            結論レビュー用 subagent (tools: Read のみ)
```

`.claude/skills/<name>/SKILL.md` と `.claude/agents/<name>.md` (frontmatter に
`name` / `description` / `tools` / `model`) は、Claude Code が公開している
Agent Skills と Subagents の標準的な配置・形式である。

- Agent Skills: https://code.claude.com/docs/en/skills
- Subagents: https://code.claude.com/docs/en/sub-agents

`reviewer.md` は `tools: Read` だけを割り当てている。Claude Code の Subagents
機能は frontmatter の `tools` で使用可能なツールを制限できるため、この
subagent には構造的にファイル書き込みができない。

`tools/logs_insights.py` と `tools/span_filter.py` はこのディレクトリの外
(リポジトリ ルートの `tools/`) にある。3 つの subagent はいずれも
`../tools/...` という相対パスで参照する前提になっている。そのため、Claude
Code は必ずこの `claude-code/` ディレクトリを起点 (cwd) にして起動すること。

## 実行手順

1. リポジトリ ルートで依存パッケージをインストールする (未実施の場合)。

   ```bash
   cd /path/to/multi-agent-design-samples
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. `reproduce/README.md` の手順で AgentCore Runtime をデプロイし、ログを
   蓄積させる。

3. このディレクトリに移動して Claude Code を起動する。

   ```bash
   cd claude-code
   claude
   ```

4. Skill を呼び出す。Claude Code は `.claude/skills/` を自動的に走査するため、
   調査内容を伝えるだけで Skill が起動する。

   ```
   > AgentCore Runtime 上のエージェントが失敗している。原因を調べてほしい。
   ```

5. Step 1 の Checkpoint でログ グループ名・対象期間・調査目的を確認し、
   `(c)ontinue` で進める。以降、Step 2 (subagent によるログ取得)、Step 3
   (結論提示)、Step 4 (subagent によるレビュー) を Checkpoint ごとに承認して
   進める。

## Amazon Bedrock の設定

Claude Code は Amazon Bedrock 上のモデルを使う設定を公式にサポートしている。

出典: https://code.claude.com/docs/en/amazon-bedrock (取得日 2026-09-24)

- 環境変数 `CLAUDE_CODE_USE_BEDROCK=1` と `AWS_REGION` を設定する。モデルを
  固定する場合は `ANTHROPIC_DEFAULT_OPUS_MODEL` / `ANTHROPIC_DEFAULT_SONNET_MODEL`
  / `ANTHROPIC_DEFAULT_HAIKU_MODEL` にモデル ID (例: `us.anthropic.claude-opus-4-8`
  のようなクロスリージョン推論プロファイル ID) を指定する。プロファイルの
  接頭辞 (`us.` / `eu.` / `apac.` / `us-gov.`) はリージョンに応じて解決される。
- 必要な IAM 権限は `bedrock:InvokeModel`、`bedrock:InvokeModelWithResponseStream`、
  `bedrock:ListInferenceProfiles`、`bedrock:GetInferenceProfile` である。
- 認証方法は次の 5 種類がドキュメントに記載されている。AWS CLI プロファイル、
  アクセスキーの環境変数、AWS SSO プロファイル、`aws login`、Bedrock API キー
  (`AWS_BEARER_TOKEN_BEDROCK`)。
- `/setup-bedrock` を実行すると対話形式で設定でき、結果は `~/.claude/settings.json`
  に保存される。

> [!NOTE]
> 上記は 2026-09-24 に公式ドキュメントで確認した内容である。モデル ID や
> IAM 権限の名称は変わる可能性があるため、実行前に上記の公式ドキュメントで
> 最新の内容を確認すること。

## 前提条件

- Claude Code (Amazon Bedrock 対応バージョン) がインストールされていること。
- Amazon Bedrock でモデルを呼び出すための AWS 認証情報と IAM 権限
  (上記「Amazon Bedrock の設定」を参照) が設定されていること。
- Python 3.10 以上、および リポジトリ ルートの `requirements.txt`
  (`boto3` のみ) がインストールされていること。
- `tools/logs_insights.py` の実行に必要な IAM 権限は、リポジトリ ルートの
  README.md を参照する。
