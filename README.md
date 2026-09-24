# Multi-Agent Design Samples

Amazon Bedrock AgentCore Runtime のログ調査を題材に、Context Rot (入力トークン長が伸びるほど LLM の性能が不安定になる現象) を避けるためのマルチエージェント設計を、Kiro のワークフロー型 Skill として実装したサンプル リポジトリです。

解説記事: [Context Rot を避けるマルチエージェント設計 — AWS のログ調査をマルチエージェントで実装する](https://zenn.dev/aws_japan/articles/multi-agent-design)

> [!NOTE]
> 本リポジトリは検証環境での確認に基づくサンプルです。AWS の公式サンプルではありません。

## 実行例

Kiro で 4 ステップのワークフロー (目的確認 → ログ取得と要約 (Sub-agent) → 結論提示 → 結論のレビュー (Sub-agent)) を実行する様子です。1000 行の正常系ログに埋もれた 1 行を真因として特定するまでを収めています。

https://github.com/user-attachments/assets/89875720-4c7f-4031-b526-3eda2be3712a

## どこから始めるか

```
multi-agent-design-samples/
├── README.md            このファイル
├── requirements.txt      tools/ が使う依存 (boto3 のみ)
├── tools/                 Logs Insights クエリ関数と OTEL スパンのノイズフィルタ
├── reproduce/             事象の再現。AgentCore CLI でログが大量に出る状況を作る
└── kiro/                  Kiro 用のワークフロー型 Skill
```

読み進める順序は次のとおりです。

1. `reproduce/README.md` の手順で、意図的に失敗するエージェントを Amazon Bedrock AgentCore Runtime にデプロイし、調査対象のログを蓄積させます。
2. `kiro/README.md` を読み、`kiro/` に移動してワークフロー型 Skill を実行します。

`tools/` (Logs Insights クエリ関数と OTEL スパンのノイズフィルタ) は `kiro/` から `../tools/...` という相対パスで参照します。Skill のディレクトリごとに同じロジックを複製すると、修正時にすべてを同期させる必要が生じるため、リポジトリ ルートの 1 か所に置いています。

## 前提条件

- Python 3.10 以上である必要があります。
- `tools/logs_insights.py` を使うには、最低限次の IAM 権限を持つ AWS 認証情報が必要です。
  - `logs:StartQuery`
  - `logs:GetQueryResults`
  - `logs:StopQuery`
  - `logs:DescribeLogGroups`
- `reproduce/` のデプロイには AgentCore CLI (`@aws/agentcore`) を使うため、Node.js 20 以上と npm が必要です。CLI は AWS CDK 経由でリソースを作成するため、ログクエリより広い IAM 権限と、初回の CDK bootstrap が必要になります。必要な権限は [Use the AgentCore CLI](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html) を参照してください。
- Docker は、AgentCore CLI の既定である `CodeZip` ビルドでは不要です。`Container` ビルドを選ぶ場合のみ必要になります。
- Kiro CLI (`kiro-cli`) がインストールされている必要があります。前提条件は `kiro/README.md` に記載しています。

```bash
git clone <このリポジトリのクローン URL>
cd multi-agent-design-samples

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## reproduce/ が AWS リソースを作成すること

`agentcore deploy` は、IAM ロールと AgentCore Runtime を実際に作成します (`Container` ビルドではコンテナ イメージの置き場所も作成します)。検証が終わったら必ず削除してください。

> [!WARNING]
> 次の 2 コマンドは実際の AWS リソースを削除します。`agentcore remove all` は設定を空にするだけで、削除は続く `agentcore deploy` が実行します。削除対象はプロジェクトの `agentcore.json` に定義されたリソースに限られます。

```bash
cd reproduce
agentcore remove all
agentcore deploy
```

詳細は `reproduce/README.md` を参照してください。

## ディレクトリの役割

| ディレクトリ | 役割 |
|---|---|
| `tools/` | Logs Insights クエリ関数 (`logs_insights.py`)、OTEL スパンの DROP / KEEP ノイズフィルタ (`span_filter.py`)。`kiro/` から共有して参照する |
| `reproduce/` | 意図的に失敗するエージェントを AgentCore CLI で AgentCore Runtime にデプロイし、調査対象のログを再現する。エージェントのコードは README に掲載している |
| `kiro/` | Kiro でワークフロー型 Skill を実行する構成 |

## ワークフロー型 Skill の構成

`kiro/` のワークフローは、次の 4 ステップで構成しています。

1. 調査目的の確認 (main agent)
2. ログ取得と要約 (subagent)
3. 結論の提示 (main agent)
4. 結論のレビュー (subagent)

Step 2 はエラー調査とレイテンシ調査を別の subagent に分けています。1 つの subagent に両方を任せると、先に見つけたエラーの内容が後の探索方針を引きずるためです。Step 4 は、Step 3 の結論が保存済みの要約ファイルの内容だけを根拠にしているか、main agent が推測で補った情報を含んでいないかを、別の subagent に検証させます。問題が見つかった場合は Step 3 に戻って結論を修正します。

Skill と Sub-agent の実装形式・配置場所は、Kiro の公開ドキュメントで確認できる範囲に従っています。確認できなかった項目は `kiro/README.md` に明記しています。

## 参考

- [Context Rot: How Increasing Input Tokens Impacts LLM Performance](https://research.trychroma.com/context-rot)
- [agentcore-investigation SKILL.md](https://github.com/awslabs/mcp/blob/main/src/cloudwatch-mcp-server/skills/agentcore-investigation/SKILL.md)
- [otel-span-schema.md](https://github.com/awslabs/mcp/blob/main/src/cloudwatch-mcp-server/skills/agentcore-investigation/references/otel-span-schema.md)
- [AgentCore Observability - Configure observability for your agents](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html)
- [GetQueryResults - Amazon CloudWatch Logs API Reference](https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_GetQueryResults.html)
- [awslabs/agentcore-samples - cloudwatch_client.py](https://github.com/awslabs/agentcore-samples/blob/main/06-workshops/07-AgentCore-evaluations/03-advanced/01-end-to-end-on-demand-with-boto3/utils/cloudwatch_client.py)
