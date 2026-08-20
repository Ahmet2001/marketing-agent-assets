# Kara Tahta reference integration

These files are the original application-specific layer that was separated from the generic publisher. They depend on Kara Tahta tables, Railway Bucket storage, and endpoints such as `/api/generate-lesson`; they are intentionally not loaded by the generic worker.

To migrate Kara Tahta to the generic worker, its backend should create a `publish_jobs` record with a signed final-video URL and the desired title/caption/platforms. Keep the scheduler as a separate Kara Tahta service or rewrite it to create the same generic job payload.
