from datetime import date, timedelta

def split_dates_by_20_years(date_from: date, date_to: date):
    """
    Splits the date range into sub-ranges of at most 20 years.
    If the difference is 20 years or less, returns [(date_from, date_to)].
    Otherwise, returns a list of (start, end) tuples, each covering up to 20 years.
    """
    result = []
    current_start = date_from

    # Helper to add 20 years safely
    def add_20_years(d):
        try:
            return d.replace(year=d.year + 20)
        except ValueError:
            # Handle leap years
            return d.replace(month=2, day=28, year=d.year + 20)

    while (date_to - current_start).days > 20 * 365:
        current_end = add_20_years(current_start) - timedelta(days=1)
        result.append((current_start, current_end))
        current_start = current_end + timedelta(days=1)

    result.append((current_start, date_to))
    return result

def main():

    # Example test cases
    test_cases = [
        (date(2000, 1, 1), date(2020, 1, 1)),  # exactly 20 years
        (date(2000, 1, 1), date(2045, 1, 1)),  # more than 20 years
        (date(2010, 5, 15), date(2015, 5, 15)),  # less than 20 years
        (date(1980, 2, 29), date(2025, 2, 28)),  # leap year edge case
    ]

    for idx, (start, end) in enumerate(test_cases, 1):
        print(f"Test case {idx}: {start} to {end}")
        ranges = split_dates_by_20_years(start, end)
        for r in ranges:
            print(f"  {r[0]} to {r[1]}")
        print()

if __name__ == "__main__":
    main()