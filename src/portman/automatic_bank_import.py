"""Reuse established online import links without interactive reassignment."""
from copy import deepcopy
import json


def prepare_known_batches(repo, results):
    prepared, notes = [], []
    for bank, batches in results:
        for original in batches:
            if original.errors:
                notes.append(f'{bank}: ' + '; '.join(original.errors))
                continue
            previous = repo.db.execute(
                'SELECT report FROM imports WHERE active=1 AND path=? ORDER BY id DESC LIMIT 1',
                (str(original.path),)).fetchone()
            if previous is None:
                notes.append(f'{bank}: Neue Quelle noch nicht verknüpft; bitte einmal über Online-Anbindung einrichten.')
                continue
            batch = deepcopy(original)
            batch.force_import = False
            batch.account_assignments = json.loads(previous['report']).get('account_assignments', {})
            if batch.snapshots:
                target = repo.previous_bank_depot(batch.path)
                if not target:
                    notes.append(f'{bank}: Depotverknüpfung fehlt; Quelle übersprungen.')
                    continue
                sources = {snapshot.account for snapshot in batch.snapshots}
                if len(sources) != 1:
                    notes.append(f'{bank}: Mehrdeutige Depotquelle übersprungen.')
                    continue
                source = next(iter(sources))
                for snapshot in batch.snapshots:
                    snapshot.account = target
                for collection in (batch.transactions, batch.balances, batch.documents):
                    for item in collection:
                        if item.account == source:
                            item.account = target
                batch.account_names = [target if name == source else name for name in batch.account_names]
            from portfolio_v5.import_accounts import import_sources
            sources = {row['key'] for row in import_sources(batch)}
            batch.account_assignments = {key: value for key, value in batch.account_assignments.items() if key in sources}
            prepared.append(batch)
    return prepared, notes
