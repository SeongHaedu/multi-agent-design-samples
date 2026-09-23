---
name: agentcore-log-investigation
description: >
  Amazon Bedrock AgentCore Runtime 上で動くエージェントのトラブルシューティングで、
  CloudWatch Logs Insights のログとスパンを調査するときに使う。ユーザーが
  「このエージェントが失敗している原因を調べたい」「セッション <id> で何が起きたか
  知りたい」のように、AgentCore Runtime のログ グループを対象にした調査を依頼した
  場合に使う。main agent の context にログの生データを読み込まず、subagent へ
  取得・絞り込み・要約を委譲し、main agent には JSON の要約とファイル パスだけを
  返させる。
---

# AgentCore Runtime ログ調査

## Pipeline Display

▶ Executing agentcore-log-investigation

Pipeline: 🎯 目的確認 → 🔎 ログ取得と要約 (subagent) → 📝 結論提示

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

- 目的が error のみ: `error-investigator` の 1 subagent を起動する。
- 目的が latency のみ: `latency-investigator` の 1 subagent を起動する。
- 目的が both: 上記 2 つを並列に起動する。

**Subagent (error-investigator):**
- role: error-investigator
- prompt: |
    ```
    対象ロググループ: {{log_group}}
    対象期間 (epoch seconds): {{start}} 〜 {{end}}
    調査目的: エラーの原因調査

    手順:
    1. tools/logs_insights.py の run_logs_insights_query() を呼び出し、
       ERROR レベルのログ、または error_type 属性を持つスパンを対象に
       クエリを実行せよ。query_string には必ず | limit を含めること
       (limit=50 を推奨)。
    2. スパンを対象にした場合は、結果を tools/span_filter.py の
       filter_spans() に渡し、kept_records だけを以後の要約対象にせよ。
    3. record_count / representative_records / field_value_counts を
       outputs/investigations/{{session_id}}/errors.json に JSON で保存せよ。
    4. ログの生データを応答に含めてはならない。

    #### 出力ルール (最優先)
    保存後、以下の JSON のみを返すこと:
    {"status": "completed", "saved_to": "<実際の保存先パス>", "record_count": <件数>}
    失敗時: {"status": "failed", "reason": "<理由>"}
    ```

**Subagent (latency-investigator):**
- role: latency-investigator
- prompt: |
    ```
    対象ロググループ: {{log_group}}
    対象期間 (epoch seconds): {{start}} 〜 {{end}}
    調査目的: レイテンシの外れ値調査

    手順:
    1. tools/logs_insights.py の run_logs_insights_query() を呼び出し、
       スパンから latency_ms (または duration) を対象にクエリを実行せよ。
       query_string には必ず | limit を含めること (limit=20 を推奨)。
    2. 結果を tools/span_filter.py の filter_spans() に渡し、
       kept_records だけを以後の要約対象にせよ。
    3. record_count / representative_records / field_value_counts を
       outputs/investigations/{{session_id}}/latency.json に JSON で保存せよ。
    4. ログの生データを応答に含めてはならない。

    #### 出力ルール (最優先)
    保存後、以下の JSON のみを返すこと:
    {"status": "completed", "saved_to": "<実際の保存先パス>", "record_count": <件数>}
    失敗時: {"status": "failed", "reason": "<理由>"}
    ```

**Constraints:**
- MUST: subagent には調査目的・対象期間・出力先パスだけを渡すこと。ログの断片や過去の調査結果を prompt に含めないこと。
- MUST: エラー調査とレイテンシ調査は別の subagent に分けること。1 つの subagent に両方を任せないこと。
- MUST: subagent が返した JSON をそのまま信用せず、下記 Acceptance Criteria で検証すること。
- MUST_NOT: ログの生レコードを main agent の応答や context に含めないこと。

**Acceptance Criteria:**
- subagent が `status: completed` の JSON を返している。
- `saved_to` に書かれたパスに、main agent がファイル読み込みツールで確認した結果、ファイルが実在する。
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
読み込みツールで読み込み、`record_count` / `representative_records` /
`field_value_counts` を確認して結論を提示する。

**Constraints:**
- MUST: 保存された JSON ファイルをファイル読み込みツールで読み込んで確認すること。subagent の応答テキストの記述だけを信用しないこと。
- MUST: 結論には根拠 (representative_records の該当箇所、field_value_counts の集計値、saved_to のファイル パス) を付記すること。
- MUST_NOT: Step 2 で保存した要約以外の新しいログ取得を、この Step で行わないこと。追加取得が必要な場合は Step 1 に戻る。

**Acceptance Criteria:**
- 結論が `record_count` と `representative_records` の内容に基づいている。
- 結論に `saved_to` のファイル パスが付記されている。

**Checkpoint:**
```
✅ Step 3: 結論提示完了
↪️ (c)ontinue: 追加調査 (別の時間範囲やセッション) に進む
↪️ (f)inish: 終了
```

**Constraints:**
- MUST: ユーザーの応答を待つこと。
- MUST: (c)/(f) 以外の入力を受け取った場合は同じ Checkpoint を再表示すること。
- (c) が選ばれた場合は Step 1 に戻る。
