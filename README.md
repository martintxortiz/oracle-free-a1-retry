# oracle-free-a1-retry

GitHub Actions job that retries creating one Oracle Cloud Always-Free `VM.Standard.A1.Flex` (4 OCPU / 24 GB) instance until capacity is available. All Oracle settings are encrypted Actions secrets; logs contain no IDs, IPs or credentials. The workflow disables itself once an instance exists.
