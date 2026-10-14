"""Online bank synchronisation and connection setup dialogs."""


class OnlineSyncMixin:
    def sync_online_accounts(self):
        from portman.bank_sync_dialog import BankSyncDialog
        current = getattr(self, '_online_sync_dialog', None)
        if current is not None:
            self.status_bar.showMessage('Die Online-Synchronisation läuft bereits im Hintergrund.', 5000)
            return
        dialog = BankSyncDialog(self.banking_directory(), self, auto_continue=True)
        self._online_sync_dialog = dialog
        dialog.accepted.connect(lambda: self._online_sync_fetched(dialog))
        dialog.rejected.connect(lambda: self._online_sync_closed(dialog))
        dialog.status_message.connect(lambda message: self.status_bar.showMessage(
            'Online-Synchronisation · ' + message, 30000))
        dialog.setModal(False)
        self.status_bar.showMessage('Online-Konten werden im Hintergrund synchronisiert …', 30000)

    def _online_sync_closed(self, dialog):
        if getattr(self, '_online_sync_dialog', None) is dialog:
            self._online_sync_dialog = None
        dialog.deleteLater()

    def _online_sync_fetched(self, dialog):
        from portman.automatic_bank_import import prepare_known_batches
        from portman.import_jobs import DatabaseJob, commit_atomic
        try:
            combined, notes = prepare_known_batches(self.repository, dialog.results)
        except Exception as error:
            self.status_bar.showMessage(f'Online-Synchronisation konnte nicht vorbereitet werden: {error}', 30000)
            self._online_sync_closed(dialog)
            return

        log_lines = dialog.log.toPlainText().splitlines()
        self._online_sync_closed(dialog)
        if not combined:
            self._online_sync_complete([], notes, log_lines)
            return

        job = DatabaseJob(self.repository.store.path,
                          lambda worker: commit_atomic(worker, combined, create_backup=False), self)
        self._online_sync_job = job
        results, errors = [], []
        job.result.connect(results.append)
        job.failed.connect(errors.append)
        job.finished.connect(lambda: self._online_sync_saved(job, results, errors, notes, log_lines))
        if hasattr(self, 'job_center'):
            self.job_center.register(job, 'Online-Daten werden gespeichert')
        self.status_bar.showMessage('Online-Abruf beendet · Daten werden im Hintergrund gespeichert …', 30000)
        job.start()

    def _online_sync_saved(self, job, results, errors, notes, log_lines):
        if getattr(self, '_online_sync_job', None) is job:
            self._online_sync_job = None
        if errors:
            notes.extend(errors)
        self._online_sync_complete(results[0] if results else [], notes, log_lines)
        job.deleteLater()

    def _online_sync_complete(self, results, notes, log_lines):
        self.refresh_scope_choices()
        self.reload_portfolio()
        imported = sum(r['status'] == 'imported' for r in results)
        unchanged = sum(r['status'] == 'duplicate' for r in results)
        notes.extend('; '.join(r.get('errors', [])) for r in results if r['status'] == 'error')
        notes.extend(line for line in log_lines if line and line not in notes)
        self.status_bar.showMessage(f'{imported} übernommen · {unchanged} unverändert' +
                                   (' · ' + ' | '.join(notes) if notes else ''), 30000)
        self.market_widget.start(incremental=True)

    def open_connection_proposal(self):
        from PySide6.QtWidgets import QInputDialog
        from portman.ing_dialog import INGDialog, INGDepotDialog
        from portman.comdirect_dialog import ComdirectDialog
        from portman.baader_dialog import BaaderDialog
        from portman.renault_dialog import RenaultDialog
        bank, accepted = QInputDialog.getItem(self, 'Online-Anbindung', 'Bank auswählen',
                                             ['ING', 'comdirect', 'Baader / finanzen.net ZERO', 'Renault Bank direkt'], 0, False)
        if not accepted:
            return
        dialog_type = {'ING': INGDialog, 'comdirect': ComdirectDialog,
                       'Baader / finanzen.net ZERO': BaaderDialog, 'Renault Bank direkt': RenaultDialog}[bank]
        dialog = dialog_type(self.banking_directory(), self)
        self._online_connection_dialog = dialog
        dialog.accepted.connect(lambda: self._online_connection_fetched(dialog, bank, INGDepotDialog))
        dialog.rejected.connect(lambda: self._online_connection_closed(dialog))
        dialog.setModal(False)
        dialog.show()

    def _online_connection_closed(self, dialog):
        if getattr(self, '_online_connection_dialog', None) is dialog:
            self._online_connection_dialog = None
        dialog.deleteLater()

    def _online_connection_fetched(self, dialog, bank, depot_dialog_type):
        batches = dialog.batches
        self._online_connection_closed(dialog)
        if not batches:
            return
        if any(batch.snapshots and not batch.errors for batch in batches):
            depots = depot_dialog_type(self.repository, batches, self, bank=bank)
            if depots.exec() != 1:
                return
            batches = depots.batches
        self.preview_parsed_import(batches)
