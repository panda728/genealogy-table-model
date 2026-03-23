"""
Genealogy-Table-Model (系譜型モデル)
=====================================
マスタデータの「状態の上書き（UPDATE）」を廃止し、
すべての変更を「事実の堆積（INSERT）」として記録するモデル。

設計の核となる概念:
  - master_room_history: parent_rev で系譜（Lineage）を形成する Fact テーブル
  - branch_id: 本番データから隔離された「計画（並行世界）」を管理する
  - 7つの基本動詞: define / fix / evolve / branch / merge / suspend / discard
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

PRODUCTION_BRANCH = "main"

# DDLファイルのパス
_SCHEMA_FILE = Path(__file__).parent.parent / "schema" / "ddl.sql"


@dataclass
class RoomRevision:
    """master_room_history の1レコードを表す値オブジェクト"""

    rev: str
    parent_rev: Optional[str]
    branch_id: str
    verb: str
    room_id: str
    room_name: Optional[str]
    capacity: Optional[int]
    status: str
    valid_from: str
    note: Optional[str]
    created_at: str


@dataclass
class RoomSnapshot:
    """master_room_snapshot の1レコードを表す値オブジェクト"""

    room_id: str
    room_name: Optional[str]
    capacity: Optional[int]
    status: str
    current_rev: str
    branch_id: str
    valid_from: str
    updated_at: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_rev() -> str:
    return str(uuid.uuid4())


class GenealogyModel:
    """
    系譜型モデルの中心クラス。

    7つの基本動詞を通じてすべての変更を INSERT として記録し、
    parent_rev による系譜と branch_id による並行世界を管理する。

    スレッドセーフティ:
        このクラスは単一スレッドでの利用を想定している。
        複数スレッドから同一インスタンスを共有する場合は、
        呼び出し元で適切な排他制御（threading.Lock 等）を行うこと。
        check_same_thread=False は `:memory:` DB のテスト用途にのみ使用し、
        本番環境では各スレッドに独立したインスタンスを生成することを推奨する。
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()

    # ------------------------------------------------------------------
    # スキーマ初期化
    # ------------------------------------------------------------------

    def _init_schema(self) -> None:
        ddl = _SCHEMA_FILE.read_text(encoding="utf-8")
        self._conn.executescript(ddl)
        # 本番ブランチを初期登録する
        self._conn.execute(
            "INSERT OR IGNORE INTO branches (branch_id, parent_branch_id, status, created_at)"
            " VALUES (?, NULL, 'active', ?)",
            (PRODUCTION_BRANCH, _now_iso()),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # 内部ヘルパー
    # ------------------------------------------------------------------

    def _latest_rev(self, room_id: str, branch_id: str) -> Optional[sqlite3.Row]:
        """指定ブランチにおける部屋の最新リビジョンを返す"""
        return self._conn.execute(
            """
            SELECT * FROM master_room_history
            WHERE room_id = ? AND branch_id = ?
            ORDER BY valid_from DESC, created_at DESC
            LIMIT 1
            """,
            (room_id, branch_id),
        ).fetchone()

    def _insert_history(
        self,
        *,
        rev: str,
        parent_rev: Optional[str],
        branch_id: str,
        verb: str,
        room_id: str,
        room_name: Optional[str],
        capacity: Optional[int],
        status: str,
        valid_from: str,
        note: Optional[str],
        created_at: str,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO master_room_history
                (rev, parent_rev, branch_id, verb, room_id, room_name,
                 capacity, status, valid_from, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (rev, parent_rev, branch_id, verb, room_id, room_name,
             capacity, status, valid_from, note, created_at),
        )

    def _upsert_snapshot(
        self,
        *,
        room_id: str,
        room_name: Optional[str],
        capacity: Optional[int],
        status: str,
        current_rev: str,
        branch_id: str,
        valid_from: str,
        updated_at: str,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO master_room_snapshot
                (room_id, room_name, capacity, status, current_rev, branch_id, valid_from, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(room_id) DO UPDATE SET
                room_name   = excluded.room_name,
                capacity    = excluded.capacity,
                status      = excluded.status,
                current_rev = excluded.current_rev,
                branch_id   = excluded.branch_id,
                valid_from  = excluded.valid_from,
                updated_at  = excluded.updated_at
            """,
            (room_id, room_name, capacity, status, current_rev, branch_id, valid_from, updated_at),
        )

    # ------------------------------------------------------------------
    # 動詞 1: define — 部屋の初回定義
    # ------------------------------------------------------------------

    def define(
        self,
        room_id: str,
        room_name: str,
        capacity: int,
        valid_from: str,
        branch_id: str = PRODUCTION_BRANCH,
        note: str = "",
    ) -> str:
        """
        新しい部屋を定義する（初回 INSERT）。

        同じ branch_id に既存のリビジョンが存在する場合はエラーとする。
        Returns: 新しい rev (UUID)
        """
        existing = self._latest_rev(room_id, branch_id)
        if existing is not None:
            raise ValueError(
                f"room_id='{room_id}' は branch_id='{branch_id}' に既に存在します。"
                " 変更には fix または evolve を使用してください。"
            )

        rev = _new_rev()
        now = _now_iso()
        with self._conn:
            self._insert_history(
                rev=rev, parent_rev=None, branch_id=branch_id,
                verb="define", room_id=room_id, room_name=room_name,
                capacity=capacity, status="active",
                valid_from=valid_from, note=note, created_at=now,
            )
            if branch_id == PRODUCTION_BRANCH:
                self._upsert_snapshot(
                    room_id=room_id, room_name=room_name, capacity=capacity,
                    status="active", current_rev=rev, branch_id=branch_id,
                    valid_from=valid_from, updated_at=now,
                )
        return rev

    # ------------------------------------------------------------------
    # 動詞 2: fix — 誤りの訂正（同一 valid_from で上書き）
    # ------------------------------------------------------------------

    def fix(
        self,
        room_id: str,
        corrections: dict[str, Any],
        note: str = "",
        branch_id: str = PRODUCTION_BRANCH,
    ) -> str:
        """
        現在のリビジョンの誤りを訂正する。
        valid_from は親と同じ値を引き継ぐ（訂正なので有効開始日は変わらない）。

        corrections: 変更するカラムと値の辞書 (room_name / capacity のみ受け付ける)
        Returns: 新しい rev (UUID)
        """
        parent = self._latest_rev(room_id, branch_id)
        if parent is None:
            raise ValueError(
                f"room_id='{room_id}' が branch_id='{branch_id}' に存在しません。"
                " まず define を呼び出してください。"
            )
        if parent["status"] == "discarded":
            raise ValueError(f"room_id='{room_id}' は既に discard されています。")

        allowed = {"room_name", "capacity"}
        invalid_keys = set(corrections) - allowed
        if invalid_keys:
            raise ValueError(f"fix で変更できないカラム: {invalid_keys}")

        rev = _new_rev()
        now = _now_iso()
        new_room_name = corrections.get("room_name", parent["room_name"])
        new_capacity = corrections.get("capacity", parent["capacity"])

        with self._conn:
            self._insert_history(
                rev=rev, parent_rev=parent["rev"], branch_id=branch_id,
                verb="fix", room_id=room_id, room_name=new_room_name,
                capacity=new_capacity, status=parent["status"],
                valid_from=parent["valid_from"],   # 訂正なので valid_from は変えない
                note=note, created_at=now,
            )
            if branch_id == PRODUCTION_BRANCH:
                self._upsert_snapshot(
                    room_id=room_id, room_name=new_room_name, capacity=new_capacity,
                    status=parent["status"], current_rev=rev, branch_id=branch_id,
                    valid_from=parent["valid_from"], updated_at=now,
                )
        return rev

    # ------------------------------------------------------------------
    # 動詞 3: evolve — 計画的変更（新しい valid_from で進化）
    # ------------------------------------------------------------------

    def evolve(
        self,
        room_id: str,
        changes: dict[str, Any],
        valid_from: str,
        branch_id: str = PRODUCTION_BRANCH,
        note: str = "",
    ) -> str:
        """
        部屋の内容を将来日付で変更する（計画的進化）。
        valid_from は新しい日付を指定する（親より新しい日付でなければならない）。

        changes: 変更するカラムと値の辞書 (room_name / capacity のみ受け付ける)
        Returns: 新しい rev (UUID)
        """
        parent = self._latest_rev(room_id, branch_id)
        if parent is None:
            raise ValueError(
                f"room_id='{room_id}' が branch_id='{branch_id}' に存在しません。"
                " まず define を呼び出してください。"
            )
        if parent["status"] == "discarded":
            raise ValueError(f"room_id='{room_id}' は既に discard されています。")
        if valid_from <= parent["valid_from"]:
            raise ValueError(
                f"evolve の valid_from ({valid_from}) は"
                f" 現在の valid_from ({parent['valid_from']}) より新しくなければなりません。"
            )

        allowed = {"room_name", "capacity"}
        invalid_keys = set(changes) - allowed
        if invalid_keys:
            raise ValueError(f"evolve で変更できないカラム: {invalid_keys}")

        rev = _new_rev()
        now = _now_iso()
        new_room_name = changes.get("room_name", parent["room_name"])
        new_capacity = changes.get("capacity", parent["capacity"])

        with self._conn:
            self._insert_history(
                rev=rev, parent_rev=parent["rev"], branch_id=branch_id,
                verb="evolve", room_id=room_id, room_name=new_room_name,
                capacity=new_capacity, status=parent["status"],
                valid_from=valid_from,
                note=note, created_at=now,
            )
            if branch_id == PRODUCTION_BRANCH:
                self._upsert_snapshot(
                    room_id=room_id, room_name=new_room_name, capacity=new_capacity,
                    status=parent["status"], current_rev=rev, branch_id=branch_id,
                    valid_from=valid_from, updated_at=now,
                )
        return rev

    # ------------------------------------------------------------------
    # 動詞 4: branch — 計画ブランチの作成
    # ------------------------------------------------------------------

    def branch(
        self,
        new_branch_id: str,
        source_branch_id: str = PRODUCTION_BRANCH,
    ) -> None:
        """
        既存ブランチから新しい計画ブランチを派生させる。

        source_branch_id の最新リビジョン群を新ブランチのベースとする。
        """
        src_branch = self._conn.execute(
            "SELECT * FROM branches WHERE branch_id = ?", (source_branch_id,)
        ).fetchone()
        if src_branch is None:
            raise ValueError(f"source_branch_id='{source_branch_id}' が存在しません。")
        if src_branch["status"] != "active":
            raise ValueError(f"branch_id='{source_branch_id}' は active ではありません。")

        existing = self._conn.execute(
            "SELECT 1 FROM branches WHERE branch_id = ?", (new_branch_id,)
        ).fetchone()
        if existing is not None:
            raise ValueError(f"branch_id='{new_branch_id}' は既に存在します。")

        now = _now_iso()
        with self._conn:
            self._conn.execute(
                "INSERT INTO branches (branch_id, parent_branch_id, status, created_at)"
                " VALUES (?, ?, 'active', ?)",
                (new_branch_id, source_branch_id, now),
            )
            # ソースブランチの全部屋の最新リビジョンを新ブランチにコピーする
            src_rooms = self._conn.execute(
                """
                SELECT * FROM master_room_history h1
                WHERE branch_id = ?
                  AND created_at = (
                      SELECT MAX(h2.created_at)
                      FROM master_room_history h2
                      WHERE h2.room_id = h1.room_id AND h2.branch_id = h1.branch_id
                  )
                """,
                (source_branch_id,),
            ).fetchall()

            for row in src_rooms:
                new_rev = _new_rev()
                self._insert_history(
                    rev=new_rev, parent_rev=row["rev"], branch_id=new_branch_id,
                    verb="branch", room_id=row["room_id"], room_name=row["room_name"],
                    capacity=row["capacity"], status=row["status"],
                    valid_from=row["valid_from"],
                    note=f"branched from {source_branch_id}", created_at=now,
                )

    # ------------------------------------------------------------------
    # 動詞 5: merge — ブランチを本番へマージ
    # ------------------------------------------------------------------

    def merge(
        self,
        source_branch_id: str,
        target_branch_id: str = PRODUCTION_BRANCH,
    ) -> list[str]:
        """
        計画ブランチの変更内容を target_branch_id へマージする。

        source_branch_id のすべての部屋について、"branch" 動詞以降のリビジョン
        （実際に変更された部屋）を target_branch_id に統合する。
        source_branch_id は merged 状態に遷移する。

        Returns: マージされた rev のリスト
        """
        src_branch = self._conn.execute(
            "SELECT * FROM branches WHERE branch_id = ?", (source_branch_id,)
        ).fetchone()
        if src_branch is None:
            raise ValueError(f"source_branch_id='{source_branch_id}' が存在しません。")
        if src_branch["status"] != "active":
            raise ValueError(
                f"branch_id='{source_branch_id}' は active ではありません"
                f" (現在のステータス: {src_branch['status']})。"
            )

        # ソースブランチで "branch" 動詞の後に変更が加えられた部屋を探す
        changed_rooms = self._conn.execute(
            """
            SELECT DISTINCT room_id FROM master_room_history
            WHERE branch_id = ? AND verb != 'branch'
            """,
            (source_branch_id,),
        ).fetchall()

        now = _now_iso()
        merged_revs: list[str] = []

        with self._conn:
            for row in changed_rooms:
                rid = row["room_id"]
                src_latest = self._latest_rev(rid, source_branch_id)
                if src_latest is None:
                    continue
                tgt_latest = self._latest_rev(rid, target_branch_id)
                parent_rev = tgt_latest["rev"] if tgt_latest else None

                new_rev = _new_rev()
                self._insert_history(
                    rev=new_rev, parent_rev=parent_rev, branch_id=target_branch_id,
                    verb="merge", room_id=rid, room_name=src_latest["room_name"],
                    capacity=src_latest["capacity"], status=src_latest["status"],
                    valid_from=src_latest["valid_from"],
                    note=f"merged from {source_branch_id}", created_at=now,
                )
                merged_revs.append(new_rev)

                if target_branch_id == PRODUCTION_BRANCH:
                    self._upsert_snapshot(
                        room_id=rid, room_name=src_latest["room_name"],
                        capacity=src_latest["capacity"], status=src_latest["status"],
                        current_rev=new_rev, branch_id=target_branch_id,
                        valid_from=src_latest["valid_from"], updated_at=now,
                    )

            # ソースブランチを merged に更新 (history テーブルには触れず branches を UPDATE)
            # ※ branches テーブルはメタデータであり Fact テーブルではないため UPDATE を許容する
            self._conn.execute(
                "UPDATE branches SET status = 'merged' WHERE branch_id = ?",
                (source_branch_id,),
            )

        return merged_revs

    # ------------------------------------------------------------------
    # 動詞 6: suspend — 一時停止
    # ------------------------------------------------------------------

    def suspend(
        self,
        room_id: str,
        note: str = "",
        branch_id: str = PRODUCTION_BRANCH,
    ) -> str:
        """
        部屋を一時停止状態にする。
        status を 'suspended' に変更した新リビジョンを INSERT する。

        Returns: 新しい rev (UUID)
        """
        parent = self._latest_rev(room_id, branch_id)
        if parent is None:
            raise ValueError(f"room_id='{room_id}' が branch_id='{branch_id}' に存在しません。")
        if parent["status"] == "discarded":
            raise ValueError(f"room_id='{room_id}' は既に discard されています。")
        if parent["status"] == "suspended":
            raise ValueError(f"room_id='{room_id}' は既に suspended です。")

        rev = _new_rev()
        now = _now_iso()
        with self._conn:
            self._insert_history(
                rev=rev, parent_rev=parent["rev"], branch_id=branch_id,
                verb="suspend", room_id=room_id, room_name=parent["room_name"],
                capacity=parent["capacity"], status="suspended",
                valid_from=parent["valid_from"], note=note, created_at=now,
            )
            if branch_id == PRODUCTION_BRANCH:
                self._upsert_snapshot(
                    room_id=room_id, room_name=parent["room_name"],
                    capacity=parent["capacity"], status="suspended",
                    current_rev=rev, branch_id=branch_id,
                    valid_from=parent["valid_from"], updated_at=now,
                )
        return rev

    # ------------------------------------------------------------------
    # 動詞 7: discard — 廃棄（論理削除）
    # ------------------------------------------------------------------

    def discard(
        self,
        room_id: str,
        note: str = "",
        branch_id: str = PRODUCTION_BRANCH,
    ) -> str:
        """
        部屋を廃棄状態にする（論理削除）。
        status を 'discarded' に変更した新リビジョンを INSERT する。
        discard 後は fix / evolve / suspend を呼び出せない。

        Returns: 新しい rev (UUID)
        """
        parent = self._latest_rev(room_id, branch_id)
        if parent is None:
            raise ValueError(f"room_id='{room_id}' が branch_id='{branch_id}' に存在しません。")
        if parent["status"] == "discarded":
            raise ValueError(f"room_id='{room_id}' は既に discard されています。")

        rev = _new_rev()
        now = _now_iso()
        with self._conn:
            self._insert_history(
                rev=rev, parent_rev=parent["rev"], branch_id=branch_id,
                verb="discard", room_id=room_id, room_name=parent["room_name"],
                capacity=parent["capacity"], status="discarded",
                valid_from=parent["valid_from"], note=note, created_at=now,
            )
            if branch_id == PRODUCTION_BRANCH:
                self._upsert_snapshot(
                    room_id=room_id, room_name=parent["room_name"],
                    capacity=parent["capacity"], status="discarded",
                    current_rev=rev, branch_id=branch_id,
                    valid_from=parent["valid_from"], updated_at=now,
                )
        return rev

    # ------------------------------------------------------------------
    # クエリヘルパー
    # ------------------------------------------------------------------

    def get_snapshot(self, room_id: str) -> Optional[RoomSnapshot]:
        """本番スナップショットから部屋の現在状態を取得する"""
        row = self._conn.execute(
            "SELECT * FROM master_room_snapshot WHERE room_id = ?", (room_id,)
        ).fetchone()
        if row is None:
            return None
        return RoomSnapshot(**dict(row))

    def get_lineage(self, rev: str) -> list[RoomRevision]:
        """
        指定リビジョンから根（parent_rev = NULL）まで遡った系譜を返す。
        リストは古い順（根が先頭）。
        """
        lineage: list[RoomRevision] = []
        current_rev: Optional[str] = rev
        while current_rev is not None:
            row = self._conn.execute(
                "SELECT * FROM master_room_history WHERE rev = ?", (current_rev,)
            ).fetchone()
            if row is None:
                break
            lineage.append(RoomRevision(**dict(row)))
            current_rev = row["parent_rev"]
        lineage.reverse()
        return lineage

    def get_history(self, room_id: str, branch_id: str = PRODUCTION_BRANCH) -> list[RoomRevision]:
        """指定ブランチにおける部屋の履歴を古い順で返す"""
        rows = self._conn.execute(
            """
            SELECT * FROM master_room_history
            WHERE room_id = ? AND branch_id = ?
            ORDER BY valid_from ASC, created_at ASC
            """,
            (room_id, branch_id),
        ).fetchall()
        return [RoomRevision(**dict(r)) for r in rows]

    def list_branches(self) -> list[dict[str, Any]]:
        """すべてのブランチ一覧を返す"""
        rows = self._conn.execute("SELECT * FROM branches ORDER BY created_at").fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        self._conn.close()
