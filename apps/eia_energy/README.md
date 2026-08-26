# EIA Energy Dashboard

Streamlit dashboard covering U.S. natural gas markets and ethanol/biofuels
production, capacity, and feedstock usage, built on the EIA Open Data API v2.
JPSI dark theme, matching the WASDE / Livestock Inventory dashboards.

## Sections

- **Weekly EIA Report** — replicates JSA's weekly ethanol/petroleum status
  report: summary bullets, an auto-generated narrative (production/stocks
  WoW with PADD drivers, gas demand, ethanol exports, days of supply), PADD
  breakdown tables (Production / Blender Demand / Imports / Stocks), seasonal
  marketing-year charts (Sept–Aug, one line per year), refinery operations
  narrative, and an EIA Petroleum Stocks table (crude / Cushing / gasoline /
  distillate / propane vs. their 5-year averages).
- **Natural Gas** — Henry Hub spot price, weekly storage (with a classic
  5-year min/max band), production, consumption by end use, and prices by
  sector.
- **Ethanol & Biofuels** — weekly ethanol production & stocks (national and
  by PADD), biofuels production capacity, feedstocks consumed (split by
  scale: corn/grain-sorghum for ethanol vs. oils/fats for biodiesel &
  renewable diesel), and fuel consumed at biofuels plants (highlighting
  natural gas as the dominant process fuel).

## Data source

U.S. Energy Information Administration Open Data API v2
(`https://api.eia.gov/v2`). All fetches are cached for 30 minutes.

## Run locally

```bash
python -m streamlit run app.py
```

Requires an `EIA_API_KEY` — set it in `.streamlit/secrets.toml` (gitignored)
for local dev:

```toml
EIA_API_KEY = "your-key"
```

## Deploy (Streamlit Cloud)

Point at `app.py`. Set the API key in **Settings → Secrets**:

```toml
EIA_API_KEY = "your-key"
```

Data: U.S. EIA · John Stewart & Associates
