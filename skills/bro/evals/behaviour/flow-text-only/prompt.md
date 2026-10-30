---
max_turns: 4
allowed_tools: [Skill]
---

Give me the decision brief.

Context from this session: uploads go from the browser to the API, the API writes the file to the storage bucket, the bucket sends a finalize event to the queue, and the worker reads the queue and marks the upload ready. Since Friday, about 2% of uploads never become ready. The worker logs show no event for those files, and the bucket shows the files exist. The queue subscription had a filter change on Friday. Options: revert the filter change, or add a sweeper job that marks stuck uploads ready after 10 minutes.
