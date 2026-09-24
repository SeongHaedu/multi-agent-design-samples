# reproduce/ — 事象の再現

Amazon Bedrock AgentCore Runtime 上に、意図的に失敗するエージェントをデプロイし、「似たログが大量に並ぶ中から真因を 1 行だけ見つける」というトラブルシュートを体験するためのディレクトリです。`kiro/` の Skill は、ここでデプロイしたエージェントのログを調査対象にします。

デプロイには AgentCore CLI (`@aws/agentcore`) を使います。CLI が AWS CDK 経由で IAM ロール、AgentCore Runtime、CloudWatch のログとオブザーバビリティの設定まで作成します。コンテナ イメージのビルドと push も CLI が行うため、自分で `docker build` を実行する必要はありません。

出典: [Get started with the AgentCore CLI](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-cli.html)

## このディレクトリの中身

このディレクトリには README.md しかありません。エージェントのプロジェクトは `agentcore create` が雛形を生成し、エージェントのコードはこの README から貼り付けます。生成物 (設定ファイルと CDK プロジェクト) はリポジトリに含めていません。

手順 1 と 2 を終えると、手元は次の構成になります。

```
reproduce/
├── README.md
└── reproduce/                  agentcore create が生成するプロジェクト ルート
    ├── agentcore/
    │   ├── agentcore.json      プロジェクト設定 (ランタイムの定義)
    │   ├── aws-targets.json    デプロイ先のアカウントとリージョン
    │   └── cdk/                 CDK プロジェクト
    └── app/agent_failing/
        ├── main.py             手順 2 でこの README から貼り付けます
        ├── pyproject.toml      手順 2 で依存を書き換えます
        └── Dockerfile          --build Container を選んだ場合のみ生成されます
```

`reproduce/` の下にもう 1 つ `reproduce/` ができるのは、`agentcore create` が `--project-name` と同じ名前のディレクトリを出力先の下に作るためです。既存のディレクトリと同名は指定できず (`A folder named 'reproduce' already exists`)、project-name は英数字のみでハイフンも使えないため、入れ子を避けたい場合は `--project-name agentlogrepro` のような別名を指定します。以降の手順は `--project-name reproduce` を前提に書いています。

## サンプル エージェントがやっていること

`FAILURE_MODE` 環境変数で失敗の種類を切り替えます。

| 値 | 動作 |
|---|---|
| `tool_exception` (既定) | 模擬したツール呼び出しが例外を投げる |
| `timeout` | `TIMEOUT_SLEEP_SECONDS` 秒スリープし、呼び出し元のタイムアウトを誘発する |
| `invalid_input` | payload に `customer_id` が無い場合にバリデーション エラーを返す |
| `none` | 失敗させない (正常系ログだけを出す動作確認用) |

正常系の INFO ログを `NORMAL_LOG_LINES` 件 (既定 200、環境変数で変更可) 出力します。文面はステップ番号と顧客 ID だけが違うほぼ同一の行であり、記事が指摘する「似たログが大量に並ぶ中から探す」状況を再現します。

`tool_exception` モードでは、さらに次の 2 点を再現します。

- 真因は 1 箇所のログ行にしか現れません。これから失敗する顧客 ID が正常系ログのループの中で最後に登場する行だけ、`account_tier` の値が `standard` から `suspended` に変わります。この行は `error` や `exception` のような検索しやすい語を含みません。
- 失敗メッセージの語彙と、真因の行の語彙が一致しません。ツール呼び出し失敗時のログ (`upstream service rejected the request`) は `account_tier` や `suspended` という語を含まないため、失敗メッセージの語で検索しても真因の行にはたどり着きません。

この 2 点は、記事の「ログ調査が Context Rot を起こしやすい理由」で述べている「紛らわしい情報 (distractor)」と「問いと答えの語彙が一致しない」を、実際のログとして再現したものです。

## 前提条件

- Node.js 20 以上と npm が必要です。AgentCore CLI は npm パッケージとして配布されています。
- AgentCore CLI が必要です。`npm install -g @aws/agentcore` でインストールし、`agentcore --version` で確認します。
- Python 3.10 以上が必要です。
- AWS 認証情報が必要です。初回の `agentcore deploy` は AWS CDK の bootstrap を必要とし、対話実行では確認を求められます。
- Docker は、既定の `CodeZip` ビルドでは不要です。`Container` ビルドを選ぶ場合のみ必要になります。
- CloudWatch Transaction Search の有効化は、スパンを出力してレイテンシ調査を行う場合に必要です。詳細は「オブザーバビリティ」の節に記載します。

> [!NOTE]
> 以前の `agentcore` コマンドが PATH 上に残っている場合、`agentcore --version` がエラーになります。`pip uninstall bedrock-agentcore-starter-toolkit` を実行してターミナルを開き直してください。

出典: [Get started with the AgentCore CLI](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-cli.html)

## 手順

### 1. プロジェクトを生成する

`reproduce/` に移動し、CLI でプロジェクトを生成します。ランタイム名は `^[a-zA-Z][a-zA-Z0-9_]{0,47}$` に制限されており、ハイフンを使えないため `agent_failing` とします。

```bash
cd reproduce

agentcore create \
  --project-name reproduce \
  --name agent_failing \
  --language Python \
  --framework Strands \
  --model-provider Bedrock \
  --memory none \
  --build CodeZip
```

`--framework Strands` を指定しているのは、コードベースのエージェントの雛形を得るためです。Strands 自体はこのサンプルでは使わないため、手順 2 で依存から外します。

生成先は `reproduce/reproduce/` です。手順 2 以降のパスは、このプロジェクト ルートを基準にしています。

```bash
cd reproduce   # リポジトリ ルートから見ると reproduce/reproduce/ に移動します
```

### 2. エージェントのコードと依存を差し替える

生成された `app/agent_failing/main.py` の内容を、次のコードで置き換えます。

<details>
<summary>app/agent_failing/main.py (クリックして展開)</summary>

```python
# app/agent_failing/main.py
#
# Amazon Bedrock AgentCore Runtime 上で動き、意図的に失敗するサンプル エージェント。
# 目的は、coding agent ディレクトリ (kiro/ など) の
# agentcore-log-investigation Skill が調査する対象のログを CloudWatch Logs に
# 発生させることである。
#
# FAILURE_MODE で失敗の種類を切り替える。
#   tool_exception : ツール呼び出しが例外を投げる (既定)
#   timeout        : ハンドラが長時間応答を返さず、呼び出し元のタイムアウトを誘発する
#   invalid_input   : payload に必須フィールドが無い場合にバリデーション エラーを返す
#   none           : 失敗させない (正常系ログだけを出す動作確認用)
#
# 正常系のログは NORMAL_LOG_LINES 件出力する。文面がほぼ同一のログが大量に並ぶ
# 状況を再現するためであり、Zenn 記事の「ログ調査が Context Rot を起こしやすい
# 理由」で述べている distractor の多さをこのサンプルで再現することが目的である。
#
# tool_exception モードでは、さらに次の 2 点を再現する。
#   - 真因が 1 箇所のログ行にしか現れない ("紛らわしい情報" の再現)。
#     正常系ログのループの中で、これから失敗する customer_id が最後に登場する
#     1 行だけ account_tier の値が "standard" から "suspended" に変わる。
#     この行は "error" や "exception" のような検索しやすい語を含まない。
#   - 失敗メッセージの語彙と、真因の行の語彙が一致しない
#     ("問いと答えの語彙が一致しない" の再現)。ツール呼び出し失敗時のログ
#     ("upstream service rejected the request") は "account_tier" や
#     "suspended" という語を含まないため、失敗メッセージの語で検索しても
#     真因の行にはたどり着かない。
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone

from bedrock_agentcore.runtime import BedrockAgentCoreApp

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("agent-failing")

app = BedrockAgentCoreApp()

# os.environ.get(KEY, default) は KEY が空文字列で export された場合に既定値へ
# 落ちないため使わない。すべて os.environ.get(KEY) or default の形にする。
FAILURE_MODE = os.environ.get("FAILURE_MODE") or "tool_exception"
NORMAL_LOG_LINES = int(os.environ.get("NORMAL_LOG_LINES") or "200")
TIMEOUT_SLEEP_SECONDS = int(os.environ.get("TIMEOUT_SLEEP_SECONDS") or "120")

_CUSTOMER_IDS = [f"CUST-{n:05d}" for n in range(1, 21)]


def _last_index_for_customer(target_customer_id: str) -> int:
    """target_customer_id が正常系ログのループ中で最後に登場するステップ番号を返す。

    見つからない場合は -1 を返す。真因の 1 行を、失敗する直前の自然な位置
    (その顧客の直近の状態) に置くために使う。
    """
    last_index = -1
    for i in range(NORMAL_LOG_LINES):
        if _CUSTOMER_IDS[i % len(_CUSTOMER_IDS)] == target_customer_id:
            last_index = i
    return last_index


def _emit_normal_logs(
    request_id: str,
    session_id: str | None,
    target_customer_id: str,
    inject_root_cause: bool,
) -> None:
    """正常系の INFO ログを NORMAL_LOG_LINES 件出す。

    文面はほぼ同一で、ステップ番号と顧客 ID だけが変わる。実際のアプリケーション
    ログが distractor になりやすいことを再現するための構成である。

    inject_root_cause が真の場合、target_customer_id が最後に登場する行だけ
    account_tier を "suspended" にする。他の全ての行 (target_customer_id の
    他の出現も含む) は "standard" のままであり、真因はこの 1 行にしか現れない。
    """
    root_cause_index = _last_index_for_customer(target_customer_id) if inject_root_cause else -1

    for i in range(NORMAL_LOG_LINES):
        customer_id = _CUSTOMER_IDS[i % len(_CUSTOMER_IDS)]
        account_tier = "suspended" if i == root_cause_index else "standard"
        logger.info(
            "processing request request_id=%s session_id=%s step=%d customer_id=%s "
            "account_tier=%s status=in_progress",
            request_id,
            session_id,
            i,
            customer_id,
            account_tier,
        )


def _fetch_customer_record(customer_id: str) -> dict:
    """例外を投げるツール呼び出しを模した関数。FAILURE_MODE=tool_exception で使う。

    例外メッセージは "upstream service rejected the request" とだけ述べ、
    _emit_normal_logs が出す真因の行 (account_tier=suspended) の語彙を含まない。
    """
    if FAILURE_MODE == "tool_exception":
        raise RuntimeError(f"failed to fetch customer record for {customer_id}: upstream service rejected the request (HTTP 403)")
    return {"customer_id": customer_id, "status": "ok"}


@app.entrypoint
def invoke(payload, context):
    request_id = str(uuid.uuid4())
    session_id = getattr(context, "session_id", None)

    logger.info(
        "invoke start request_id=%s session_id=%s failure_mode=%s",
        request_id,
        session_id,
        FAILURE_MODE,
    )

    customer_id = payload.get("customer_id") if isinstance(payload, dict) else None
    if not customer_id:
        customer_id = _CUSTOMER_IDS[0]

    _emit_normal_logs(
        request_id,
        session_id,
        target_customer_id=customer_id,
        inject_root_cause=(FAILURE_MODE == "tool_exception"),
    )

    if FAILURE_MODE == "invalid_input":
        if not isinstance(payload, dict) or "customer_id" not in payload:
            logger.error(
                "invalid input request_id=%s session_id=%s error_type=user reason=missing_customer_id",
                request_id,
                session_id,
            )
            return {
                "status": "error",
                "error_type": "invalid_input",
                "reason": "customer_id is required",
                "request_id": request_id,
            }

    if FAILURE_MODE == "timeout":
        logger.warning(
            "simulated slow dependency request_id=%s session_id=%s sleep_seconds=%d",
            request_id,
            session_id,
            TIMEOUT_SLEEP_SECONDS,
        )
        time.sleep(TIMEOUT_SLEEP_SECONDS)
        # 通常は呼び出し元 (クライアントまたはランタイム) のタイムアウトが先に発火し、
        # ここには到達しない想定である。
        return {"status": "ok", "request_id": request_id, "note": "did not actually time out"}

    if FAILURE_MODE == "tool_exception":
        try:
            record = _fetch_customer_record(customer_id)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "tool call failed request_id=%s session_id=%s customer_id=%s error_type=%s error_message=%s",
                request_id,
                session_id,
                customer_id,
                type(exc).__name__,
                exc,
            )
            return {
                "status": "error",
                "error_type": "tool_exception",
                "reason": str(exc),
                "request_id": request_id,
            }
        logger.info("tool call succeeded request_id=%s record=%s", request_id, json.dumps(record))

    logger.info(
        "invoke end request_id=%s session_id=%s status=ok now=%s",
        request_id,
        session_id,
        datetime.now(timezone.utc).isoformat(),
    )
    return {
        "status": "ok",
        "request_id": request_id,
        "session_id": session_id,
        "failure_mode": FAILURE_MODE,
    }


if __name__ == "__main__":
    app.run()
```

</details>

次に `app/agent_failing/pyproject.toml` を、次の内容で置き換えます。雛形に含まれる `strands-agents` と `mcp` は、このサンプルでは使いません。

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "agent-failing"
version = "0.1.0"
description = "Intentionally failing sample agent that reproduces AgentCore Runtime logs for investigation"
readme = "README.md"
requires-python = ">=3.10"
dependencies = [
    "bedrock-agentcore >= 1.9.1",
    "aws-opentelemetry-distro >= 0.18.0",
]

[tool.hatch.build.targets.wheel]
packages = ["."]
```

`aws-opentelemetry-distro` はスパンの出力に必要です。0.18.0 以上を指定する理由は「オブザーバビリティ」の節に記載します。

依存を変えたので `uv.lock` を作り直します。雛形が生成した `uv.lock` は `strands-agents` などを含んだままであり、`pyproject.toml` と食い違います。

```bash
cd app/agent_failing
uv lock
cd ../..
```

雛形が生成する `mcp_client/`、`model/`、`skills/` は、貼り付けた `main.py` が import しないため使われません。残しておいても動作に影響はありません。

### 3. 環境変数を設定する

失敗モードやログ件数を変える場合は、`agentcore/agentcore.json` の該当ランタイムに `envVars` を追記します。キー名は `envVars` であり、要素は `name` と `value` を持つオブジェクトです。

```json
{
  "runtimes": [
    {
      "name": "agent_failing",
      "build": "CodeZip",
      "entrypoint": "main.py",
      "codeLocation": "app/agent_failing/",
      "envVars": [
        { "name": "FAILURE_MODE", "value": "tool_exception" },
        { "name": "NORMAL_LOG_LINES", "value": "200" },
        { "name": "UNIFIED_TRACES_DESTINATION_ENABLED", "value": "true" }
      ]
    }
  ]
}
```

`main.py` は環境変数が無い場合の既定値を持つため、`tool_exception` と 200 件でよければこの手順は省略できます。`UNIFIED_TRACES_DESTINATION_ENABLED` の意味は「オブザーバビリティ」の節に記載します。

出典: [agentcore.json schema](https://schema.agentcore.aws.dev/v1/agentcore.json)

### 4. デプロイする

```bash
agentcore deploy
```

`agentcore deploy` はコードを zip にまとめ (`--build Container` の場合はコンテナ イメージをビルドして push し)、CDK で IAM ロールと AgentCore Runtime を作成し、CloudWatch のログとオブザーバビリティを設定します。初回は CDK の bootstrap が走るため数分かかります。

デプロイ前に内容を確認する場合は次を使います。

```bash
agentcore deploy --dry-run   # デプロイせずに内容を表示する
agentcore deploy --diff      # CDK の差分を表示する
```

デプロイ後の状態は次で確認します。

```bash
agentcore status
agentcore status --json      # ランタイム ID と ARN を機械可読で取得する
```

### 5. ログを蓄積させる

ランタイムを数回呼び出します。1 回の呼び出しで正常系ログが `NORMAL_LOG_LINES` 件、真因の行が 1 行、失敗ログが 1 行出力されます。

```bash
for i in 1 2 3 4 5; do
  agentcore invoke --prompt "check account"
done
```

`agentcore invoke --prompt` は payload を CLI が組み立てます。`main.py` は payload に `customer_id` が無い場合、`CUST-00001` を対象として真因の行を埋め込みます。特定の顧客 ID を対象にしたい場合は、AWS SDK から `InvokeAgentRuntime` を呼び、payload に `customer_id` を含めてください。

```python
import json
import uuid

import boto3

client = boto3.client("bedrock-agentcore")
response = client.invoke_agent_runtime(
    agentRuntimeArn="<agentcore status で取得した ARN>",
    runtimeSessionId=str(uuid.uuid4()),
    payload=json.dumps({"customer_id": "CUST-00007"}).encode(),
    qualifier="DEFAULT",
)
print(b"".join(response.get("response", [])).decode())
```

出典: [Get started with the AgentCore CLI - Invoke an agent programmatically](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-cli.html)

### 6. 調査対象のログ グループを確認する

Skill に渡すログ グループ名を確認します。AgentCore Runtime のログ グループは 1 つで、`/aws/bedrock-agentcore/runtimes/<agent_id>-<endpoint_name>` の形式です。

```bash
agentcore logs --since 30m                 # 直近 30 分のログを表示する
agentcore logs --query "suspended"         # 真因の行だけを絞り込む
agentcore traces list                      # スパンを一覧する
```

ログ グループ名そのものは AWS CLI でも確認できます。

```bash
aws logs describe-log-groups \
  --log-group-name-prefix /aws/bedrock-agentcore/runtimes/agent_failing \
  --query 'logGroups[].logGroupName'
```

> [!NOTE]
> `filter-log-events` や Logs Insights で期間を指定する場合、呼び出しからの経過時間に注意してください。直近 30 分を指定すると、それより前に蓄積したログは 0 件になります。

### 7. クリーンアップ

> [!WARNING]
> 次の 2 コマンドは、`agentcore deploy` が作成した AWS リソースを実際に削除します。`agentcore remove all` は設定を空にするだけで、削除は続く `agentcore deploy` が実行します。削除対象は、このプロジェクトの `agentcore.json` に定義されたリソースに限られます。

```bash
agentcore remove all
agentcore deploy
```

出典: [Get started with the AgentCore CLI - Clean up](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-cli.html)

## オブザーバビリティ

スパンの出力は CLI が既定で設定します。`agentcore.json` の `instrumentation.enableOtel` が既定で true であり、entrypoint を `opentelemetry-instrument` でラップします。`--build Container` で生成される Dockerfile も、`CMD ["opentelemetry-instrument", "python", "-m", "main"]` になっています。

スパンを実際に CloudWatch へ届けるには、次の 3 つが揃っている必要があります。

- アカウントで CloudWatch Transaction Search を有効化していること。有効状態は `aws xray get-trace-segment-destination` で確認でき、`Destination` が `CloudWatchLogs` かつ `Status` が `ACTIVE` であればよいです。
- 実行ロールが対象ログ グループに対して `logs:PutResourcePolicy` を持つこと。
- ADOT が 0.18.0 以上であること。これより古いとスパンの出力先設定が無視され、共有の `aws/spans` ログ グループに出力されます。

スパンの出力先は、既定ではエージェント自身のログ グループの `spans` ログ ストリームです。対応リージョンで新規作成したエージェントが対象になります。明示的に切り替える場合は `UNIFIED_TRACES_DESTINATION_ENABLED` を `true` (自分のログ グループ) または `false` (共有の `aws/spans`) に設定します。

ADOT を入れていない場合、`spans` ログ ストリームは作成されてもイベントが 0 件になります。この状態では Skill のレイテンシ調査は結果を返せません。

出典: [Add observability to your Amazon Bedrock AgentCore resources](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html)

## 確認状況

- AgentCore CLI 0.26.0 で `agentcore create` の生成物 (`agentcore.json`、Dockerfile、`pyproject.toml`) を確認しました。公式リファレンスは 0.28.1 時点の内容です。
- 手順 4 から 7 の CLI コマンドは公式ドキュメントの記載に基づきます。本リポジトリでの実行確認は未実施です。
- サンプル エージェントの動作は us-west-2 で `tool_exception` モードを確認済みです。1 回の呼び出しで正常系ログ 200 件、真因の行 1 件、失敗ログ 1 件が出力されます。
