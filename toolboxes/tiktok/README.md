# TikTok toolbox

Use `api/toolbox.py` for official TikTok Display API reads and Content Posting API video uploads. `browser/toolbox.py` requires an interactive signed-in Selenium session and is supervised local-only.

Direct posting requires a TikTok developer app approved for `video.publish` and explicit authorization from the target user. TikTok restricts content posted by unaudited clients to private visibility. Review the current [TikTok Content Posting API requirements](https://developers.tiktok.com/doc/content-posting-api-get-started/) before enabling a write action.

The current API surface supports local-file video uploads. It does not yet expose TikTok photo posting or URL-pull publishing.
