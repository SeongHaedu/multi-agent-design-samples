# codex/ — AgentCore Runtime ログ調査

このファイルは Codex CLI が実行のたびに読み込む AGENTS.md である。Codex を
このディレクトリ (`codex/`) を作業ディレクトリにして起動した場合に発見される。

AgentCore Runtime 上のエージェントのトラブルシューティングを依頼された場合は、
`.agents/skills/agentcore-log-investigation/SKILL.md` の 4 ステップ
(目的確認 → ログ取得と要約 (subagent) → 結論提示 → 結論のレビュー (subagent))
に従うこと。このスキルは `$agentcore-log-investigation` の `$` メンションで
明示的に呼び出せるほか、`description` に基づく暗黙のマッチングでも呼び出される。

利用する subagent は `.codex/agents/error-investigator.toml`、
`latency-investigator.toml`、`reviewer.toml` の 3 つであり、`name` フィールド
の値で指定して委譲する。

`tools/logs_insights.py` と `tools/span_filter.py` はこのディレクトリの外
(リポジトリ ルートの `tools/`) にある。subagent への指示はいずれも
`../tools/...` という相対パスで参照する前提になっている。
