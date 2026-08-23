# Kara Tahta reference integration

These files are the original application-specific layer that was separated from the generic publisher. They depend on Kara Tahta tables, Railway Bucket storage, and endpoints such as `/api/generate-lesson`; they are intentionally not loaded by the generic worker.

To migrate Kara Tahta to the generic worker, its backend should create a `publish_jobs` record with a signed final-video URL and the desired title/caption/platforms. Keep the scheduler as a separate Kara Tahta service or rewrite it to create the same generic job payload.

## The scheduler now ships as its own package

`services/scheduler.js` here is kept only as a snapshot of Kara Tahta's
original embedded version (calls Kara Tahta's own `socialPublishQueue.js`/
`supabaseStore.js`, pre-dates the generic `publish_jobs` migration). The
maintained, standalone, actually-deployable version lives at
[`../../../scheduler_worker`](../../../scheduler_worker) -- a sibling
package to `social-media-worker` with its own `package.json`, minimal
Supabase/S3 clients, and a `workers/scheduler.js` entrypoint (`npm start`).

Running the scheduler as its own process (rather than embedded in
`workers/socialPublisher.js`, as this example folder's copy still is) means
scaling the publisher to multiple replicas never duplicates the scheduler's
`setInterval` tick (which must run exactly once). On Kara Tahta's own
Railway account it had to be embedded back into `socialPublisher.js` because
the account's plan blocked provisioning a 5th service -- that was a
deployment constraint, not a design preference; use the separate
`scheduler_worker` package whenever you can.
