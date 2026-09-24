# multi-agent-design-samples

Amazon Bedrock AgentCore Runtime のログ調査を題材に、Context Rot (入力トークン
長が伸びるほど LLM の性能が不安定になる現象) を避けるためのマルチエージェント
設計を、3 つの coding agent (Kiro、Claude Code、Codex) それぞれのワークフロー型
Skill として実装したサンプル リポジトリです。

解説記事: (記事公開後に追記)

> [!NOTE]
> 本リポジトリは検証環境での確認に基づくサンプルです。AWS の公式サンプルでは
> ありません。

## どこから始めるか

```
multi-agent-design-samples/
├── README.md            このファイル
├── requirements.txt      tools/ と reproduce/scripts/ が使う共通の依存 (boto3 のみ)
├── tools/                 Logs Insights クエリ関数と OTEL スパンのノイズフィルタ (3 つの coding agent 共通)
├── reproduce/             事象の再現。ログが大量に出る状況を作る
├── kiro/                  Kiro 用のワークフロー型 Skill
├── claude-code/           Claude Code (Amazon Bedrock 版) 用のワークフロー型 Skill
└── codex/                 Codex CLI (OpenAI) 用のワークフロー型 Skill
```

読み進める順序は次のとおりです。

1. `reproduce/README.md` の手順で、意図的に失敗するエージェントを Amazon
   Bedrock AgentCore Runtime にデプロイし、調査対象のログを蓄積させます。
2. 使っている coding agent に応じて `kiro/README.md`、`claude-code/README.md`、
   `codex/README.md` のいずれかを読み、そのディレクトリに移動してワークフロー型
   Skill を実行します。

`tools/` (Logs Insights クエリ関数と OTEL スパンのノイズフィルタ) は 3 つの
coding agent ディレクトリすべてから `../tools/...` という相対パスで共有して
参照します。同じロジックを 3 か所に複製すると、修正時に 3 か所を同期させる必要が
生じるため、リポジトリ ルートの 1 か所に置いています。

## 前提条件

- Python 3.10 以上である必要があります。
- `tools/logs_insights.py` を使うには、最低限次の IAM 権限を持つ AWS 認証情報が
  必要です。
  - `logs:StartQuery`
  - `logs:GetQueryResults`
  - `logs:StopQuery`
  - `logs:DescribeLogGroups`
- `reproduce/scripts/deploy.py` と `reproduce/scripts/cleanup.py` は、ログ
  クエリより広い操作を行います。AgentCore Runtime、ECR リポジトリ、IAM ロールの
  作成と削除です。実行するには、`bedrock-agentcore-control`
  (`CreateAgentRuntime`、`DeleteAgentRuntime`、`ListAgentRuntimes`、
  `GetAgentRuntime`)、`ecr` (`CreateRepository`、`DeleteRepository`、
  `DescribeRepositories`)、`iam` (`CreateRole`、`DeleteRole`、
  `PutRolePolicy`、`DeleteRolePolicy`、`GetRole`、`ListRoleTags`) の追加権限が
  必要です。
- `reproduce/agent-failing` のコンテナ イメージを自分でビルドする場合は、
  `docker buildx` を含む Docker が必要です。AgentCore Runtime の microVM は
  ARM64 Linux で動作します。
- 使用する coding agent (Kiro、Claude Code、Codex) がインストールされている
  必要があります。各ディレクトリの README.md に前提条件を記載しています。

```bash
git clone <このリポジトリのクローン URL>
cd multi-agent-design-samples

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## reproduce/ が AWS リソースを作成すること

`reproduce/scripts/deploy.py` は、AgentCore Runtime、ECR リポジトリ、IAM
ロールを実際に作成します。検証が終わったら、`reproduce/scripts/cleanup.py` で
必ず削除してください。

> [!WARNING]
> `reproduce/scripts/cleanup.py` は実際の AWS リソースを削除します。次の 2 つの
> 安全対策は両方が必須であり、片方だけでは不十分です。
>
> - プレフィックス限定: 名前が `RESOURCE_PREFIX` (既定 `multi-agent-design-`)
>   で始まるリソースだけを対象にします。空プレフィックスは AWS 呼び出しの前に
>   拒否します。
> - 明示的な確認フラグ: `--yes` を渡さない限り、削除対象の一覧を表示するだけで
>   終了します。

```bash
cd reproduce
python scripts/cleanup.py        # 削除対象の一覧表示のみ
python scripts/cleanup.py --yes  # 実際に削除する
```

詳細は `reproduce/README.md` を参照してください。

## ディレクトリの役割

| ディレクトリ | 役割 |
|---|---|
| `tools/` | Logs Insights クエリ関数 (`logs_insights.py`)、OTEL スパンの DROP / KEEP ノイズフィルタ (`span_filter.py`)。3 つの coding agent ディレクトリすべてから共有する |
| `reproduce/` | 意図的に失敗するエージェントを AgentCore Runtime にデプロイし、調査対象のログを再現する。デプロイとクリーンアップのスクリプトを含む |
| `kiro/` | Kiro でワークフロー型 Skill を実行する構成 |
| `claude-code/` | Claude Code (Amazon Bedrock 版) でワークフロー型 Skill を実行する構成 |
| `codex/` | Codex CLI (OpenAI) でワークフロー型 Skill を実行する構成 |

## ワークフロー型 Skill の構成

3 つの coding agent ディレクトリはいずれも、同じ 4 ステップのワークフローを
実装しています。

1. 調査目的の確認 (main agent)
2. ログ取得と要約 (subagent)
3. 結論の提示 (main agent)
4. 結論のレビュー (subagent)

Step 2 はエラー調査とレイテンシ調査を別の subagent に分けています。1 つの
subagent に両方を任せると、先に見つけたエラーの内容が後の探索方針を引きずる
ためです。Step 4 は、Step 3 の結論が保存済みの要約ファイルの内容だけを
根拠にしているか、main agent が推測で補った情報を含んでいないかを、別の
subagent に検証させます。問題が見つかった場合は Step 3 に戻って結論を修正します。

各 coding agent での実装形式・配置場所は、その coding agent の公開ドキュメント
で確認できる範囲に従っています。確認できなかった項目は、各ディレクトリの
README.md に明記しています。

## 参考

- [Context Rot: How Increasing Input Tokens Impacts LLM Performance](https://research.trychroma.com/context-rot)
- [agentcore-investigation SKILL.md](https://github.com/awslabs/mcp/blob/main/src/cloudwatch-mcp-server/skills/agentcore-investigation/SKILL.md)
- [otel-span-schema.md](https://github.com/awslabs/mcp/blob/main/src/cloudwatch-mcp-server/skills/agentcore-investigation/references/otel-span-schema.md)
- [AgentCore Observability - Configure observability for your agents](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html)
- [GetQueryResults - Amazon CloudWatch Logs API Reference](https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_GetQueryResults.html)
- [awslabs/agentcore-samples - cloudwatch_client.py](https://github.com/awslabs/agentcore-samples/blob/main/06-workshops/07-AgentCore-evaluations/03-advanced/01-end-to-end-on-demand-with-boto3/utils/cloudwatch_client.py)
