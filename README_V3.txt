BLACKGOLD BTC 15M V3

1. Replace your deployed app.py with app.py from this package.
2. Run schema_v3.sql in the same Supabase project once.
3. Keep the existing Supabase secrets. Do not use a service-role key in Streamlit secrets.
4. V3 remains paper-only; it never submits Kalshi orders.
5. The dashboard reruns every second for the countdown. Kalshi/Coinbase requests are cached so the APIs are not called every second.
6. Every 30 seconds, the current decision is recorded in signal_journal, including PASS.
7. Existing paper_trades remain intact.
8. Calibration is calculated from resolved paper trades. Bucket analysis uses the resolved paper-trade fields available in the journal; time-remaining analysis becomes fully populated for new V3 trades after the database column is added.
