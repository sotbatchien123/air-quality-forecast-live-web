# DAP391m_Air-Quality-Forecast
 This project collect data about weather, population density, tree density and traffic density of Ho Chi Minh City in 2025 to predict Air quality in Ho Chi Minh City realtime.
## Project Structure: 
```
├── data/
│   │
│   ├── raw/
│   │   ├── weather/
│   │   ├── traffic/
│   │   ├── population/
│   │   ├── tree/
│   │   └── air_quality/
│   │
│   ├── processed/
│   │   ├── merged_data.csv
│   │   ├── cleaned_data.csv
│   │   ├── train.csv
│   │   └── test.csv
│   │
│   └── visualization/
│       ├── plots/
│       └── maps/
│
├── database/
│   │
│   ├── sql/
│   │   ├── create_tables.sql
│   │   ├── insert_data.sql
│   │   └── queries.sql
│   │
│   ├── export_to_sql.py
│   └── connect_sqlserver.py
│
│
├── src/
│   │
│   ├── collect_data/
│   │   ├── weather.py
│   │   ├── traffic.py
│   │   ├── population.py
│   │   └── tree.py
│   │
│   ├── preprocessing/
│   │   ├── clean_data.py
│   │   ├── merge_data.py
│   │   └── feature_engineering.py
│   │
│   ├── models/
│   │   ├── train.py
│   │   ├── predict.py
│   │   └── evaluate.py
│   ├── EDA/
│   │   ├── traffic
│   │   ├── weather
│   │   └── population
    
