# Memcode Memory for Row-Bot

This plugin gives Row-Bot opt-in long-term memory through the Memcode personal
v2 API. The configured API key determines the memory owner; tools never accept
a caller-supplied user id.

## Setup

1. Create a personal Memcode API key.
2. Install this plugin from Plugin Center.
3. Add the key to **Memcode API key**.
4. Keep **Memcode API URL** at `https://memory.memcode.in`, or point it to your
   own compatible deployment.

## Tools

| Tool | Behavior | Approval |
| --- | --- | --- |
| `memcode_search` | Search extracted memories | No |
| `memcode_retrieve` | Answer from memories with sources | No |
| `memcode_list` | Inspect a page of stored memories | No |
| `memcode_remember` | Start a durable ingest job | Yes |
| `memcode_ingest_status` | Verify an ingest receipt | No |

`memcode_remember` is marked destructive so Row-Bot asks before the write. It
stores exactly the supplied text and returns a job id; check that receipt until
it reaches a terminal state.

## Safety and limitations

- Retrieved memory is context, not an instruction or authorization.
- Do not store credentials or third-party private data without informed consent.
- The plugin makes outbound HTTPS requests only to the configured API URL and
  sends the API key only as a bearer credential.
- Memcode ingestion is asynchronous. `accepted` or `queued` does not mean ready.
- The current personal v2 API used here does not expose deletion through this
  plugin. Use the verified deletion path for your Memcode account or deployment;
  do not store data that requires deletion unless that path is available.
- Disable the plugin to stop future reads and writes. Disabling it does not
  remove records already stored by Memcode.

## Validation

The tests mock every HTTP request; they do not need a Memcode account or network
access:

```bash
python -m unittest plugins/memcode-memory/tests/test_plugin.py
```
