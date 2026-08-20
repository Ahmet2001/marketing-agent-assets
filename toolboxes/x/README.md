# X toolbox

`api/toolbox.py` is the server-side official API module. `browser/toolbox.py` is the Selenium module. `toolbox.py` re-exports the API module for compatibility.

The browser module expects the shared MarketingApp browser helpers. Do not run a browser action from a queue worker.
