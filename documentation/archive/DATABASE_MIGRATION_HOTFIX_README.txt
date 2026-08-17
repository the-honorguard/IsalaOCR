IsalaOCR database migration hotfix v3.2.2

Problem fixed
-------------
Existing training workspaces created by v3.1.x use schema v2. The v3.2.0
collector attempted to create an index on extraction_method before adding that
column, producing:

    sqlite3.OperationalError: no such column: extraction_method

Installation
------------
Extract this rootless ZIP directly over the existing IsalaOCR_docker folder
and replace files. Then run TRAINING_MENU.cmd and choose option 2 again.
The collector rebuilds its Docker image automatically.

Data safety
-----------
The migration preserves existing samples, labels, statuses and notes. Before
changing an older database it creates one SQLite-consistent backup at:

    training\workspace\samples.before-schema-v4.sqlite3

Do not delete samples.sqlite3. No manual database reset is required.
