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
                result = repo.store.import_batch(batch)
            except ValueError as error:
                result = {'status': 'error', 'errors': [str(error)]}
            result.update(path=batch.path, warnings=batch.summary()['warnings'])
            results.append(result)
            job.progress.emit(index + 1, len(batches))
        if any(r['status'] == 'imported' for r in results):
            repo.sync_security_master()
        return results
    finally:
        repo.close()
