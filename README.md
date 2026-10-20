# hrsolar-watch

When do HOPS's day-ahead solar forecast (ENTSO-E 14.1.D, HR) and the day-ahead total load forecasts
(6.1.B, HR and coupled zones) for tomorrow appear in the ENTSO-E File Library? GitHub Actions runs
`watch.py` every 15 min (04-12 UTC) and every 30 min (13-18 UTC) and commits one log line per item and
run to `logs/<item>/<tomorrow>.txt`. HOPS's solar values are saved when first complete
(`logs/hops_solar_values/<day>_first_seen.csv`) and as last seen (`<day>_latest.csv`) to detect revisions.

Secrets: `ENTSOE_TP_USER`, `ENTSOE_TP_PASSWORD` (the Transparency Platform password expires every
183 days). Part of the Solari / hrsolar project; the logs are read on the Mac.
