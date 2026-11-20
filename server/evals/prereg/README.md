# Pre-registrations

This directory holds the pre-registrations that are frozen before any generation run on the
pilot or test slice: `pilot.md` for the pilot and `v1.md` for the test split. Freezing means
committing: a file counts as frozen when git tracks it and it matches `HEAD`, because the commit
is the timestamp, and the generate command refuses to run on a slice until its file is frozen.
Drafts are edited freely until the commit that freezes them; after it, changes belong in a new
version, not an edit.
