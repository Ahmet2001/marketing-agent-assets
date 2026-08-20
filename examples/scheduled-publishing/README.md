# Scheduled publishing

Your scheduler should create a `publish_request` when the campaign is due, then record the returned `publish_result`. It should not invoke browser tools or store OAuth secrets in the request itself.
