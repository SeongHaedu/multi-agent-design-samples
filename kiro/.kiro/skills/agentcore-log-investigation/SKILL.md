---
name: agentcore-log-investigation
description: >
  Amazon Bedrock AgentCore Runtime 上で動くエージェントのトラブルシューティングで、
  CloudWatch Logs Insights のログとスパンを調査するときに使う。ユーザーが
  「このエージェントが失敗している原因を調べたい」「セッション <id> で何が起きたか
  知りたい」のように、AgentCore Runtime のログ グループを対象にした調査を依頼した
  場合に使う。main agent の context にログの生データを読み込まず、Sub-agent へ
  取得・絞り込み・要約を委譲し、main agent には Sub-agent が保存した Markdown
  ファイルのパスを含む JSON だけを返させる。結論の提示後は、その結論が根拠となる
  ファイルの内容だけに基づいているかを別の Sub-agent にレビューさせる。
---

# AgentCore Runtime ログ調査 (Kiro 版)

このスキルは、agentskills.io の Agent Skills 標準に準拠した SKILL.md である。
`kiro/.kiro/agents/log-investigator.json` の `resources` フィールドが
`file://.kiro/skills/**/SKILL.md` を参照しているため、`kiro-cli --agent
log-investigator` で起動したときに読み込み対象になる。main agent は特定の
スキルに固定されておらず、依頼内容に該当するスキルを `.kiro/skills/` 配下から
選ぶ。AgentCore Runtime のログ調査を依頼された場合にこのスキルが該当する。

利用する Sub-agent は `kiro/.kiro/agents/error-investigator.json`、
`latency-investigator.json`、`reviewer.json` の 3 つであり、`name` フィールド
の値で指定して委譲する。

`tools/logs_insights.py` と `tools/span_filter.py` はこのディレクトリの外
(リポジトリ ルートの `tools/`) にある。Sub-agent への指示はいずれも
`../tools/...` という相対パスで参照する前提になっている。

## Pipeline Display

▶ Executing agentcore-log-investigation

Pipeline: 🎯 目的確認 → 🔎 ログ取得と要約 (subagent) → 📝 結論提示 → ✅ レビュー (subagent)

Sub-agent が担うステップには `(subagent)` と明記する。ユーザーは、そのステップの
間は main agent の context に何も残っていないことを理解した上で待てる。

## Step 1: 調査目的の確認

main agent が対話し、以下を確定する。

- ログ グループ名。AgentCore Runtime のログ グループは
  `/aws/bedrock-agentcore/runtimes/<agent_id>-<endpoint_name>` の 1 つにまとまっており、
  ログストリームは CloudWatch コンソールで実機を確認したところ 3 つある。
  `<YYYY>/<MM>/<DD>/[runtime-logs-<uuid>]<id>` (エージェント コンテナの stdout と
  stderr。例: `2026/09/24/[runtime-logs-7a322d83-af0a-470d-a270-031f98f9b319]eec9b279-bf1...`。
  先頭が日付で、UUID を含むサフィックスが付くことを実機で確認した)、`otel-rt-logs`
  (OTEL 形式のログ。内容は公式ドキュメントで確認できていない)、`spans` (トレース
  スパン。unified span destination を設定した場合) の 3 つである。unified span
  destination を設定していない場合、スパンは共有の `aws/spans` ログ グループに
  出力される。ログストリームを絞り込む必要がある場合は、クエリ内で `@logStream` を
  使う。stdout/stderr のログストリーム名は先頭が日付であるため前方一致では絞り込めず、
  `@logStream like /runtime-logs/` のように部分一致で絞り込む。`otel-rt-logs` は
  `runtime-logs` という文字列を含まないため、この部分一致で誤って拾うことはない。
- 対象期間 (start_time, end_time)。ユーザーとのやり取りでは JST の `yyyy/mm/dd HH:MM:SS` 形式で確認し、Logs Insights に渡す値は epoch seconds に変換して保持する。指定がなければ既定 60 分を JST 表記でユーザーに提示し、合意を得る。
- 調査目的。エラー調査 / レイテンシ調査 / 両方のいずれかを確定する。
- 分かっている場合は session_id または trace_id。

**Constraints:**
- MUST: ログ グループ名・対象期間・調査目的の 3 つがすべて確定するまで Step 2 に進まないこと。
- MUST_NOT: ログ取得の前に目的確認を省略しないこと。

**Acceptance Criteria:**
- ログ グループ名が確定している。
- 対象期間 (start_time, end_time) が確定しており、JST 表記と epoch seconds の両方を保持している。
- 調査目的 (error / latency / both のいずれか) が確定している。

> Checkpoint の `{{start_jst}}` と `{{end_jst}}` は JST の `yyyy/mm/dd HH:MM:SS` 形式で表示する。Sub-agent へ渡すのは epoch seconds の値である。

**Checkpoint:**
```
✅ Step 1: 調査目的確認完了 — ログ グループ {{log_group}}、対象期間 {{start_jst}} 〜 {{end_jst}} (JST)、目的 {{purpose}}
↪️ (c)ontinue: ログ取得へ進む
↪️ (e)dit: 目的や範囲を修正する
↪️ (a)bort: 中止
```

**Constraints:**
- MUST: ユーザーの応答を待つこと。Checkpoint を表示した直後に自分で (c) を選んで先へ進んではならない。
- MUST: (c)/(e)/(a) 以外の入力を受け取った場合は同じ Checkpoint を再表示すること。

## Step 2: ログ取得と要約 (subagent)

調査目的に応じて Sub-agent を分ける。エラー調査とレイテンシ調査を 1 つの
Sub-agent に任せると、先に見つけたエラーの内容が後の探索方針を引きずるため、
目的が独立しているなら Sub-agent 自体を分ける。

- 目的が error のみ: `error-investigator` を 1 回委譲する。
- 目的が latency のみ: `latency-investigator` を 1 回委譲する。
- 目的が both: 上記 2 つを委譲する。

**Sub-agent (error-investigator):**
- name: error-investigator
- 渡す内容: |
    ```
    対象ロググループ: {{log_group}}
    対象期間 (epoch seconds): {{start}} 〜 {{end}}
    調査目的: エラーの原因調査
    出力先: outputs/investigations/{{session_id}}/errors.md
    ```

**Sub-agent (latency-investigator):**
- name: latency-investigator
- 渡す内容: |
    ```
    対象ロググループ: {{log_group}}
    対象期間 (epoch seconds): {{start}} 〜 {{end}}
    調査目的: レイテンシの外れ値調査
    ログストリームの絞り込み: @logStream like /^spans/ (runtime-logs ストリームには latency_ms/duration が含まれない)
    出力先: outputs/investigations/{{session_id}}/latency.md
    ```

各 Sub-agent の詳細な手順 (`../tools/logs_insights.py` の呼び出し方、
`| limit` の推奨値、`../tools/span_filter.py` によるノイズ除去、返す JSON の
形式) は `.kiro/agents/error-investigator.json` と
`.kiro/agents/latency-investigator.json` の `prompt` フィールドに定義済みで
あり、ここでは対象・期間・出力先と、調査対象に固有の絞り込み条件だけを渡す。
Sub-agent の `prompt` は AWS のログ調査全般に使える汎用の内容にしてあり、
AgentCore Runtime に固有の前提 (ログストリームの分かれ方) はこのスキルの側で
渡している。

**Constraints:**
- MUST: Sub-agent には調査目的・対象期間・出力先パス・ログストリームの絞り込み条件だけを渡すこと。ログの断片や過去の調査結果を渡す内容に含めないこと。
- MUST: エラー調査とレイテンシ調査は別の Sub-agent に分けること。1 つの Sub-agent に両方を任せないこと。
- MUST: Sub-agent が返した JSON をそのまま信用せず、`saved_to` の Markdown を読み込んで下記 Acceptance Criteria で検証すること。
- MUST_NOT: ログの生レコードを main agent の応答や context に含めないこと。

**Acceptance Criteria:**
- Sub-agent が `status: completed` の JSON を返している。
- `saved_to` に書かれたパスに、main agent がファイル読み込みで確認した結果、ファイルが実在する。
- `saved_to` の拡張子が `.md` である。
- 保存された Markdown に「調査メタデータ」「サマリ」「根拠ログの抜粋」の見出しが含まれている。
- 「根拠ログの抜粋」に `@timestamp` と `@message` の引用が含まれている。
- エラー調査の場合、「真因の候補」の見出しと、「根拠ログの抜粋」配下の「エラー直前のログ」の小見出しが含まれている。エラー行だけを取得して終わっていないことを、この 2 つの存在で確認する。
- 真因の候補が 0 件の場合、「候補は見つかりませんでした」と記録されている。0 件であること自体は失敗ではない。
- 上記のいずれかを満たさない場合、そのステップは失敗として扱い、下記 Checkpoint で (r)etry を選べるようにする。

**Checkpoint:**
```
✅ Step 2: ログ取得完了 — 対象期間 {{start_jst}} 〜 {{end_jst}} (JST)、取得件数 {{count}} 件
↪️ (c)ontinue: 結論提示へ進む
↪️ (n)arrow: 時間範囲を絞り直す
↪️ (r)etry: Sub-agent を再実行する
↪️ (a)bort: 中止
```

**Constraints:**
- MUST: ユーザーの応答を待つこと。Checkpoint を表示した直後に自分で (c) を選んで先へ進んではならない。
- MUST: (c)/(n)/(r)/(a) 以外の入力を受け取った場合は同じ Checkpoint を再表示すること。

## Step 3: 結論の提示

main agent は、Step 2 で Sub-agent が返した `saved_to` のパスだけをファイル
読み込みで読み込み、結論を Markdown にまとめて
`outputs/investigations/{{session_id}}/conclusion.md` に保存する。ユーザーには
保存先のパスと、真因・根拠・未確定の点の要点を提示する。

`conclusion.md` は次の見出しをこの順で含める。

```markdown
# 調査結果

## 調査メタデータ
対象ログ グループ、対象期間 (JST の `yyyy/mm/dd HH:MM:SS` と epoch seconds の両方)、調査目的、根拠ファイルのパス。

## サマリ
真因、または真因を特定できていないこと。3 行以内。

## 根拠
主張ごとに、対応する根拠ファイルの記載 (真因の候補の該当行、集計値、統計) を対応付けて書く。

## 根拠ログの抜粋
根拠ファイルから引用したログ行。@timestamp と @message を含める。

## 確定していない点
ログから読み取れなかったこと、相関に基づく推定であること。無い場合は「なし」と書く。
```

**Constraints:**
- MUST: 保存された Markdown を読み込んで確認すること。Sub-agent の応答テキストの記述だけを信用しないこと。
- MUST: 結論の各主張に、根拠ファイルの該当箇所を対応付けて書くこと。根拠ファイルに記載のない数値や固有名詞を書いてはならない。
- MUST: エラー調査の結論では、「真因の候補」と「エラー直前のログ」を確認したうえで真因を述べること。エラー メッセージの文面をそのまま真因として述べてはならない。エラー メッセージは失敗した箇所と症状を示すだけであり、真因は別の行に記録されていることがある。
- MUST: 真因の候補が 0 件だった場合は、真因を特定できていないことを明示すること。エラー メッセージからの推測を真因として提示してはならない。
- MUST_NOT: Step 2 で保存した成果物以外の新しいログ取得を、この Step で行わないこと。追加取得が必要な場合は Step 1 に戻る。

**Acceptance Criteria:**
- `outputs/investigations/{{session_id}}/conclusion.md` が実在する。
- `conclusion.md` に「調査メタデータ」「サマリ」「根拠」「根拠ログの抜粋」の見出しが含まれている。
- 「調査メタデータ」に根拠ファイルのパスが書かれている。
- 結論が根拠ファイルの記載に基づいている。

**Checkpoint:**
```
✅ Step 3: 結論提示完了 — 保存先 {{conclusion_path}}
↪️ (c)ontinue: レビューへ進む
↪️ (a)bort: 中止
```

**Constraints:**
- MUST: ユーザーの応答を待つこと。
- MUST: (c)/(a) 以外の入力を受け取った場合は同じ Checkpoint を再表示すること。

## Step 4: 結論のレビュー (subagent)

main agent は、Step 3 で保存した結論を検証するため、`reviewer` を委譲する。
reviewer に渡すのは、`conclusion.md` のパスと、その根拠となったファイルのパス
(Step 2 で保存した `errors.md` や `latency.md`) だけである。結論文の本文は渡さない。
reviewer は自分でファイルを読み、結論の各主張が根拠ファイルの記載に対応しているか、
main agent が context に持っていない情報を推測で補っていないかを確認する。

**Sub-agent (reviewer):**
- name: reviewer
- 渡す内容: |
    ```
    以下の結論ファイルが、根拠ファイルの内容だけに基づいているかを検証せよ。

    結論ファイル: outputs/investigations/{{session_id}}/conclusion.md
    根拠ファイル: {{evidence_md_paths}}
    ```

**Constraints:**
- MUST: reviewer には結論ファイルと根拠ファイルのパスだけを渡すこと。結論文の本文やログの生データを渡さないこと。
- MUST_NOT: reviewer にファイルの書き込みを行わせないこと。`.kiro/agents/reviewer.json` は `tools` に `read` だけを割り当てているため、構造的に書き込みができない。
- MUST: reviewer が返した JSON をそのまま信用せず、下記 Acceptance Criteria で検証すること。

**Acceptance Criteria:**
- Sub-agent が `status: completed` の JSON を返している。
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
