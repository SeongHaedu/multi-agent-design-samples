[English](README.md) | Japanese

# Multi-Agent Design Samples: AgentCore Runtime ログ調査

> [!NOTE]
> このリポジトリは AWS が提供するものではない。個人の検証環境での確認に基づく、ブログ記事に付随するサンプルである。見解は個人のものである。

main agent の context をログの生レコードで溢れさせずに、Amazon Bedrock AgentCore Runtime のログを調査するワークフロー型 Agent Skill のサンプルコードである。この Skill は、ログの取得・ノイズ除去・要約を subagent に委譲する。subagent が返すのは JSON の要約とファイル パスだけであり、ログの生レコードは main agent の context に一切入らない。

記事 (日本語): (記事公開後に追記)

## ディレクトリ構成

```
.
├── skills/
│   └── agentcore-log-investigation/
│       └── SKILL.md             ワークフロー型 Agent Skill。Pipeline Display と
│                                 4 ステップ (目的確認 / subagent によるログ取得と要約 /
│                                 結論提示 / subagent による結論のレビュー) で構成し、
│                                 各ステップに Constraints、Acceptance Criteria、
│                                 固定書式の Checkpoint を持つ。
├── tools/
│   ├── logs_insights.py         CloudWatch Logs Insights クエリ関数。StartQuery /
│                                 GetQueryResults のポーリングをラップし、結果を
│                                 record_count / representative_records /
│                                 field_value_counts に要約する。依存は boto3 のみ。
│   └── span_filter.py           OTEL スパンの DROP / KEEP ノイズフィルタ。
│                                 cloudwatch-mcp-server の agentcore-investigation
│                                 Skill が公開しているパターンをそのまま実装している。
│                                 依存は標準ライブラリのみ。
├── agent-failing/
│   ├── main.py                  意図的に失敗させ、調査対象のログを作るサンプル
│                                 エージェント。FAILURE_MODE でツール呼び出しの例外、
│                                 タイムアウト、不正な入力の 3 種類を切り替える。
│   ├── Dockerfile
│   └── requirements.txt
├── scripts/
│   ├── deploy.py                agent-failing を AgentCore Runtime へデプロイする。
│   └── cleanup.py               deploy.py が作成したリソースを削除する。
├── requirements.txt              boto3 のみ
└── .gitignore
```

## 前提条件

- Python 3.10 以上であること。
- `tools/logs_insights.py` を使うには、最低限次の IAM 権限を持つ AWS 認証情報が必要である。
  - `logs:StartQuery`
  - `logs:GetQueryResults`
  - `logs:StopQuery`
  - `logs:DescribeLogGroups`
- `scripts/deploy.py` と `scripts/cleanup.py` は、ログ クエリより広い操作を行う。AgentCore Runtime、ECR リポジトリ、IAM ロールの作成と削除である。実行するには、`bedrock-agentcore-control` (`CreateAgentRuntime`、`DeleteAgentRuntime`、`ListAgentRuntimes`、`GetAgentRuntime`)、`ecr` (`CreateRepository`、`DeleteRepository`、`DescribeRepositories`)、`iam` (`CreateRole`、`DeleteRole`、`PutRolePolicy`、`DeleteRolePolicy`、`GetRole`、`ListRoleTags`) の追加権限が必要である。このリポジトリ自体はこれらのスクリプトを実行していないため、まず上記 4 つのログ権限から始め、実際にデプロイする場合にのみ残りを追加すること。
- `agent-failing` のコンテナ イメージを自分でビルドする場合は、`docker buildx` を含む Docker が必要である。AgentCore Runtime の microVM は ARM64 Linux で動作する。

## セットアップ

```bash
git clone https://github.com/SeongHaedu/multi-agent-design-samples.git
cd multi-agent-design-samples

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

以下のコマンドはすべてリポジトリのルートから実行する。

## Skill の使い方

`skills/agentcore-log-investigation/SKILL.md` は Claude Code の Agent Skill である。Claude Code の Skill 検出が有効なプロジェクト (例えば `.claude/skills/` ディレクトリを持つプロジェクト) に `skills/agentcore-log-investigation/` ディレクトリをコピーし、「AgentCore Runtime 上のエージェントが失敗している、原因を調べてほしい」のように調査内容を伝えることで呼び出せる。この Skill は、目的確認、subagent へのログ取得・要約の委譲、結論提示、別の reviewer subagent による結論レビューという 4 ステップで進む。レビューでは、結論が保存済みの要約だけを根拠にしており、main agent が推測で補った情報を含んでいないかを検証する。各ステップの後には Checkpoint で一度停止し、ユーザーの承認を待つ。レビューで問題が見つかった場合は、結論提示のステップに戻って修正できる。

内部では、subagent のステップで `tools/logs_insights.py` の `run_logs_insights_query()` を呼び、CloudWatch Logs Insights クエリを実行して結果を要約する。OTEL スパンを対象にする場合は、要約の前に `tools/span_filter.py` の `filter_spans()` でノイズを除く。いずれのモジュールも直接呼び出せる。

```bash
python tools/logs_insights.py \
  --log-group /aws/bedrock-agentcore/runtimes/<agent-id>-DEFAULT \
  --query 'fields @timestamp, @message | filter @message like /ERROR/' \
  --minutes 60 \
  --limit 50
```

これは JSON の要約 (`record_count`、`representative_records`、`field_value_counts`) を標準出力に印字するだけであり、一致したログ レコードの全件を出力することはない。

## 失敗するエージェントを動かす

`agent-failing/main.py` は `bedrock-agentcore` SDK で作った最小のエージェントである。ほぼ同一の INFO ログを `NORMAL_LOG_LINES` (既定 200) 件出力したうえで、`FAILURE_MODE` の値に応じて、模擬したツール呼び出しの中で例外を投げる (`tool_exception`、既定)、呼び出し元のタイムアウトを超えてスリープする (`timeout`)、`customer_id` を含まない payload を拒否する (`invalid_input`) のいずれかを行う。`FAILURE_MODE=none` を指定すると、正常系ログだけを出力する。

```bash
docker buildx build --platform linux/arm64 \
  -t <account-id>.dkr.ecr.<region>.amazonaws.com/multi-agent-design-agent-failing:latest \
  --push agent-failing/

AGENTCORE_CONTAINER_URI=<account-id>.dkr.ecr.<region>.amazonaws.com/multi-agent-design-agent-failing:latest \
  python scripts/deploy.py
```

`scripts/deploy.py` は、作成するすべてのリソース (IAM ロール、ECR リポジトリ、AgentCore Runtime) の名前に `RESOURCE_PREFIX` (既定 `multi-agent-design-`) を付け、AWS 呼び出しの前に対象リージョンとアカウント ID (下 4 桁以外をマスク) を表示する。ECR リポジトリと IAM ロールが存在しない場合は作成し、作成したランタイムの ID と ARN を `results/deploy.json` に書き込む。

## クリーンアップ

> [!WARNING]
> `scripts/cleanup.py` は実際の AWS リソースを削除する。対象は `scripts/deploy.py` が作成した AgentCore Runtime、ECR リポジトリ、IAM ロールである。次の 2 つの安全対策は両方が必須であり、片方だけでは不十分である。
>
> - プレフィックス限定: 名前が `RESOURCE_PREFIX` で始まるリソースだけを対象にする。`"".startswith("")` が常に真になるため、空プレフィックスは AWS 呼び出しの前に拒否する。拒否しない場合、アカウントとリージョン内のすべてのリソースが対象に入ってしまう。
> - 明示的な確認フラグ: `--yes` を渡さない限り、削除対象の一覧を表示するだけで終了する。`--yes` を明示的に渡さない限り、何も削除しない。

```bash
python scripts/cleanup.py        # 削除対象の一覧表示のみ
python scripts/cleanup.py --yes  # 実際に削除する
```

## 参考

- [Context Rot: How Increasing Input Tokens Impacts LLM Performance](https://research.trychroma.com/context-rot)
- [agentcore-investigation SKILL.md](https://github.com/awslabs/mcp/blob/main/src/cloudwatch-mcp-server/skills/agentcore-investigation/SKILL.md)
- [otel-span-schema.md](https://github.com/awslabs/mcp/blob/main/src/cloudwatch-mcp-server/skills/agentcore-investigation/references/otel-span-schema.md)
- [Claude Code Subagents](https://code.claude.com/docs/en/sub-agents)
- [Claude Code Agent Skills](https://code.claude.com/docs/en/skills)
- [AgentCore Observability - Configure observability for your agents](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html)
- [GetQueryResults - Amazon CloudWatch Logs API Reference](https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_GetQueryResults.html)
- [awslabs/agentcore-samples - cloudwatch_client.py](https://github.com/awslabs/agentcore-samples/blob/main/06-workshops/07-AgentCore-evaluations/03-advanced/01-end-to-end-on-demand-with-boto3/utils/cloudwatch_client.py)
