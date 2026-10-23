"""Save reports on the job's own connection, with per-file progress."""


def commit_reports(job, batches, repository_type, versioned=True, backup=False):
    repo = repository_type(job.path, backups=False) if versioned else repository_type(job.path)
    results = []
    try:
        if backup and batches and not job.isInterruptionRequested():
            repo.backup('before-import')
        for index, batch in enumerate(batches):
            if job.isInterruptionRequested():
                results.extend({'path': b.path, 'status': 'cancelled'} for b in batches[index:])
                break
            try:
                # Keep the dedicated Finanzreport progress UI, but persist via
                # the V09 repository boundary.  Direct Store writes bypass the
                # reconciliation hooks for trade details and tax/dividend
                # links, which made the outcome depend on the GUI entry point.
                result = repo.commit_batches([batch])[0]
            except ValueError as error:
                result = {'status': 'error', 'errors': [str(error)]}
            result.update(path=batch.path, warnings=batch.summary()['warnings'])
            results.append(result)
            job.progress.emit(index + 1, len(batches))
        return results
    finally:
        repo.close()
