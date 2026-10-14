"""Shared progress and cancellation ledger for background work."""
import time
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog,QVBoxLayout,QLabel,QProgressBar,QPushButton,QTableWidget
from .import_jobs import DatabaseJob
from .busy_indicator import busy_operation


class JobCenter(QDialog):
    def __init__(self,parent):
        super().__init__(parent); self.setWindowTitle('PortMan 09 · Aufträge'); self.resize(900,450)
        self.records=[]; layout=QVBoxLayout(self); self.table=QTableWidget(); layout.addWidget(self.table)
        button=QPushButton('Ausgewählten Auftrag abbrechen'); button.clicked.connect(self.cancel); layout.addWidget(button)
        self.timer=QTimer(self); self.timer.timeout.connect(self.refresh); self.timer.setInterval(1000)
        self._rendered=[]
    def showEvent(self,event): super().showEvent(event); self.timer.start(); self.refresh()
    def hideEvent(self,event): self.timer.stop(); super().hideEvent(event)
    def register(self,job,title):
        if any(r['job'] is job for r in self.records): return
        row=dict(job=job,title=title,start=time.monotonic(),end=None,status='Läuft',progress='')
        self.records.append(row)
        def progress(*args): row['progress']=' / '.join(str(x) for x in args)
        def failed(message): row['status']='Fehler: '+str(message)
        def done():
            row['end']=time.monotonic()
            if row['status']=='Läuft': row['status']='Beendet' if not job.isInterruptionRequested() else 'Beendet · Abbruch war angefordert; Ergebnis prüfen'
            self.refresh()
            if hasattr(job,'function'): job.function=None
            completed=[r for r in self.records if r['end'] is not None]
            if len(completed)>64:
                self.records.remove(completed[0])
        if hasattr(job,'progress'): job.progress.connect(progress)
        if hasattr(job,'failed'): job.failed.connect(failed)
        job.finished.connect(done); self.refresh()
    def refresh(self):
        if not self.isVisible(): return
        from PySide6.QtWidgets import QTableWidgetItem
        rows=[[r['title'],r['status'],r['progress'],str(round((r['end'] or time.monotonic())-r['start']))] for r in self.records]
        if self.table.columnCount()!=4: self.table.setColumnCount(4); self.table.setHorizontalHeaderLabels(['Auftrag','Status','Fortschritt','Dauer (s)'])
        self.table.setRowCount(len(rows))
        for i,row in enumerate(rows):
            for c,value in enumerate(row):
                if i>=len(self._rendered) or self._rendered[i][c]!=value: self.table.setItem(i,c,QTableWidgetItem(value))
        self._rendered=rows
    def cancel(self):
        i=self.table.currentRow()
        if i>=0 and self.records[i]['end'] is None:
            self.records[i]['job'].requestInterruption(); self.records[i]['progress']='Abbruch angefordert'


@busy_operation
def run_job(parent,path,title,function):
    class Progress(QDialog):
        def reject(self):
            job.requestInterruption(); note.setText('Abbruch angefordert. Ein bereits gespeichertes Ergebnis bleibt erhalten.'); cancel.setEnabled(False)
        def closeEvent(self,event): event.ignore(); self.reject()
    dialog=Progress(parent); dialog.setWindowTitle(title); layout=QVBoxLayout(dialog)
    note=QLabel(title); note.setWordWrap(True); layout.addWidget(note)
    progress=QProgressBar(); progress.setRange(0,0); layout.addWidget(progress)
    cancel=QPushButton('Abbrechen'); cancel.clicked.connect(dialog.reject); layout.addWidget(cancel)
    job=DatabaseJob(path,function,parent); results=[]; errors=[]
    job.phase.connect(note.setText)
    owner=parent
    while owner is not None and not hasattr(owner,'job_center'): owner=owner.parent()
    if owner is not None: owner.job_center.register(job,title)
    job.result.connect(results.append); job.failed.connect(errors.append)
    def advance(n,total): progress.setRange(0,max(1,total)); progress.setValue(n)
    job.progress.connect(advance); job.finished.connect(dialog.accept)
    job.start(); dialog.exec(); job.wait()
    if errors: raise ValueError(errors[0])
    if not results: raise ValueError('Vorgang abgebrochen.')
    return results[0]
