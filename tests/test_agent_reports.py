from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import pytest
from threaddesk.api.service import ThreadService
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore
from threaddesk.services.agent_reports import AgentReports


@pytest.fixture(params=[JsonStore, SQLiteStore])
def setup(request, tmp_path):
    return AgentReports(ThreadService(request.param(tmp_path)))


def send(r, instance='codex-session-a', rid='one', done='API geprüft'):
    return r.report(instance, 'Codex', rid, 'working', done, 'Tests', 'Review')


def test_identity_retry_conflict_and_current_thread(setup):
    r = setup
    active = r.svc.create('laufende fremde Arbeit')
    first = send(r)
    assert r.svc.current().id == active.id
    assert send(r)['duplicate'] is True
    assert len(r.svc.whiteboard(first['board_id'])) == 1
    with pytest.raises(ValueError, match='different content'):
        send(r, done='anderer Inhalt')
    second = send(r, instance='codex-session-b')
    assert second['board_id'] != first['board_id']
    assert len(r.snapshot()['instances']) == 2
    assert r.svc.current().id == active.id


def test_scheduler_does_not_forge_freshness(setup):
    r = setup
    send(r)
    snapshot = r.snapshot()
    reported = snapshot['instances'][0]['reported_at']
    future = datetime.now(timezone.utc) + timedelta(minutes=4)
    assert r.snapshot(now=future)['instances'][0]['freshness'] == 'stale'
    overview = r.refresh()
    count = len(r.svc.whiteboard(overview))
    assert r.refresh() == overview
    assert len(r.svc.whiteboard(overview)) == count
    assert r.snapshot()['instances'][0]['reported_at'] == reported
    assert 'Maschinenlesbar' in r.svc.get(overview).context.notes


def test_atomic_registration(tmp_path):
    # Separate service/store objects exercise the workspace lock shared by writers.
    def run(_):
        return send(AgentReports(ThreadService(JsonStore(tmp_path))))
    with ThreadPoolExecutor(max_workers=4) as pool:
        values = list(pool.map(run, range(4)))
    assert len({v['board_id'] for v in values}) == 1
    assert sum(not v['duplicate'] for v in values) == 1


def test_rejects_invalid_input(setup):
    with pytest.raises(ValueError):
        send(setup, instance='../foreign')
    assert not setup.snapshot()['instances']


def test_reserved_identity_and_archived_board(setup):
    r = setup
    with pytest.raises(ValueError):
        send(r, instance='overview')
    result = send(r)
    r.svc.archive(result['board_id'])
    with pytest.raises(ValueError, match='archived'):
        send(r, rid='two')
    assert not r.snapshot()['instances']


def test_foreign_metadata_cannot_break_overview(setup):
    r = setup
    board = send(r)['board_id']
    r.svc.append_whiteboard(board, actor='other', actor_type='system', entry_type='note',
                            content='Fremder Beitrag', metadata={'agent_report': 'invalid'})
    assert len(r.snapshot()['instances']) == 1
    send(r, rid='two')
    assert r.snapshot()['instances'][0]['report_id'] == 'two'
