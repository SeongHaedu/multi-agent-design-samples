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

# AgentCore Runtime ログ調査 (Claude Code 版)

このファイルは `claude-code/` ディレクトリを cwd として `claude` を起動した場合に
発見される。使う subagent は `claude-code/.claude/agents/error-investigator.md`、
`latency-investigator.md`、`reviewer.md` の 3 つであり、Task ツールの
`subagent_type` にファイル名 (拡張子なし) を指定して起動する。

このディレクトリの `tools/logs_insights.py` と `tools/span_filter.py` への参照は、
リポジトリ ルートの `tools/` を指す。`claude-code/` からの相対パスは `../tools/` で
ある。

## Pipeline Display

▶ Executing agentcore-log-investigation

Pipeline: 🎯 目的確認 → 🔎 ログ取得と要約 (subagent) → 📝 結論提示 → ✅ レビュー (subagent)

subagent が担うステップには `(subagent)` と明記する。ユーザーは、そのステップの
間は main agent の context に何も残っていないことを理解した上で待てる。

## Step 1: 調査目的の確認

main agent が対話し、以下を確定する。

- ログ グループ名。AgentCore Runtime のログ グループは
  `/aws/bedrock-agentcore/runtimes/<agent_id>-<endpoint_name>` の 1 つにまとまっており、
  ログストリームが `spans` (トレース スパン。unified span destination を設定した場合) と
  `runtime-logs` (stdout/stderr) に分かれている。unified span destination を設定していない
  場合、スパンは共有の `aws/spans` ログ グループに出力される。ログストリームを絞り込む必要が
  ある場合は、クエリ内で `@logStream` を使う。`runtime-logs` にセッション ID 相当の
  サフィックスが付くかどうかは公式ドキュメントで確認できていないため、完全一致ではなく
  `@logStream like /^runtime-logs/` のような前方一致で絞り込む。
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

- 目的が error のみ: Task ツールで `subagent_type: error-investigator` を 1 回起動する。
- 目的が latency のみ: Task ツールで `subagent_type: latency-investigator` を 1 回起動する。
- 目的が both: 上記 2 つを 1 つのメッセージで並行して起動する。

**Task (error-investigator):**
- subagent_type: error-investigator
- prompt: |
    ```
    対象ロググループ: {{log_group}}
    対象期間 (epoch seconds): {{start}} 〜 {{end}}
    調査目的: エラーの原因調査
    出力先: outputs/investigations/{{session_id}}/errors.json
    ```

**Task (latency-investigator):**
- subagent_type: latency-investigator
- prompt: |
    ```
    対象ロググループ: {{log_group}}
    対象期間 (epoch seconds): {{start}} 〜 {{end}}
    調査目的: レイテンシの外れ値調査
    出力先: outputs/investigations/{{session_id}}/latency.json
    ```

各 subagent の詳細な手順 (`../tools/logs_insights.py` の呼び出し方、
`| limit` の推奨値、`../tools/span_filter.py` によるノイズ除去、返す JSON の形式)
は `.claude/agents/error-investigator.md` と `.claude/agents/latency-investigator.md`
の本文で定義済みであり、ここでは対象・期間・出力先だけを渡す。

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
↪️ (c)ontinue: レビューへ進む
↪️ (a)bort: 中止
```

**Constraints:**
- MUST: ユーザーの応答を待つこと。
- MUST: (c)/(a) 以外の入力を受け取った場合は同じ Checkpoint を再表示すること。

## Step 4: 結論のレビュー (subagent)

main agent は、Step 3 で提示した結論を検証するため、Task ツールで
`subagent_type: reviewer` を起動する。reviewer に渡すのは、Step 3 の結論文と、
その根拠となったファイルのパス (Step 2 で保存した `errors.json` や
`latency.json`) だけである。reviewer は、結論文の各主張が `record_count` /
`representative_records` / `field_value_counts` のいずれかに対応する記載を持つ
かどうかを検証し、main agent が context に持っていない情報を推測で補っていない
かを確認する。reviewer には Read ツールしか割り当てていないため、ファイルの
書き込みは構造的にできない。

**Task (reviewer):**
- subagent_type: reviewer
- prompt: |
    ```
    以下の結論文が、指定したファイルの内容だけを根拠にしているかを検証せよ。

    結論文:
    {{conclusion_text}}

    根拠ファイル:
    {{summary_json_paths}}
    ```

**Constraints:**
- MUST: reviewer には結論文と根拠ファイルのパスだけを渡すこと。ログの生データを新たに渡さないこと。
- MUST_NOT: reviewer にファイルの書き込みを行わせないこと。検証結果は JSON の返り値だけで受け取ること。
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
