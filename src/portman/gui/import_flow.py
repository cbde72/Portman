"""File/PDF import flows, preview handling and account glue."""
from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMessageBox

from portman.accounts_dialog import AccountsDialog
from portman.busy_indicator import busy_cursor
from portman.import_preview import ImportPreviewDialog
from portman.import_worker import ImportWorker

from portman.gui.window_compat import project_root


class ImportFlowMixin:
    def import_start_folder(self, default=None):
        """Return the last successfully selected import folder when available."""
        remembered = self.settings.get('last_import_folder')
        if remembered and Path(remembered).is_dir():
            return remembered
        return str(default or project_root())

    def remember_import_folder(self, selection):
        """Persist a selected file's parent (or a selected directory) immediately."""
        path = Path(selection)
        folder = path if path.is_dir() else path.parent
        self.settings['last_import_folder'] = str(folder.resolve())
        storage = getattr(self, 'storage', None)
        if storage is not None:
            storage.save_settings(self.settings)

    def import_csv(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Bestände, Transaktionen oder PDFs importieren", ImportFlowMixin.import_start_folder(self), "Alle Importdateien (*.pdf *.csv *.xlsx *.xls *.ods);;PDF-Dokumente (*.pdf)")
        if paths:
            ImportFlowMixin.remember_import_folder(self, paths[0])
            self.run_repository_import(paths)

    def import_renault_pdf(self):
        if getattr(self, 'import_worker', None) and self.import_worker.isRunning():
            self.status_bar.showMessage('Ein Import wird bereits eingelesen.', 5000)
            return
        paths, _ = QFileDialog.getOpenFileNames(self, 'Renault PDF importieren',
            ImportFlowMixin.import_start_folder(self, project_root() / 'history' / 'renault'), 'PDF-Kontoauszüge (*.pdf)')
        if not paths:
            return
        ImportFlowMixin.remember_import_folder(self, paths[0])
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.import_worker = ImportWorker(paths, self, document_tags=self.settings.get('import_document_tags'))
        self.import_worker.progress.connect(self.update_progress)
        self.import_worker.parsed.connect(self.finish_renault_pdf_import)
        self.import_worker.finished.connect(lambda: self.progress_bar.setVisible(False))
        self.import_worker.start()

    def import_baader_pdf(self):
        if getattr(self, 'import_worker', None) and self.import_worker.isRunning():
            self.status_bar.showMessage('Ein Import wird bereits eingelesen.', 5000)
            return
        from portman.baader_pdf_import import baader_pdf_files
        default = project_root() / 'history' / 'baader' / '3128164_20260929' / '3128164' / 'PDF'
        if not default.is_dir():
            default = project_root() / 'history' / 'baader'
        folder = QFileDialog.getExistingDirectory(self, 'Baader-PDF-Ordner mit Unterordnern importieren',
                                                 ImportFlowMixin.import_start_folder(self, self.settings.get('baader_pdf_folder', default)))
        if not folder:
            return
        try:
            paths = baader_pdf_files(folder)
        except ValueError as error:
            QMessageBox.warning(self, 'Baader PDF importieren', str(error))
            return
        if not paths:
            QMessageBox.information(self, 'Baader PDF importieren',
                                    'Keine PDF-Dateien im gewählten Ordner und seinen Unterordnern gefunden.')
            return
        self.settings['baader_pdf_folder'] = folder
        ImportFlowMixin.remember_import_folder(self, folder)
        self.status_bar.showMessage(f'Baader: {len(paths)} PDFs gefunden · Kontozuordnung in der Importvorschau.', 12000)
        self.run_repository_import(paths)

    def import_comdirect_pdf(self):
        if getattr(self, 'import_worker', None) and self.import_worker.isRunning():
            self.status_bar.showMessage('Ein Import wird bereits eingelesen.', 5000)
            return
        paths, _ = QFileDialog.getOpenFileNames(self, 'comdirect Finanzreports importieren',
            ImportFlowMixin.import_start_folder(self, project_root() / 'history' / 'comdirect' / 'finanzreports'), 'PDF-Finanzreports (*.pdf)')
        if paths:
            ImportFlowMixin.remember_import_folder(self, paths[0])
            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
            self.import_worker = ImportWorker(paths, self, document_tags=self.settings.get('import_document_tags'))
            self.import_worker.progress.connect(self.update_progress)
            self.import_worker.parsed.connect(self.finish_comdirect_pdf_import)
            self.import_worker.finished.connect(lambda: self.progress_bar.setVisible(False))
            self.import_worker.start()

    def finish_comdirect_pdf_import(self, batches):
        from portman.comdirect_pdf_preview import ComdirectPdfPreviewDialog
        self.progress_bar.setVisible(False)
        try:
            preview = ComdirectPdfPreviewDialog(self.repository, batches, self)
            if preview.exec() != 1:
                return
            from portman.comdirect_import import commit_reports
            from portman.jobs_v09 import run_job
            selected = preview.selected_batches()
            versioned = hasattr(self.repository, 'backups_enabled')
            backup = versioned and self.repository.backups_enabled
            repository_type = type(self.repository)
            results = run_job(self, self.repository.store.path, 'Finanzreports speichern',
                lambda job: commit_reports(job, selected, repository_type, versioned, backup=backup))
            if any(r['status'] == 'imported' for r in results):
                self.refresh_scope_choices()
                self.reload_portfolio(visible_only=hasattr(self, '_scope_refreshers'))
            imported = sum(r['status'] == 'imported' for r in results)
            duplicates = sum(r['status'] == 'duplicate' for r in results)
            errors = [r for r in results if r['status'] == 'error']
            cancelled = sum(r['status'] == 'cancelled' for r in results)
            self.status_bar.showMessage(
                f'comdirect: {imported} Dateien importiert, {duplicates} bereits vorhanden, {cancelled} abgebrochen, {len(errors)} Fehler.', 15000)
            if errors:
                QMessageBox.warning(self, 'comdirect-Import', '\n'.join(
                    f"{Path(r['path']).name}: {'; '.join(r['errors'])}" for r in errors))
        except Exception as error:
            QMessageBox.warning(self, 'comdirect-Import', str(error))

    def finish_renault_pdf_import(self, batches):
        from portman.renault_pdf_import import import_renault_batches
        from portman.renault_pdf_preview import RenaultPdfPreviewDialog
        try:
            self.progress_bar.setVisible(False)
            from portman.import_options import choose_import_options
            batches = choose_import_options(self, self.repository, batches)
            if not batches:
                return
            with busy_cursor():
                preview = RenaultPdfPreviewDialog(self.repository, batches, self)
            if preview.exec() != 1:
                return
            with busy_cursor():
                results = import_renault_batches(self.repository, preview.selected_batches())
            self.refresh_scope_choices()
            self.reload_portfolio()
            imported = sum(r['status'] == 'imported' for r in results)
            errors = [r for r in results if r['status'] == 'error']
            self.status_bar.showMessage(f'Renault: {imported} Auszüge importiert / aktualisiert, {len(errors)} ausgelassen.', 12000)
            if errors:
                QMessageBox.warning(self, 'Renault PDF importieren', '\n'.join(
                    f"{Path(r['path']).name}: {'; '.join(r['errors'])}" for r in errors))
        except Exception as error:
            QMessageBox.warning(self, 'Renault PDF importieren', str(error))
        finally:
            self.progress_bar.setVisible(False)

    def manage_accounts(self):
        dialog = AccountsDialog(self.repository, project_root() / 'history', self)
        dialog.changed.connect(self.accounts_changed)
        dialog.exec()

    def accounts_changed(self):
        self.refresh_scope_choices()
        self.reload_portfolio()

    def select_overview_account(self, name):
        index = self.combo_account.findData(name)
        if index >= 0:
            self.combo_account.setCurrentIndex(index)

    def sync_history(self, checked=False, savings=False):
        from portman.history_import import history_files
        try:
            paths = history_files(project_root() / 'history')
        except ValueError as error:
            QMessageBox.warning(self, 'History-Import', str(error)); return
        if not paths:
            QMessageBox.information(self, 'History-Import', 'Keine Excel-Dateien im Ordner history gefunden.'); return
        self.run_repository_import(paths, history_sheets="savings" if savings else True)

    def run_repository_import(self, paths, history_sheets=False):
        if getattr(self, 'import_worker', None) and self.import_worker.isRunning():
            self.status_bar.showMessage('Ein Import wird bereits eingelesen.', 5000)
            return
        self.progress_bar.setVisible(True); self.progress_bar.setRange(0,100); self.progress_bar.setValue(0)
        self.import_worker = ImportWorker(paths, self, history_sheets=history_sheets,
                                          document_tags=self.settings.get('import_document_tags'))
        self.import_worker.progress.connect(self.update_progress)
        self.import_worker.parsed.connect(lambda batches: self.preview_parsed_import(batches, history_sheets))
        self.import_worker.finished.connect(lambda: self.progress_bar.setVisible(False))
        self.import_worker.start()

    def preview_parsed_import(self, batches, history_sheets=False):
        if not history_sheets and batches and all(b.document_type == 'comdirect Finanzreport' for b in batches):
            return self.finish_comdirect_pdf_import(batches)
        from portman.import_options import choose_import_options
        batches = choose_import_options(self, self.repository, batches)
        if not batches:
            self.progress_bar.setVisible(False)
            return
        try:
            self.progress_bar.setRange(0,100); self.progress_bar.setVisible(False)
            if history_sheets == "savings":
                from portman.history_overview_dialog import HistoryOverviewDialog
                preview = HistoryOverviewDialog(self.repository, batches, self, savings=history_sheets == "savings")
            elif history_sheets:
                from portman.history_sheet_dialog import HistorySheetDialog
                preview = HistorySheetDialog(self.repository, batches, self)
            else:
                preview = ImportPreviewDialog(self.repository,batches,self)
            accepted = preview.exec() == 1
            if getattr(preview, 'accounts_created', False):
                self.refresh_scope_choices(); self.reload_portfolio()
            if not accepted: return
            selected = preview.selected if history_sheets else preview.selected_batches()
            if not selected: return
            self.progress_bar.setVisible(True);self.progress_bar.setRange(0,0)
            with busy_cursor():
                results = self.repository.commit_batches(selected)
            errors = [r for r in results if r['status']=='error']
            imported = sum(r['status']=='imported' for r in results)
            duplicates = sum(r['status']=='duplicate' for r in results)
            self.refresh_scope_choices()
            if (imported or duplicates) and any(b.source_sheet.startswith('Online ') for b in selected):
                self.combo_snapshot.blockSignals(True)
                self.combo_snapshot.setCurrentIndex(0)
                self.combo_snapshot.blockSignals(False)
                from PySide6.QtCore import QDate
                self.date_selector.blockSignals(True)
                self.date_selector.setDate(QDate.currentDate())
                self.date_selector.blockSignals(False)
                self.update_date_navigation()
            self.reload_portfolio()
            self.status_bar.showMessage(f"{imported} importiert, {duplicates} unverändert, {len(errors)} fehlerhaft",7000)
            if history_sheets is True and not errors and (imported or duplicates):
                QMessageBox.information(self, 'Excel-Blatt importiert',
                    f'{selected[0].source_sheet} · {len(selected)} Excel-Dateien\n'
                    'Das Blatt ist als importiert markiert. Frühere Bestände bleiben erhalten.')
            if errors: QMessageBox.warning(self,"Import mit Fehlern","\n".join(f"{Path(r['path']).name}: {'; '.join(r['errors'])}" for r in errors[:20]))
        finally:
            self.progress_bar.setRange(0,100); self.progress_bar.setVisible(False)
