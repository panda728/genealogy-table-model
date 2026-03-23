-- ============================================================
-- Genealogy-Table-Model DDL (2026 Edition)
-- 系譜型マスタデータ設計パターン
--
-- 設計原則:
--   - UPDATE禁止: すべての変更はINSERTで記録する
--   - parent_rev: 変更の親リビジョンを紐づけ、系譜(Lineage)を形成する
--   - branch_id: 本番データから隔離された計画（並行世界）を管理する
--   - verb: 7つの基本動詞でデータのライフサイクルを記述する
-- ============================================================

-- ブランチ管理テーブル
-- 本番ブランチは branch_id = 'main' とする
CREATE TABLE IF NOT EXISTS branches (
    branch_id       TEXT NOT NULL,           -- ブランチ識別子
    parent_branch_id TEXT,                   -- 派生元ブランチ
    status          TEXT NOT NULL DEFAULT 'active',  -- active | merged | discarded
    created_at      TEXT NOT NULL,           -- 作成日時 (ISO 8601)
    PRIMARY KEY (branch_id),
    FOREIGN KEY (parent_branch_id) REFERENCES branches(branch_id)
);

-- 系譜型履歴テーブル (Fact Table)
-- すべての変更はINSERTのみ。UPDATEは禁止。
CREATE TABLE IF NOT EXISTS master_room_history (
    rev         TEXT NOT NULL,               -- リビジョンID (UUID)
    parent_rev  TEXT,                        -- 親リビジョンID (NULLは最初の定義)
    branch_id   TEXT NOT NULL DEFAULT 'main',-- ブランチ識別子
    verb        TEXT NOT NULL,               -- define|fix|evolve|branch|merge|suspend|discard
    room_id     TEXT NOT NULL,               -- 部屋の業務キー
    room_name   TEXT,                        -- 部屋名
    capacity    INTEGER,                     -- 収容人数
    status      TEXT NOT NULL DEFAULT 'active', -- active | suspended | discarded
    valid_from  TEXT NOT NULL,               -- この改訂が有効になる日時 (ISO 8601)
    note        TEXT,                        -- 変更理由・メモ
    created_at  TEXT NOT NULL,              -- レコード作成日時 (ISO 8601)
    PRIMARY KEY (rev),
    FOREIGN KEY (parent_rev) REFERENCES master_room_history(rev),
    FOREIGN KEY (branch_id)  REFERENCES branches(branch_id),
    CHECK (verb IN ('define','fix','evolve','branch','merge','suspend','discard')),
    CHECK (status IN ('active','suspended','discarded'))
);

-- インデックス: 部屋IDとブランチIDで効率的に最新リビジョンを取得する
CREATE INDEX IF NOT EXISTS idx_mrh_room_branch
    ON master_room_history (room_id, branch_id, valid_from DESC);

-- インデックス: parent_rev による系譜探索を高速化する
CREATE INDEX IF NOT EXISTS idx_mrh_parent_rev
    ON master_room_history (parent_rev);

-- スナップショットテーブル (Projection Table)
-- 本番ブランチ (main) の現在状態を保持する。マージ時に更新される。
CREATE TABLE IF NOT EXISTS master_room_snapshot (
    room_id     TEXT NOT NULL,               -- 部屋の業務キー
    room_name   TEXT,                        -- 部屋名
    capacity    INTEGER,                     -- 収容人数
    status      TEXT NOT NULL DEFAULT 'active', -- active | suspended | discarded
    current_rev TEXT NOT NULL,               -- 対応する最新リビジョンID
    branch_id   TEXT NOT NULL DEFAULT 'main',-- ブランチ識別子 (通常はmain)
    valid_from  TEXT NOT NULL,               -- 現在のリビジョンが有効になる日時
    updated_at  TEXT NOT NULL,               -- スナップショット更新日時
    PRIMARY KEY (room_id),
    FOREIGN KEY (current_rev) REFERENCES master_room_history(rev),
    FOREIGN KEY (branch_id)   REFERENCES branches(branch_id)
);
