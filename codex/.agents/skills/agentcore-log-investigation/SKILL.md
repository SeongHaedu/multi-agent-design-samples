---
name: agentcore-log-investigation
description: >
  Amazon Bedrock AgentCore Runtime 上で動くエージェントのトラブルシューティングで、
  CloudWatch Logs Insights のログとスパンを調査するときに使う。ユーザーが
  「このエージェントが失敗している原因を調べたい」「セッション <id> で何が起きたか
  知りたい」のように、AgentCore Runtime のログ グループを対象にした調査を依頼した
  場合に使う。main agent の context にログの生データを読み込まず、subagent へ
  取得・絞り込み・要約を委譲し、main agent には JSON の要約とファイル パスだけを
  返させる。結論の提示後は、その結論が根拠となるファイルの内容だけに基づいている
  かを別の subagent にレビューさせる。
---

# AgentCore Runtime ログ調査 (Codex CLI 版)

このディレクトリ (`codex/`) を作業ディレクトリにして `codex` を起動すると、
Codex は現在のディレクトリから repo root まで `.agents/skills` を再帰的に
探索してこのスキルを見つける。呼び出しは `$agentcore-log-investigation` の
ように `$` メンションで明示するか、`description` に基づく暗黙のマッチングで
行われる。

利用する subagent は `.codex/agents/error-investigator.toml`、
`latency-investigator.toml`、`reviewer.toml` の 3 つであり、`name` フィールド
の値で指定して委譲する。

`tools/logs_insights.py` と `tools/span_filter.py` はこのディレクトリの外
(リポジトリ ルートの `tools/`) にある。`codex/` からの相対パスは
`../tools/` である。

## Pipeline Display

▶ Executing agentcore-log-investigation

Pipeline: 🎯 目的確認 → 🔎 ログ取得と要約 (subagent) → 📝 結論提示 → ✅ レビュー (subagent)

subagent が担うステップには `(subagent)` と明記する。ユーザーは、そのステップの
間は main agent の context に何も残っていないことを理解した上で待てる。

## Step 1: 調査目的の確認

main agent が対話し、以下を確定する。

- ログ グループ名。分からない場合は次の 3 パターンを提示し、どれを使うか確認する。
  - `/aws/bedrock-agentcore/runtimes/<agent_id>-<endpoint_name>/otel-rt-logs` (構造化 OTEL スパン専用)
  - `/aws/bedrock-agentcore/runtimes/<agent_id>-<endpoint_name>/[runtime-logs]` (stdout/stderr)
  - `/aws/bedrock-agentcore/runtimes/<agent_id>-<endpoint_name>-DEFAULT` (単一結合ログ グループ)
- 対象期間 (start_time, end_time。epoch seconds または「直近 N 分」)。指定がなければ既定 60 分をユーザーに提示し、合意を得る。
- 調査目的。エラー調査 / レイテンシ調査 / 両方のいずれかを確定する。
- 分かっている場合は session_id または trace_id。

**Constraints:**
- MUST: ログ グループ名・対象期間・調査目的の 3 つがすべて確定するまで Step 2 に進まないこと。
- MUST_NOT: ログ取得の前に目的確認を省略しないこと。

**Acceptance Criteria:**
- ログ グループ名が確定している。
- 対象期間 (start_time, end_time) が確定している。
- 調査目的 (error / latency / both のいずれか) が確定している。

**Checkpoint:**
```
✅ Step 1: 調査目的確認完了 — ログ グループ {{log_group}}、対象期間 {{start}} 〜 {{end}}、目的 {{purpose}}
↪️ (c)ontinue: ログ取得へ進む
↪️ (e)dit: 目的や範囲を修正する
↪️ (a)bort: 中止
```

**Constraints:**
- MUST: ユーザーの応答を待つこと。Checkpoint を表示した直後に自分で (c) を選んで先へ進んではならない。
- MUST: (c)/(e)/(a) 以外の入力を受け取った場合は同じ Checkpoint を再表示すること。

## Step 2: ログ取得と要約 (subagent)

調査目的に応じて subagent を分ける。エラー調査とレイテンシ調査を 1 つの
subagent に任せると、先に見つけたエラーの内容が後の探索方針を引きずるため、
目的が独立しているなら subagent 自体を分ける。

- 目的が error のみ: `error-investigator` を 1 回委譲する。
- 目的が latency のみ: `latency-investigator` を 1 回委譲する。
- 目的が both: 上記 2 つを委譲する。

**Subagent (error-investigator):**
- name: error-investigator
- 渡す内容: |
    ```
    対象ロググループ: {{log_group}}
    対象期間 (epoch seconds): {{start}} 〜 {{end}}
    調査目的: エラーの原因調査
    出力先: outputs/investigations/{{session_id}}/errors.json
    ```

**Subagent (latency-investigator):**
- name: latency-investigator
- 渡す内容: |
    ```
    対象ロググループ: {{log_group}}
    対象期間 (epoch seconds): {{start}} 〜 {{end}}
    調査目的: レイテンシの外れ値調査
    出力先: outputs/investigations/{{session_id}}/latency.json
    ```

各 subagent の詳細な手順 (`../tools/logs_insights.py` の呼び出し方、
`| limit` の推奨値、`../tools/span_filter.py` によるノイズ除去、返す JSON の
形式) は `.codex/agents/error-investigator.toml` と
`.codex/agents/latency-investigator.toml` の `developer_instructions` に
定義済みであり、ここでは対象・期間・出力先だけを渡す。

**Constraints:**
- MUST: subagent には調査目的・対象期間・出力先パスだけを渡すこと。ログの断片や過去の調査結果を渡す内容に含めないこと。
- MUST: エラー調査とレイテンシ調査は別の subagent に分けること。1 つの subagent に両方を任せないこと。
- MUST: subagent が返した JSON をそのまま信用せず、下記 Acceptance Criteria で検証すること。
- MUST_NOT: ログの生レコードを main agent の応答や context に含めないこと。

**Acceptance Criteria:**
- subagent が `status: completed` の JSON を返している。
- `saved_to` に書かれたパスに、main agent がファイル読み込みで確認した結果、ファイルが実在する。
- 保存された JSON に `record_count` と `representative_records` が含まれている。
- `representative_records` の各要素に `@timestamp` と `@message` が含まれている。
- 上記のいずれかを満たさない場合、そのステップは失敗として扱い、下記 Checkpoint で (r)etry を選べるようにする。

**Checkpoint:**
```
✅ Step 2: ログ取得完了 — 対象期間 {{start}} 〜 {{end}}、取得件数 {{count}} 件
↪️ (c)ontinue: 結論提示へ進む
↪️ (n)arrow: 時間範囲を絞り直す
↪️ (r)etry: subagent を再実行する
↪️ (a)bort: 中止
```

**Constraints:**
- MUST: ユーザーの応答を待つこと。Checkpoint を表示した直後に自分で (c) を選んで先へ進んではならない。
- MUST: (c)/(n)/(r)/(a) 以外の入力を受け取った場合は同じ Checkpoint を再表示すること。

## Step 3: 結論の提示

main agent は、Step 2 で subagent が返した `saved_to` のパスだけをファイル
読み込みで読み込み、`record_count` / `representative_records` /
`field_value_counts` を確認して結論を提示する。

**Constraints:**
- MUST: 保存された JSON ファイルを読み込んで確認すること。subagent の応答テキストの記述だけを信用しないこと。
- MUST: 結論には根拠 (representative_records の該当箇所、field_value_counts の集計値、saved_to のファイル パス) を付記すること。
- MUST_NOT: Step 2 で保存した要約以外の新しいログ取得を、この Step で行わないこと。追加取得が必要な場合は Step 1 に戻る。

**Acceptance Criteria:**
- 結論が `record_count` と `representative_records` の内容に基づいている。
- 結論に `saved_to` のファイル パスが付記されている。

**Checkpoint:**
```
✅ Step 3: 結論提示完了
↪️ (c)ontinue: レビューへ進む
↪️ (a)bort: 中止
```

**Constraints:**
- MUST: ユーザーの応答を待つこと。
- MUST: (c)/(a) 以外の入力を受け取った場合は同じ Checkpoint を再表示すること。

## Step 4: 結論のレビュー (subagent)

main agent は、Step 3 で提示した結論を検証するため、`reviewer` を委譲する。
reviewer に渡すのは、Step 3 の結論文と、その根拠となったファイルのパス
(Step 2 で保存した `errors.json` や `latency.json`) だけである。reviewer は、
結論文の各主張が `record_count` / `representative_records` / `field_value_counts`
のいずれかに対応する記載を持つかどうかを検証し、main agent が context に持って
いない情報を推測で補っていないかを確認する。

**Subagent (reviewer):**
- name: reviewer
- 渡す内容: |
    ```
    以下の結論文が、指定したファイルの内容だけを根拠にしているかを検証せよ。

    結論文:
    {{conclusion_text}}

    根拠ファイル:
    {{summary_json_paths}}
    ```

**Constraints:**
- MUST: reviewer には結論文と根拠ファイルのパスだけを渡すこと。ログの生データを新たに渡さないこと。
- MUST_NOT: reviewer にファイルの書き込みを行わせないこと。`.codex/agents/reviewer.toml` の `developer_instructions` に明記した MUST_NOT に依拠する (Codex の Subagent TOML には利用ツールを制限する公開ドキュメント上のフィールドが確認できなかったため、構造的な強制ではない)。
- MUST: reviewer が返した JSON をそのまま信用せず、下記 Acceptance Criteria で検証すること。

**Acceptance Criteria:**
- subagent が `status: completed` の JSON を返している。
- `verdict` が `pass` または `fail` のいずれかである。
- `verdict` が `fail` の場合、`issues` に 1 件以上の説明が含まれている。

**Checkpoint:**
```
✅ Step 4: レビュー完了 — verdict: {{verdict}}
↪️ (c)ontinue: 終了
↪️ (r)evise: Step 3 に戻り結論を修正する
↪️ (a)bort: 中止
```

**Constraints:**
- MUST: ユーザーの応答を待つこと。Checkpoint を表示した直後に自分で (c) を選んで先へ進んではならない。
- MUST: (c)/(r)/(a) 以外の入力を受け取った場合は同じ Checkpoint を再表示すること。
- (r) が選ばれた場合は Step 3 に戻り、`issues` の内容を踏まえて結論を修正する。
