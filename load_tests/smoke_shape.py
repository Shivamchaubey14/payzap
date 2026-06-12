"""
SmokeLoadShape: 5-minute quick test to verify setup before full run.
Ramps to 500 users then holds for 3 minutes.
"""
from locust import LoadTestShape


class SmokeLoadShape(LoadTestShape):

    STEPS = [
        (100, 10, 1),
        (500, 50, 4),
    ]

    def tick(self):
        run_time = self.get_run_time()
        elapsed_minutes = run_time / 60

        accumulated = 0
        for users, spawn_rate, hold_minutes in self.STEPS:
            accumulated += hold_minutes
            if elapsed_minutes < accumulated:
                return (users, spawn_rate)

        return None