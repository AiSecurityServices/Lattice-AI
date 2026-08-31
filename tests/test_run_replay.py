from lattice_ai.run_replay import replay_page


def test_replay_page_paginates():
    run = {"id": "r1", "events": [{"seq": 1}, {"seq": 2}, {"seq": 3}]}
    page = replay_page(run, after=0, limit=2)
    assert len(page["events"]) == 2
    assert page["next_after"] == 2
    assert page["has_more"] is True
