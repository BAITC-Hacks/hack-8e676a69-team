# Turbine input data

The two original organizer CSVs are included in the repository so a reviewer can start from a fresh clone. Their contents match the source datasets already recorded in this repository's ML development branch. Keep the filenames ending in turbine 1.csv and turbine 2.csv.

Alternatively, set DATASETS_DIR in back/.env to their absolute location. The backend reads only timestamp, wind speed, and temperature. Power/MWh training labels are not included in tickets.
