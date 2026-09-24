# reproduce/ — 事象の再現

Amazon Bedrock AgentCore Runtime 上に、意図的に失敗するエージェントをデプロイし、
「似たログが大量に並ぶ中から真因を 1 行だけ見つける」というトラブルシュートを
体験するためのディレクトリです。`kiro/`、`claude-code/`、`codex/` のいずれの
Skill も、ここでデプロイしたエージェントのログを調査対象にします。

## 構成

```
reproduce/
├── README.md
├── agent-failing/
│   ├── main.py            意図的に失敗するサンプル エージェント
│   ├── Dockerfile
│   └── requirements.txt
└── scripts/
    ├── deploy.py           AgentCore Runtime へのデプロイ
    └── cleanup.py          作成したリソースの削除
```

## agent-failing/main.py がやっていること

`FAILURE_MODE` 環境変数で失敗の種類を切り替えます。

| 値 | 動作 |
|---|---|
| `tool_exception` (既定) | 模擬したツール呼び出しが例外を投げる |
| `timeout` | `TIMEOUT_SLEEP_SECONDS` 秒スリープし、呼び出し元のタイムアウトを誘発する |
| `invalid_input` | payload に `customer_id` が無い場合にバリデーション エラーを返す |
| `none` | 失敗させない (正常系ログだけを出す動作確認用) |

正常系の INFO ログを `NORMAL_LOG_LINES` 件 (既定 200、環境変数で変更可) 出力します。
文面はステップ番号と顧客 ID だけが違うほぼ同一の行であり、記事が指摘する
「似たログが大量に並ぶ中から探す」状況を再現します。

`tool_exception` モードでは、さらに次の 2 点を再現します。

- 真因は 1 箇所のログ行にしか現れません。これから失敗する顧客 ID が正常系ログの
  ループの中で最後に登場する行だけ、`account_tier` の値が `standard` から
  `suspended` に変わります。この行は `error` や `exception` のような検索しやすい
  語を含みません。
- 失敗メッセージの語彙と、真因の行の語彙が一致しません。ツール呼び出し失敗時の
  ログ (`upstream service rejected the request`) は `account_tier` や
  `suspended` という語を含まないため、失敗メッセージの語で検索しても真因の
  行にはたどり着きません。

この 2 点は、記事の「ログ調査が Context Rot を起こしやすい理由」で述べている
「紛らわしい情報 (distractor)」と「問いと答えの語彙が一致しない」を、実際の
ログとして再現したものです。

## デプロイ

```bash
cd reproduce

docker buildx build --platform linux/arm64 \
  -t <account-id>.dkr.ecr.<region>.amazonaws.com/multi-agent-design-agent-failing:latest \
  --push agent-failing/

AGENTCORE_CONTAINER_URI=<account-id>.dkr.ecr.<region>.amazonaws.com/multi-agent-design-agent-failing:latest \
  python scripts/deploy.py
```

`scripts/deploy.py` は、作成するすべてのリソース (IAM ロール、ECR リポジトリ、
AgentCore Runtime) の名前に `RESOURCE_PREFIX` (既定 `multi-agent-design-`) を付け、
AWS 呼び出しの前に対象リージョンとアカウント ID (下 4 桁以外をマスク) を表示します。
ECR リポジトリと IAM ロールが存在しない場合は作成し、作成したランタイムの ID と
ARN を `reproduce/results/deploy.json` に書き込みます。

デプロイ後、ランタイムを何度か呼び出してログを蓄積させてください。呼び出し方法は
`kiro/README.md`、`claude-code/README.md`、`codex/README.md` の前提条件を参照してください。

## クリーンアップ

> [!WARNING]
> `scripts/cleanup.py` は実際の AWS リソースを削除します。対象は `scripts/deploy.py`
> が作成した AgentCore Runtime、ECR リポジトリ、IAM ロールです。次の 2 つの
> 安全対策は両方が必須であり、片方だけでは不十分です。
>
> - プレフィックス限定: 名前が `RESOURCE_PREFIX` で始まるリソースだけを対象に
>   します。`"".startswith("")` が常に真になるため、空プレフィックスは AWS 呼び出し
>   の前に拒否します。拒否しない場合、アカウントとリージョン内のすべてのリソースが
>   対象に入ってしまいます。
> - 明示的な確認フラグ: `--yes` を渡さない限り、削除対象の一覧を表示するだけで
>   終了します。`--yes` を明示的に渡さない限り、何も削除しません。

```bash
cd reproduce
python scripts/cleanup.py        # 削除対象の一覧表示のみ
python scripts/cleanup.py --yes  # 実際に削除する
```

## 前提条件

- Python 3.10 以上である必要があります。
- リポジトリ ルートの `requirements.txt` を `pip install -r requirements.txt` で
  インストール済みである必要があります (`boto3` のみ)。
- `docker buildx` を含む Docker がインストールされている必要があります。
  AgentCore Runtime の microVM は ARM64 Linux で動作します。
- 必要な IAM 権限はリポジトリ ルートの README.md を参照してください。
