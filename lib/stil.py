"""Gemeinsames Aussehen fuer Editor und Vergleichsseite.

Eine Datei statt zweier Stilbloecke, die auseinanderlaufen. Hell und dunkel
folgen der Systemeinstellung.
"""

CSS = """
  :root {
    --grund: #f6f7f9;    --karte: #ffffff;  --rand: #e4e6eb;
    --text: #15181d;     --leise: #656c7a;  --akzent: #2563eb;
    --schatten: 0 1px 2px rgba(16,24,40,.06), 0 8px 24px rgba(16,24,40,.08);
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --grund: #15181d;  --karte: #1d2127;  --rand: #2e3440;
      --text: #e8eaed;   --leise: #9aa2b1;  --akzent: #5b8cff;
      --schatten: 0 1px 2px rgba(0,0,0,.4), 0 8px 24px rgba(0,0,0,.35);
    }
  }

  * { box-sizing: border-box; }
  /* Ohne das gewinnt jedes eigene display gegen das hidden-Attribut. */
  [hidden] { display: none !important; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    margin: 0; background: var(--grund); color: var(--text);
    font-size: 15px; line-height: 1.55;
    -webkit-font-smoothing: antialiased;
  }
  .huelle { max-width: 1180px; margin: 0 auto; padding: 28px 24px 56px; }

  header { margin-bottom: 20px; }
  h1 { font-size: 23px; font-weight: 650; margin: 0 0 6px; letter-spacing: -.01em; }
  header p, .hinweis { margin: 0; color: var(--leise); font-size: 14px; }

  .karte {
    background: var(--karte); border: 1px solid var(--rand);
    border-radius: 14px; box-shadow: var(--schatten);
  }
  .leiste { display: flex; gap: 10px; align-items: center; flex-wrap: wrap;
            padding: 14px 16px; margin-bottom: 14px; }

  button, select {
    font: inherit; font-size: 14px; padding: 8px 14px; border-radius: 9px;
    border: 1px solid var(--rand); background: var(--karte); color: var(--text);
    cursor: pointer; transition: background .12s, border-color .12s, transform .06s;
  }
  button:hover:not(:disabled) { border-color: var(--akzent); }
  button:active:not(:disabled) { transform: translateY(1px); }
  button.haupt { background: var(--akzent); border-color: var(--akzent); color: #fff; }
  button:disabled { opacity: .38; cursor: default; }
  select { cursor: pointer; min-width: 240px; }
  .trenner { width: 1px; height: 26px; background: var(--rand); }

  .reiter { display: flex; gap: 4px; padding: 4px; border-radius: 11px;
            background: var(--grund); border: 1px solid var(--rand); }
  .reiter button { border: none; background: none; padding: 7px 14px; }
  .reiter button.haupt { background: var(--karte); color: var(--text);
                         box-shadow: var(--schatten); }

  .chip {
    display: inline-block; font-size: 13px; padding: 5px 11px; margin: 3px 3px 0 0;
    border-radius: 999px; border: 1px solid var(--rand); background: var(--karte);
    color: var(--text); cursor: pointer; user-select: none;
  }
  .chip:hover { border-color: var(--akzent); }
  .chip.aktiv { background: var(--akzent); border-color: var(--akzent); color: #fff; }

  .legende { display: flex; gap: 14px; flex-wrap: wrap; padding: 12px 16px;
             margin-bottom: 14px; }
  .feld { display: flex; align-items: center; gap: 6px; font-size: 13px;
          color: var(--leise); }
  .feld i { width: 22px; height: 13px; border-radius: 4px; display: block; }

  svg.plan { width: 100%; height: auto; display: block; border-radius: 13px;
             background: #fff; }

  table { border-collapse: collapse; width: 100%; font-size: 14px; }
  th, td { padding: 9px 14px; text-align: left; border-bottom: 1px solid var(--rand); }
  tr:last-child td { border-bottom: none; }
  th { font-size: 11.5px; text-transform: uppercase; letter-spacing: .5px;
       color: var(--leise); font-weight: 600; }
  td.zahl { text-align: right; font-variant-numeric: tabular-nums; }
  .besser { color: #16a34a; font-weight: 650; }
  .schlechter { color: #dc2626; font-weight: 650; }
  .gleich { color: var(--leise); }

  #stand { font-size: 13.5px; color: #16a34a; font-weight: 600; }
  .hinweisklein { font-size: 13px; color: var(--leise); }
"""
