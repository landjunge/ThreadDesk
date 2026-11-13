"""Initial source-watch checkpoints must not invalidate an unchanged index."""
import json
import pytest

from threaddesk.api.service import ThreadService
from threaddesk.services.library_api import LibraryApplication
from threaddesk.services.library_batch import LibraryBatchImporter
from threaddesk.services.library_index import LibrarySearchError
from threaddesk.services.library_refresh import refresh_existing
from threaddesk.services.library_watch import LibrarySourceWatch
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=['json', 'sqlite'])
def imported(request, tmp_path):
    store = request.param(tmp_path / 'workspace')
    thread = ThreadService(store).create('Library Project')
    source = tmp_path / 'source'
    source.mkdir()
    original = source / 'fixture.txt'
    original.write_text('unchanged library-owl marker')
    app = LibraryApplication(store)
    app.call({'action': 'import', 'operation_id': 'initial-import',
              'data': {'source': str(source), 'thread_id': thread.id}})
    app.call({'action': 'reindex', 'operation_id': 'confirmed-index'})
    yield store, app, original
    if isinstance(store, SQLiteStore):
        store.connection.close()


@pytest.mark.parametrize('edited', [False, True], ids=['imported', 'restored'])
def test_initial_pending_watch_keeps_confirmed_index_searchable(imported, monkeypatch, edited):
    store, app, original = imported
    if edited:
        record = app.call({'action': 'list'})['records'][0]
        for action, data in [('rename', {'filename': 'renamed.txt'}),
                             ('move', {'folder': 'Sorted'}), ('trash', {}),
                             ('restore', {'trash_generation': 1})]:
            record = app.call({'action': action, 'id': record['id'],
                               'operation_id': 'edit-' + action,
                               'expected_revision': record['revision'], 'data': data})['record']
    before = app.index.status()['generation'], app.index._source_state()
    records_before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns)
                      for p in app.importer.records.glob('*.json')}
    rebuild = LibraryBatchImporter._index
    observed = []

    def during_checkpoint(batch):
        # The first watch has checkpointed receipts and metadata, but has not
        # rebuilt: the confirmed source/content is still exactly the same.
        observed.append(app.index.search('library-owl'))
        return rebuild(batch)

    monkeypatch.setattr(LibraryBatchImporter, '_index', during_checkpoint)
    assert LibrarySourceWatch(store).poll_once()['outcomes'][0]['status'] == 'ready'
    assert observed and observed[0]
    assert (app.index.status()['generation'], app.index._source_state()) == before
    assert records_before == {p.name: (p.read_bytes(), p.stat().st_mtime_ns)
                              for p in app.importer.records.glob('*.json')}
    assert original.read_text() == 'unchanged library-owl marker'


def test_noop_postcommit_refresh_does_not_publish_transient_stale(imported, monkeypatch):
    store, app, _ = imported
    before = app.index.path.read_bytes()

    def forbidden(*args, **kwargs):
        raise AssertionError('unchanged sources need no index publication')

    monkeypatch.setattr(type(app.index), '_replace', forbidden)
    assert refresh_existing(store)['status'] == 'ready'
    assert app.index.path.read_bytes() == before
    assert app.index.search('library-owl')


def test_changed_watch_source_still_refuses_old_results_until_rebuild(imported, monkeypatch):
    store, app, original = imported
    LibrarySourceWatch(store).poll_once()
    original.write_text('genuinely changed source marker')
    rebuild = LibraryBatchImporter._index
    observed = []

    def during_change(batch):
        with pytest.raises(LibrarySearchError, match='index_stale'):
            app.index.search('library-owl')
        observed.append(True)
        return rebuild(batch)

    monkeypatch.setattr(LibraryBatchImporter, '_index', during_change)
    assert LibrarySourceWatch(store).poll_once()['outcomes'][0]['status'] == 'ready'
    assert observed == [True]
    assert app.index.search('genuinely changed')


def test_version_lineage_changes_remain_index_sources(imported):
    store, app, _ = imported
    path = store.workspace_path / 'library-batch-sources.json'
    sources = json.loads(path.read_text())
    receipt = next(iter(sources['sources'].values()))
    old = receipt['record_id']
    receipt.update(record_id='f' * 12, history=[old])
    path.write_text(json.dumps(sources))
    with pytest.raises(LibrarySearchError, match='index_stale'):
        app.index.search('library-owl')
    app.call({'action': 'reindex', 'operation_id': 'lineage-reindex'})
    assert app.index.search('library-owl')[0]['current_version'] is False


@pytest.mark.parametrize('backend', [JsonStore, SQLiteStore], ids=['json', 'sqlite'])
def test_partial_extraction_is_retried_by_explicit_batch_resume(tmp_path, monkeypatch, backend):
    from threaddesk.services.library_search import projections
    store = backend(tmp_path / 'workspace')
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'retry.txt').write_text('recovered extraction marker')
    batch = LibraryBatchImporter(store)
    manifest = batch.manifest_for_folder(source)
    extract = projections.extract
    try:
        monkeypatch.setattr(projections, 'extract', lambda *args: {
            'text': '', 'status': 'failed', 'error': 'temporary_fixture_failure', 'truncated': False})
        first = batch.run(manifest, operation_id='partial-extraction')
        assert first['index']['status'] == 'partial' and not first['complete']
        monkeypatch.setattr(projections, 'extract', extract)
        resumed = batch.resume('partial-extraction')
        assert resumed['complete'] and resumed['index']['status'] == 'ready'
        assert LibraryApplication(store).index.search('recovered extraction')
    finally:
        if isinstance(store, SQLiteStore):
            store.connection.close()
