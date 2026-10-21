"""Select complete histories for the first 100 users in user-sorted ratings.

Run from the repository root: python src/data/create_dev_sample.py
This development sample is deterministic, not a random evaluation sample.
"""

import csv
from pathlib import Path

input_file_path = "data/raw/ml-32m/ratings.csv"
output_file_path = "data/processed/ratings_dev.csv"

Path(output_file_path).parent.mkdir(parents=True, exist_ok=True)

selected_users = set()
max_users = 100
written_count = 0

with (
    open(input_file_path, mode="r", newline="", encoding="utf-8") as infile,
    open(output_file_path, mode="w", newline="", encoding="utf-8") as outfile,
):

    reader = csv.DictReader(infile)
    writer = csv.DictWriter(outfile, fieldnames=reader.fieldnames)
    writer.writeheader()

    for row in reader:
        user_id = row["userId"]

        if user_id not in selected_users:
            if len(selected_users) >= max_users:
                break

            selected_users.add(user_id)

        writer.writerow(row)
        written_count += 1


print(f"Total Unique Users Selected: {len(selected_users)}")
print(f"Total Rows Written: {written_count}")
