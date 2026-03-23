"""
系譜型モデル (GenealogyModel) のテストスイート

各テストは独立したインメモリ SQLite データベースを使用し、
7つの基本動詞および系譜・ブランチ操作を検証する。
"""

import pytest
from src.genealogy import GenealogyModel, PRODUCTION_BRANCH


# ---------------------------------------------------------------------------
# フィクスチャ
# ---------------------------------------------------------------------------

@pytest.fixture
def model():
    """テストごとにクリーンなインメモリ DB を提供する"""
    m = GenealogyModel(":memory:")
    yield m
    m.close()


# ---------------------------------------------------------------------------
# 動詞 1: define
# ---------------------------------------------------------------------------

class TestDefine:
    def test_define_creates_history_record(self, model):
        rev = model.define("R001", "会議室A", 10, "2026-01-01T00:00:00+00:00")
        history = model.get_history("R001")
        assert len(history) == 1
        h = history[0]
        assert h.rev == rev
        assert h.verb == "define"
        assert h.room_id == "R001"
        assert h.room_name == "会議室A"
        assert h.capacity == 10
        assert h.status == "active"
        assert h.parent_rev is None
        assert h.branch_id == PRODUCTION_BRANCH

    def test_define_updates_snapshot(self, model):
        rev = model.define("R001", "会議室A", 10, "2026-01-01T00:00:00+00:00")
        snap = model.get_snapshot("R001")
        assert snap is not None
        assert snap.room_id == "R001"
        assert snap.room_name == "会議室A"
        assert snap.capacity == 10
        assert snap.status == "active"
        assert snap.current_rev == rev

    def test_define_same_room_twice_raises(self, model):
        model.define("R001", "会議室A", 10, "2026-01-01T00:00:00+00:00")
        with pytest.raises(ValueError, match="既に存在します"):
            model.define("R001", "会議室A重複", 20, "2026-02-01T00:00:00+00:00")

    def test_define_on_branch_does_not_update_production_snapshot(self, model):
        model.define("R001", "会議室A", 10, "2026-01-01T00:00:00+00:00")
        model.branch("plan-2026", PRODUCTION_BRANCH)
        model.define("R002", "会議室B", 5, "2026-01-01T00:00:00+00:00", branch_id="plan-2026")
        # ブランチ上の define は本番スナップショットに反映されない
        assert model.get_snapshot("R002") is None

    def test_define_with_note(self, model):
        model.define("R001", "会議室A", 10, "2026-01-01T00:00:00+00:00", note="初回登録")
        history = model.get_history("R001")
        assert history[0].note == "初回登録"


# ---------------------------------------------------------------------------
# 動詞 2: fix
# ---------------------------------------------------------------------------

class TestFix:
    def test_fix_corrects_room_name(self, model):
        model.define("R001", "会議室A（誤）", 10, "2026-01-01T00:00:00+00:00")
        rev = model.fix("R001", {"room_name": "会議室A"}, note="名称誤り訂正")
        history = model.get_history("R001")
        assert len(history) == 2
        latest = history[-1]
        assert latest.rev == rev
        assert latest.verb == "fix"
        assert latest.room_name == "会議室A"
        # valid_from は変わらない（訂正なので）
        assert latest.valid_from == history[0].valid_from

    def test_fix_links_parent_rev(self, model):
        rev1 = model.define("R001", "会議室A（誤）", 10, "2026-01-01T00:00:00+00:00")
        rev2 = model.fix("R001", {"room_name": "会議室A"})
        history = model.get_history("R001")
        assert history[-1].parent_rev == rev1
        assert history[-1].rev == rev2

    def test_fix_updates_snapshot(self, model):
        model.define("R001", "会議室A（誤）", 10, "2026-01-01T00:00:00+00:00")
        model.fix("R001", {"room_name": "会議室A"})
        snap = model.get_snapshot("R001")
        assert snap.room_name == "会議室A"

    def test_fix_capacity(self, model):
        model.define("R001", "会議室A", 10, "2026-01-01T00:00:00+00:00")
        model.fix("R001", {"capacity": 12})
        snap = model.get_snapshot("R001")
        assert snap.capacity == 12

    def test_fix_nonexistent_room_raises(self, model):
        with pytest.raises(ValueError, match="存在しません"):
            model.fix("R999", {"room_name": "存在しない部屋"})

    def test_fix_discarded_room_raises(self, model):
        model.define("R001", "会議室A", 10, "2026-01-01T00:00:00+00:00")
        model.discard("R001")
        with pytest.raises(ValueError, match="discard"):
            model.fix("R001", {"room_name": "復活試み"})

    def test_fix_invalid_column_raises(self, model):
        model.define("R001", "会議室A", 10, "2026-01-01T00:00:00+00:00")
        with pytest.raises(ValueError, match="変更できないカラム"):
            model.fix("R001", {"status": "discarded"})


# ---------------------------------------------------------------------------
# 動詞 3: evolve
# ---------------------------------------------------------------------------

class TestEvolve:
    def test_evolve_creates_new_revision_with_new_valid_from(self, model):
        model.define("R001", "会議室A", 10, "2026-01-01T00:00:00+00:00")
        rev = model.evolve("R001", {"capacity": 20}, "2026-06-01T00:00:00+00:00")
        history = model.get_history("R001")
        assert len(history) == 2
        latest = history[-1]
        assert latest.rev == rev
        assert latest.verb == "evolve"
        assert latest.capacity == 20
        assert latest.valid_from == "2026-06-01T00:00:00+00:00"

    def test_evolve_links_parent_rev(self, model):
        rev1 = model.define("R001", "会議室A", 10, "2026-01-01T00:00:00+00:00")
        rev2 = model.evolve("R001", {"capacity": 20}, "2026-06-01T00:00:00+00:00")
        history = model.get_history("R001")
        assert history[-1].parent_rev == rev1
        assert history[-1].rev == rev2

    def test_evolve_updates_snapshot(self, model):
        model.define("R001", "会議室A", 10, "2026-01-01T00:00:00+00:00")
        model.evolve("R001", {"room_name": "会議室A（改装後）"}, "2026-06-01T00:00:00+00:00")
        snap = model.get_snapshot("R001")
        assert snap.room_name == "会議室A（改装後）"
        assert snap.valid_from == "2026-06-01T00:00:00+00:00"

    def test_evolve_with_older_valid_from_raises(self, model):
        model.define("R001", "会議室A", 10, "2026-06-01T00:00:00+00:00")
        with pytest.raises(ValueError, match="新しくなければなりません"):
            model.evolve("R001", {"capacity": 20}, "2026-01-01T00:00:00+00:00")

    def test_evolve_with_same_valid_from_raises(self, model):
        model.define("R001", "会議室A", 10, "2026-01-01T00:00:00+00:00")
        with pytest.raises(ValueError, match="新しくなければなりません"):
            model.evolve("R001", {"capacity": 20}, "2026-01-01T00:00:00+00:00")

    def test_evolve_discarded_room_raises(self, model):
        model.define("R001", "会議室A", 10, "2026-01-01T00:00:00+00:00")
        model.discard("R001")
        with pytest.raises(ValueError, match="discard"):
            model.evolve("R001", {"capacity": 20}, "2027-01-01T00:00:00+00:00")

    def test_evolve_suspended_room_is_allowed(self, model):
        """suspended 状態の部屋も evolve で属性変更できる（status は suspended のまま維持）"""
        model.define("R001", "会議室A", 10, "2026-01-01T00:00:00+00:00")
        model.suspend("R001", note="改装中")
        rev = model.evolve("R001", {"capacity": 15}, "2026-06-01T00:00:00+00:00",
                           note="改装後の収容人数を更新")
        history = model.get_history("R001")
        latest = history[-1]
        assert latest.rev == rev
        assert latest.verb == "evolve"
        assert latest.capacity == 15
        assert latest.status == "suspended"  # status は変わらず suspended のまま

    def test_evolve_invalid_column_raises(self, model):
        model.define("R001", "会議室A", 10, "2026-01-01T00:00:00+00:00")
        with pytest.raises(ValueError, match="変更できないカラム"):
            model.evolve("R001", {"status": "suspended"}, "2027-01-01T00:00:00+00:00")


# ---------------------------------------------------------------------------
# 動詞 4: branch
# ---------------------------------------------------------------------------

class TestBranch:
    def test_branch_creates_new_branch(self, model):
        model.define("R001", "会議室A", 10, "2026-01-01T00:00:00+00:00")
        model.branch("plan-2026")
        branches = model.list_branches()
        branch_ids = [b["branch_id"] for b in branches]
        assert "plan-2026" in branch_ids

    def test_branch_copies_rooms_to_new_branch(self, model):
        model.define("R001", "会議室A", 10, "2026-01-01T00:00:00+00:00")
        model.branch("plan-2026")
        history = model.get_history("R001", branch_id="plan-2026")
        assert len(history) == 1
        assert history[0].verb == "branch"
        assert history[0].room_name == "会議室A"

    def test_branch_has_correct_parent_branch(self, model):
        model.define("R001", "会議室A", 10, "2026-01-01T00:00:00+00:00")
        model.branch("plan-2026")
        branches = model.list_branches()
        plan = next(b for b in branches if b["branch_id"] == "plan-2026")
        assert plan["parent_branch_id"] == PRODUCTION_BRANCH

    def test_branch_duplicate_id_raises(self, model):
        model.branch("plan-2026")
        with pytest.raises(ValueError, match="既に存在します"):
            model.branch("plan-2026")

    def test_branch_nonexistent_source_raises(self, model):
        with pytest.raises(ValueError, match="存在しません"):
            model.branch("new-plan", source_branch_id="nonexistent")

    def test_branch_links_parent_rev_to_source(self, model):
        rev1 = model.define("R001", "会議室A", 10, "2026-01-01T00:00:00+00:00")
        model.branch("plan-2026")
        history = model.get_history("R001", branch_id="plan-2026")
        # ブランチ上の最初のリビジョンの parent_rev はソースのrevを指す
        assert history[0].parent_rev == rev1


# ---------------------------------------------------------------------------
# 動詞 5: merge
# ---------------------------------------------------------------------------

class TestMerge:
    def test_merge_brings_changes_to_target(self, model):
        model.define("R001", "会議室A", 10, "2026-01-01T00:00:00+00:00")
        model.branch("plan-2026")
        model.evolve("R001", {"capacity": 30}, "2026-06-01T00:00:00+00:00",
                     branch_id="plan-2026")
        merged = model.merge("plan-2026")
        assert len(merged) == 1
        snap = model.get_snapshot("R001")
        assert snap.capacity == 30
        assert snap.valid_from == "2026-06-01T00:00:00+00:00"

    def test_merge_creates_merge_verb_in_history(self, model):
        model.define("R001", "会議室A", 10, "2026-01-01T00:00:00+00:00")
        model.branch("plan-2026")
        model.evolve("R001", {"capacity": 30}, "2026-06-01T00:00:00+00:00",
                     branch_id="plan-2026")
        model.merge("plan-2026")
        history = model.get_history("R001")
        verbs = [h.verb for h in history]
        assert "merge" in verbs

    def test_merge_sets_source_branch_to_merged(self, model):
        model.branch("plan-2026")
        model.merge("plan-2026")
        branches = model.list_branches()
        plan = next(b for b in branches if b["branch_id"] == "plan-2026")
        assert plan["status"] == "merged"

    def test_merge_already_merged_raises(self, model):
        model.branch("plan-2026")
        model.merge("plan-2026")
        with pytest.raises(ValueError, match="active ではありません"):
            model.merge("plan-2026")

    def test_merge_nonexistent_branch_raises(self, model):
        with pytest.raises(ValueError, match="存在しません"):
            model.merge("nonexistent-branch")

    def test_merge_only_changed_rooms_are_merged(self, model):
        model.define("R001", "会議室A", 10, "2026-01-01T00:00:00+00:00")
        model.define("R002", "会議室B", 20, "2026-01-01T00:00:00+00:00")
        model.branch("plan-2026")
        # plan-2026 では R001 だけ変更する
        model.evolve("R001", {"capacity": 30}, "2026-06-01T00:00:00+00:00",
                     branch_id="plan-2026")
        merged = model.merge("plan-2026")
        # R002 はブランチで変更されていないのでマージ対象外
        assert len(merged) == 1
        # R002 のスナップショットは変わらない
        snap_r002 = model.get_snapshot("R002")
        assert snap_r002.capacity == 20

    def test_merge_preserves_lineage(self, model):
        model.define("R001", "会議室A", 10, "2026-01-01T00:00:00+00:00")
        model.branch("plan-2026")
        model.evolve("R001", {"capacity": 30}, "2026-06-01T00:00:00+00:00",
                     branch_id="plan-2026")
        model.merge("plan-2026")
        # マージ後のメインブランチ履歴に merge リビジョンが存在し、
        # そのリビジョンから lineage を辿れることを確認する
        history = model.get_history("R001")
        merge_rev = next(h for h in history if h.verb == "merge")
        lineage = model.get_lineage(merge_rev.rev)
        verbs_in_lineage = [r.verb for r in lineage]
        # 系譜は define -> merge と続く
        assert verbs_in_lineage[0] == "define"
        assert verbs_in_lineage[-1] == "merge"


# ---------------------------------------------------------------------------
# 動詞 6: suspend
# ---------------------------------------------------------------------------

class TestSuspend:
    def test_suspend_changes_status(self, model):
        model.define("R001", "会議室A", 10, "2026-01-01T00:00:00+00:00")
        model.suspend("R001", note="改装中")
        snap = model.get_snapshot("R001")
        assert snap.status == "suspended"

    def test_suspend_creates_history_record(self, model):
        model.define("R001", "会議室A", 10, "2026-01-01T00:00:00+00:00")
        model.suspend("R001", note="改装中")
        history = model.get_history("R001")
        assert history[-1].verb == "suspend"
        assert history[-1].status == "suspended"

    def test_suspend_links_parent_rev(self, model):
        rev1 = model.define("R001", "会議室A", 10, "2026-01-01T00:00:00+00:00")
        model.suspend("R001")
        history = model.get_history("R001")
        assert history[-1].parent_rev == rev1

    def test_suspend_nonexistent_room_raises(self, model):
        with pytest.raises(ValueError, match="存在しません"):
            model.suspend("R999")

    def test_suspend_already_suspended_raises(self, model):
        model.define("R001", "会議室A", 10, "2026-01-01T00:00:00+00:00")
        model.suspend("R001")
        with pytest.raises(ValueError, match="suspended"):
            model.suspend("R001")

    def test_suspend_discarded_room_raises(self, model):
        model.define("R001", "会議室A", 10, "2026-01-01T00:00:00+00:00")
        model.discard("R001")
        with pytest.raises(ValueError, match="discard"):
            model.suspend("R001")


# ---------------------------------------------------------------------------
# 動詞 7: discard
# ---------------------------------------------------------------------------

class TestDiscard:
    def test_discard_changes_status(self, model):
        model.define("R001", "会議室A", 10, "2026-01-01T00:00:00+00:00")
        model.discard("R001", note="廃止")
        snap = model.get_snapshot("R001")
        assert snap.status == "discarded"

    def test_discard_creates_history_record(self, model):
        model.define("R001", "会議室A", 10, "2026-01-01T00:00:00+00:00")
        model.discard("R001", note="廃止")
        history = model.get_history("R001")
        assert history[-1].verb == "discard"
        assert history[-1].status == "discarded"

    def test_discard_links_parent_rev(self, model):
        rev1 = model.define("R001", "会議室A", 10, "2026-01-01T00:00:00+00:00")
        model.discard("R001")
        history = model.get_history("R001")
        assert history[-1].parent_rev == rev1

    def test_discard_nonexistent_room_raises(self, model):
        with pytest.raises(ValueError, match="存在しません"):
            model.discard("R999")

    def test_discard_already_discarded_raises(self, model):
        model.define("R001", "会議室A", 10, "2026-01-01T00:00:00+00:00")
        model.discard("R001")
        with pytest.raises(ValueError, match="discard"):
            model.discard("R001")


# ---------------------------------------------------------------------------
# 系譜 (Lineage) の検証
# ---------------------------------------------------------------------------

class TestLineage:
    def test_lineage_traversal(self, model):
        rev1 = model.define("R001", "会議室A", 10, "2026-01-01T00:00:00+00:00")
        rev2 = model.fix("R001", {"room_name": "会議室A（訂正）"})
        rev3 = model.evolve("R001", {"capacity": 15}, "2026-06-01T00:00:00+00:00")

        lineage = model.get_lineage(rev3)
        assert len(lineage) == 3
        assert lineage[0].rev == rev1
        assert lineage[0].verb == "define"
        assert lineage[1].rev == rev2
        assert lineage[1].verb == "fix"
        assert lineage[2].rev == rev3
        assert lineage[2].verb == "evolve"

    def test_lineage_from_root_returns_single_item(self, model):
        rev1 = model.define("R001", "会議室A", 10, "2026-01-01T00:00:00+00:00")
        lineage = model.get_lineage(rev1)
        assert len(lineage) == 1
        assert lineage[0].rev == rev1
        assert lineage[0].parent_rev is None

    def test_lineage_unknown_rev_returns_empty(self, model):
        lineage = model.get_lineage("nonexistent-uuid")
        assert lineage == []


# ---------------------------------------------------------------------------
# 複合シナリオ
# ---------------------------------------------------------------------------

class TestCompoundScenarios:
    def test_full_lifecycle(self, model):
        """define -> fix -> evolve -> suspend -> evolve -> discard の完全なライフサイクル"""
        # 初回定義
        rev1 = model.define("R001", "会議室A", 10, "2026-01-01T00:00:00+00:00")
        # 名称訂正
        rev2 = model.fix("R001", {"room_name": "Conference Room A"})
        # 増席
        rev3 = model.evolve("R001", {"capacity": 20}, "2026-04-01T00:00:00+00:00",
                            note="増席工事完了")
        # 一時停止
        rev4 = model.suspend("R001", note="年末清掃")
        # ※ suspended 状態でも evolve は可能 (status は suspended のまま)
        # 廃止
        rev5 = model.discard("R001", note="フロア閉鎖")

        history = model.get_history("R001")
        assert len(history) == 5
        verbs = [h.verb for h in history]
        assert verbs == ["define", "fix", "evolve", "suspend", "discard"]

        snap = model.get_snapshot("R001")
        assert snap.status == "discarded"

        # 系譜の確認
        lineage = model.get_lineage(rev5)
        assert len(lineage) == 5
        assert lineage[0].parent_rev is None  # 根は親なし
        for i in range(1, 5):
            assert lineage[i].parent_rev == lineage[i - 1].rev  # 連鎖

    def test_branch_evolve_and_merge(self, model):
        """branch -> plan上でevolve -> merge のシナリオ"""
        model.define("R001", "会議室A", 10, "2026-01-01T00:00:00+00:00")
        model.define("R002", "会議室B", 20, "2026-01-01T00:00:00+00:00")

        # 計画ブランチ作成
        model.branch("plan-q3")

        # 計画ブランチ上で変更
        model.evolve("R001", {"capacity": 25}, "2026-07-01T00:00:00+00:00",
                     branch_id="plan-q3")
        model.suspend("R002", note="Q3改装", branch_id="plan-q3")

        # 本番スナップショットはまだ変わっていない
        assert model.get_snapshot("R001").capacity == 10
        assert model.get_snapshot("R002").status == "active"

        # マージ
        merged = model.merge("plan-q3")
        assert len(merged) == 2

        # 本番スナップショットが更新された
        assert model.get_snapshot("R001").capacity == 25
        assert model.get_snapshot("R002").status == "suspended"

    def test_multiple_rooms_independent_history(self, model):
        """複数部屋の履歴が独立していることを確認"""
        model.define("R001", "会議室A", 10, "2026-01-01T00:00:00+00:00")
        model.define("R002", "会議室B", 20, "2026-01-01T00:00:00+00:00")
        model.evolve("R001", {"capacity": 15}, "2026-06-01T00:00:00+00:00")

        assert len(model.get_history("R001")) == 2
        assert len(model.get_history("R002")) == 1

    def test_no_direct_updates_in_history(self, model):
        """全操作が INSERT のみで記録されていることを確認（履歴は増加のみ）"""
        model.define("R001", "会議室A", 10, "2026-01-01T00:00:00+00:00")
        count_after_define = len(model.get_history("R001"))
        model.fix("R001", {"room_name": "会議室A（改）"})
        count_after_fix = len(model.get_history("R001"))
        model.evolve("R001", {"capacity": 12}, "2026-06-01T00:00:00+00:00")
        count_after_evolve = len(model.get_history("R001"))

        # 毎回1件ずつ増える（UPDATEではなくINSERT）
        assert count_after_define == 1
        assert count_after_fix == 2
        assert count_after_evolve == 3
