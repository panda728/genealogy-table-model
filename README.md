# genealogy-table-model

**Genealogy-Table-Model（系譜型モデル）— 2026 Edition**

マスタデータの「状態の上書き（UPDATE）」を廃止し、すべての変更を「事実の堆積（INSERT）」として記録する系譜型モデルの実装例です。  
`parent_rev` による変更の追跡、`branch_id` による計画データの分離、および **7つの基本動詞（Verb）** による意味論的な更新処理を定義しています。

---

## 設計の核となる概念

| 概念 | 説明 |
|------|------|
| **Fact テーブル** (`master_room_history`) | すべての変更は INSERT のみ。UPDATE は禁止。 |
| **Lineage（系譜）** | `parent_rev` により変更の経緯を連鎖させ、根から葉までの変更履歴を追跡する。 |
| **Branch（並行世界）** | `branch_id` により本番データ（`main`）から隔離された計画データを管理する。 |
| **Snapshot テーブル** (`master_room_snapshot`) | 本番ブランチの現在状態をキャッシュする Projection。マージ時に更新される。 |

---

## テーブル構成

```
branches
  branch_id       TEXT PK
  parent_branch_id TEXT FK -> branches
  status          TEXT  (active | merged | discarded)
  created_at      TEXT

master_room_history  ← Fact テーブル（INSERT のみ）
  rev             TEXT PK   — UUID
  parent_rev      TEXT FK -> master_room_history.rev
  branch_id       TEXT FK -> branches.branch_id
  verb            TEXT      — define | fix | evolve | branch | merge | suspend | discard
  room_id         TEXT      — 業務キー
  room_name       TEXT
  capacity        INTEGER
  status          TEXT      — active | suspended | discarded
  valid_from      TEXT      — ISO 8601
  note            TEXT
  created_at      TEXT      — ISO 8601

master_room_snapshot  ← Projection テーブル（本番 main ブランチの現在状態）
  room_id         TEXT PK
  room_name       TEXT
  capacity        INTEGER
  status          TEXT
  current_rev     TEXT FK -> master_room_history.rev
  branch_id       TEXT
  valid_from      TEXT
  updated_at      TEXT
```

---

## 7つの基本動詞

| 動詞 | 意味 | valid_from の扱い |
|------|------|-------------------|
| `define` | 新規エンティティの初回定義 | 指定値 |
| `fix` | 誤りの訂正（遡及的修正） | 親と同じ（変更なし） |
| `evolve` | 計画的変更（将来日付への進化） | 親より新しい値を指定 |
| `branch` | 計画ブランチの派生 | ソースブランチの値を継承 |
| `merge` | 計画ブランチを本番へ統合 | ソースブランチの最新値 |
| `suspend` | 一時停止（`status = suspended`） | 親と同じ |
| `discard` | 廃棄・論理削除（`status = discarded`） | 親と同じ |

---

## プロジェクト構成

```
genealogy-table-model/
├── schema/
│   └── ddl.sql           # テーブル DDL（SQLite / PostgreSQL 互換）
├── src/
│   ├── __init__.py
│   └── genealogy.py      # GenealogyModel クラス（7動詞の実装）
├── tests/
│   ├── __init__.py
│   └── test_genealogy.py # 全動詞・系譜・ブランチ操作のテスト（50件）
├── requirements.txt
└── README.md
```

---

## クイックスタート

```bash
pip install -r requirements.txt
python -m pytest tests/ -v
```

### 使用例

```python
from src.genealogy import GenealogyModel

model = GenealogyModel()  # インメモリ SQLite

# 1. define — 部屋を定義する
model.define("R001", "会議室A", capacity=10, valid_from="2026-01-01T00:00:00+00:00")

# 2. fix — 名称の誤りを訂正する（valid_from は変わらない）
model.fix("R001", {"room_name": "Conference Room A"}, note="英語名に統一")

# 3. evolve — 将来日付で増席する
model.evolve("R001", {"capacity": 20}, valid_from="2026-06-01T00:00:00+00:00", note="増席工事")

# 4. branch — 計画ブランチを作成する
model.branch("plan-q4")

# 5. ブランチ上で変更する（本番には影響しない）
model.evolve("R001", {"capacity": 30}, valid_from="2026-10-01T00:00:00+00:00",
             branch_id="plan-q4")

# 6. merge — 計画を本番へ反映する
model.merge("plan-q4")

# 7. suspend — 一時停止
model.suspend("R001", note="年末清掃")

# 8. discard — 廃棄
model.discard("R001", note="フロア閉鎖")

# スナップショット（現在状態）の参照
snap = model.get_snapshot("R001")
print(snap.status)  # "discarded"

# 系譜の参照
history = model.get_history("R001")
for h in history:
    print(h.verb, h.valid_from, h.capacity)
```

