"""
StepLoadShape: gradually ramps users from 1,000 to 100,000
over 1 hour in 10 steps. Each step holds for 6 minutes.
"""
from locust import LoadTestShape


class StepLoadShape(LoadTestShape):
    """
    Step  Users    Spawn rate   Hold (min)
    1     1,000    100/s        6
    2     5,000    200/s        6
    3     10,000   500/s        6
    4     20,000   1,000/s      6
    5     30,000   1,000/s      6
    6     40,000   1,000/s      6
    7     50,000   2,000/s      6
    8     65,000   2,000/s      6
    9     80,000   2,000/s      6
    10    100,000  5,000/s      6
    """

    STEPS = [
        (1_000,   100,    6),
        (5_000,   200,    6),
        (10_000,  500,    6),
        (20_000,  1_000,  6),
        (30_000,  1_000,  6),
        (40_000,  1_000,  6),
        (50_000,  2_000,  6),
        (65_000,  2_000,  6),
        (80_000,  2_000,  6),
        (100_000, 5_000,  6),
    ]

    def tick(self):
        run_time = self.get_run_time()
        elapsed_minutes = run_time / 60

        accumulated = 0
        for users, spawn_rate, hold_minutes in self.STEPS:
            accumulated += hold_minutes
            if elapsed_minutes < accumulated:
                return (users, spawn_rate)

        return None  # test complete after all steps