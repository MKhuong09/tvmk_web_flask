'''
Requirements for this implementation:
Input
*****
1. A list of users including their Information (name, email, userID, list of unavailable days)
2. Use the list of unavailable days to create a schedule for each user
3. Number of days to schedule (e.g., 7 days) = NumOfSchedDays
4. Number of users to schedule per day (e.g., 3 users per day) = NumOfUsersPerDay

Constraints
***********
1. Each user can only be scheduled on days they are available
2. Each user can only be schecduled with the maxium 3 days per week
3. The Maximum number of users per day is NumOfUsersPerDay
4. To be fair, refer last week's schedule to avoid there is a user who is scheduled on the weekend for 2 weeks in a row.
5. Use randomization to ensure that the schedule is not biased towards any particular user.
6. If there is a conflict in scheduling, the algorithm should try to resolve it by rescheduling users to different days (use backup algorithm) if possible.

Output
******
A schedule for each user that meets the above constraints. The schedule should be in the form of a dictionary where the keys are the days and the values are lists of users scheduled for that day.
'''
import enum
import random
from typing import List, Dict, Any

try:
    from ortools.sat.python import cp_model
except Exception:  # pragma: no cover - runtime dependency may be missing
    cp_model = None


class DayOfWeek(enum.Enum):
    MONDAY = 1
    TUESDAY = 2
    WEDNESDAY = 3
    THURSDAY = 4
    FRIDAY = 5
    SATURDAY = 6
    SUNDAY = 7


class User:
    def __init__(self, name: str, email: str, userID: int, unavailable_days: List[int]):
        self.name = name
        self.email = email
        self.userID = userID
        self.role = "user"
        self.unavailable_days = unavailable_days or []


class ScheduleAgent:
    """Schedule generator using CP-SAT (OR-Tools). Falls back to simple greedy if OR-Tools not installed."""

    def __init__(self, users: List[User], NumOfSchedDays: int, NumOfUsersPerDay: int, last_week_schedule: Dict[int, List[Any]] | None = None):
        self.users = users
        self.NumOfSchedDays = NumOfSchedDays
        self.NumOfUsersPerDay = NumOfUsersPerDay
        self.schedule: Dict[int, List[User]] = {day: [] for day in range(1, NumOfSchedDays + 1)}
        self.last_week_schedule = last_week_schedule or {}

    def create_schedule(self, max_days_per_user: int = 3, solve_time_seconds: int = 5):
        if cp_model is None:
            return self._create_schedule_greedy(max_days_per_user)

        model = cp_model.CpModel()
        n_users = len(self.users)
        n_days = self.NumOfSchedDays

        # Boolean decision vars x[u,d] == 1 if user u scheduled on day d
        x = {}
        for u in range(n_users):
            for d in range(n_days):
                x[(u, d)] = model.NewBoolVar(f"x_{u}_{d}")

        # Availability constraints
        for u, user in enumerate(self.users):
            for d in range(n_days):
                daynum = d + 1
                if daynum in user.unavailable_days:
                    model.Add(x[(u, d)] == 0)

        # Max users per day
        for d in range(n_days):
            model.Add(sum(x[(u, d)] for u in range(n_users)) <= self.NumOfUsersPerDay)
            model.Add(sum(x[(u, d)] for u in range(n_users)) > 0)  # Ensure at least one user is scheduled per day

        # Max days per user
        for u in range(n_users):
            model.Add(sum(x[(u, d)] for d in range(n_days)) <= max_days_per_user)

        # Fairness: avoid scheduling users on weekend if they were scheduled on weekend last week
        last_week_weekend_ids = set()
        for daynum, users_on_day in (self.last_week_schedule or {}).items():
            if daynum in (DayOfWeek.SATURDAY.value, DayOfWeek.SUNDAY.value):
                for itm in users_on_day:
                    try:
                        last_week_weekend_ids.add(int(getattr(itm, "userID", itm)))
                    except Exception:
                        pass

        if last_week_weekend_ids:
            for u, user in enumerate(self.users):
                if user.userID in last_week_weekend_ids:
                    for d in range(n_days):
                        daynum = d + 1
                        if daynum in (DayOfWeek.SATURDAY.value, DayOfWeek.SUNDAY.value):
                            model.Add(x[(u, d)] == 0)

        # Objective: randomize selection to avoid bias (maximize random weights)
        weights = {}
        for u in range(n_users):
            for d in range(n_days):
                weights[(u, d)] = int(random.random() * 1000)
        model.Maximize(sum(weights[(u, d)] * x[(u, d)] for u in range(n_users) for d in range(n_days)))

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = float(solve_time_seconds)
        solver.parameters.random_seed = random.randrange(1, 1_000_000)
        solver.parameters.num_search_workers = 8

        result = solver.Solve(model)
        if result in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            for d in range(n_days):
                daynum = d + 1
                scheduled = []
                for u in range(n_users):
                    if solver.Value(x[(u, d)]) == 1:
                        scheduled.append(self.users[u])
                self.schedule[daynum] = scheduled
            return self.schedule

        # Fallback to greedy if solver didn't find a solution
        return self._create_schedule_greedy(max_days_per_user)

    def _create_schedule_greedy(self, max_days_per_user: int = 3):
        # Simple randomized greedy algorithm with retry/backtracking
        attempts = 0
        n_days = self.NumOfSchedDays
        while attempts < 200:
            attempts += 1
            result = {day: [] for day in range(1, n_days + 1)}
            user_counts = {u.userID: 0 for u in self.users}
            pool = list(self.users)
            random.shuffle(pool)
            ok = True
            for d in range(1, n_days + 1):
                candidates = [u for u in pool if d not in u.unavailable_days and user_counts[u.userID] < max_days_per_user]
                # apply fairness: drop users who had weekend last week if today is weekend
                if d in (DayOfWeek.SATURDAY.value, DayOfWeek.SUNDAY.value):
                    last_week_ids = set()
                    for daynum, us in (self.last_week_schedule or {}).items():
                        if daynum in (DayOfWeek.SATURDAY.value, DayOfWeek.SUNDAY.value):
                            for itm in us:
                                try:
                                    last_week_ids.add(int(getattr(itm, "userID", itm)))
                                except Exception:
                                    pass
                    candidates = [u for u in candidates if u.userID not in last_week_ids]

                if len(candidates) < self.NumOfUsersPerDay:
                    ok = False
                    break

                chosen = random.sample(candidates, self.NumOfUsersPerDay)
                for u in chosen:
                    result[d].append(u)
                    user_counts[u.userID] += 1

            if ok:
                self.schedule = result
                return self.schedule

        # Last-resort deterministic fill (may violate fairness)
        for d in range(1, n_days + 1):
            assigned = []
            for u in self.users:
                if len(assigned) >= self.NumOfUsersPerDay:
                    break
                if d not in u.unavailable_days and sum(1 for dd in self.schedule.values() if u in dd) < max_days_per_user:
                    assigned.append(u)
            self.schedule[d] = assigned
        return self.schedule

    def get_schedule(self) -> Dict[int, List[User]]:
        return self.schedule
    
    def print_schedule(self):
        for day, users in self.schedule.items():
            print(f"Day {day}: {[u.name for u in users]}")
    
    def validating_schedule_result(self, schedule):
        for user in self.users:
            for dayoff in user.unavailable_days:
                if user.userID in schedule[dayoff]:
                    return False
        return True


if __name__ == "__main__":
    # Quick local example (run after installing ortools or will fall back to greedy)
    users = [
        User("Alice", "a@example.com", 1, [6]),
        User("Bob", "b@example.com", 2, []),
        User("Cara", "c@example.com", 3, [2]),
        User("Dan", "d@example.com", 4, [1, 3]),
        User("Eve", "e@example.com", 5, []),
    ]
    # last week scheduled user IDs for weekend days
    last_week = {6: [2], 7: [3]}
    agent = ScheduleAgent(users, NumOfSchedDays=7, NumOfUsersPerDay=7, last_week_schedule=last_week)
    sched = agent.create_schedule()
    for day, us in sched.items():
        print(day, [u.name for u in us])
    
    print(agent.validating_schedule_result(schedule=sched))
    
