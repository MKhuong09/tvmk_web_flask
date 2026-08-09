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
import pandas as pd
import openpyxl

from ortools.sat.python import cp_model



class DayOfWeek(enum.Enum):
    MONDAY = 1
    TUESDAY = 2
    WEDNESDAY = 3
    THURSDAY = 4
    FRIDAY = 5
    SATURDAY = 6
    SUNDAY = 7


class UserData:
    def __init__(self, name: str, email: str, userID: int, unavailable_days: List[int], max_days_per_week: int):
        self.name = name
        self.email = email
        self.userID = userID
        self.role = "user"
        self.unavailable_days = unavailable_days or []
        self.max_days_per_week = max_days_per_week


class ScheduleAgent:
    """Schedule generator using CP-SAT (OR-Tools). Falls back to simple greedy if OR-Tools not installed."""

    def __init__(self, users: List[UserData], NumOfSchedDays: int, NumOfUsersPerDay: int, last_week_schedule: Dict[int, List[Any]] | None = None):
        self.users = users
        self.NumOfSchedDays = NumOfSchedDays
        self.NumOfUsersPerDay = NumOfUsersPerDay
        self.schedule: Dict[int, List[UserData]] = {day: [] for day in range(1, NumOfSchedDays + 1)}
        self.last_week_schedule = last_week_schedule or {}

    def create_schedule(self, solve_time_seconds: int = 5):
        if cp_model is None:
            return self._create_schedule_greedy()

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
        for u, user in enumerate(self.users):
            model.Add(sum(x[(u, d)] for d in range(n_days)) == user.max_days_per_week)

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
            print(f"Schedule created using CP-SAT solver in {solver.WallTime()} seconds.")
            return self.schedule

        # Fallback to greedy if solver didn't find a solution
        print(f"CP-SAT solver failed to find a solution, falling back to greedy algorithm.\nReason: {solver.StatusName(result)}")
        print("Please try increasing Number of Users Per Day.")
        return self._create_schedule_greedy()

    def _create_schedule_greedy(self):
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
                candidates = [u for u in pool if d not in u.unavailable_days and user_counts[u.userID] == u.max_days_per_week]
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
                if d not in u.unavailable_days and sum(1 for dd in self.schedule.values() if u in dd) == u.max_days_per_week:
                    assigned.append(u)
            self.schedule[d] = assigned
        return self.schedule

    def get_schedule(self) -> Dict[int, List[UserData]]:
        return self.schedule
    
    def print_schedule(self):
        for day, users in self.schedule.items():
            print(f"Day {day}: {[u.name for u in users]}")
    
    def validating_schedule_result(self, schedule):
        for user in self.users:
            for dayoff in user.unavailable_days:
                if user.userID in schedule[dayoff]:
                    return False
                if sum(1 for d in schedule if user.userID in schedule[d]) > user.max_days_per_week:
                    return False
        return True

def convert_day_to_numeric(day_str: str) -> int:
    day_str = day_str.strip().lower()
    mapping = {
        "monday": DayOfWeek.MONDAY.value,
        "tuesday": DayOfWeek.TUESDAY.value,
        "wednesday": DayOfWeek.WEDNESDAY.value,
        "thursday": DayOfWeek.THURSDAY.value,
        "friday": DayOfWeek.FRIDAY.value,
        "saturday": DayOfWeek.SATURDAY.value,
        "sunday": DayOfWeek.SUNDAY.value
    }
    return mapping.get(day_str, -1)  # Return -1 if not found

def convert_numeric_to_day(day_num: int) -> str:
    mapping = {
        DayOfWeek.MONDAY.value: "Monday",
        DayOfWeek.TUESDAY.value: "Tuesday",
        DayOfWeek.WEDNESDAY.value: "Wednesday",
        DayOfWeek.THURSDAY.value: "Thursday",
        DayOfWeek.FRIDAY.value: "Friday",
        DayOfWeek.SATURDAY.value: "Saturday",
        DayOfWeek.SUNDAY.value: "Sunday"
    }
    return mapping.get(day_num, "Unknown")  # Return "Unknown" if not found

if __name__ == "__main__":
    # Quick local example (run after installing ortools or will fall back to greedy)
    users = [
        UserData(name="Vinh", email="a@example.com", userID=1, 
                 unavailable_days=[DayOfWeek.MONDAY.value, DayOfWeek.WEDNESDAY.value,DayOfWeek.FRIDAY.value,DayOfWeek.SUNDAY.value], 
                 max_days_per_week=3),
        
        UserData(name="Nhan", email="b@example.com", userID=2,
                 unavailable_days=[DayOfWeek.THURSDAY.value, DayOfWeek.FRIDAY.value,DayOfWeek.SATURDAY.value,DayOfWeek.SUNDAY.value]
                 , max_days_per_week=3),
        
        UserData(name="Nam", email="c@example.com", userID=3,
                 unavailable_days=[DayOfWeek.MONDAY.value,DayOfWeek.FRIDAY.value],
                 max_days_per_week=1),
        
        UserData(name="Son", email="d@example.com", userID=4,
                 unavailable_days=[DayOfWeek.THURSDAY.value, DayOfWeek.FRIDAY.value,DayOfWeek.SATURDAY.value,DayOfWeek.SUNDAY.value],
                 max_days_per_week=3),
        
        UserData(name="Huy", email="e@example.com", userID=5,
                 unavailable_days=[],
                 max_days_per_week=2),
        
        UserData(name="Giang", email="f@example.com", userID=6,
                 unavailable_days=[],
                 max_days_per_week=2),
        
        UserData(name="Khoa", email="g@example.com", userID=7,
                 unavailable_days=[],
                 max_days_per_week=2),
        
        UserData(name="Khuong", email="k@example.com", userID=8,
                 unavailable_days=[DayOfWeek.WEDNESDAY.value,DayOfWeek.THURSDAY.value, DayOfWeek.FRIDAY.value,DayOfWeek.SATURDAY.value,DayOfWeek.SUNDAY.value],
                 max_days_per_week=2),
    ]
    # last week scheduled user IDs for weekend days
    last_week = {}
    agent = ScheduleAgent(users, NumOfSchedDays=7, NumOfUsersPerDay=4, last_week_schedule=last_week)
    sched = agent.create_schedule()
    for day, us in sched.items():
        day_name = convert_numeric_to_day(day)
        print(day_name, [u.name for u in us])
    # write to excel
    # Columns: only Day of the Week
    df = pd.DataFrame(columns=['Day of the Week'])
    for day, us in sched.items():
        day_name = convert_numeric_to_day(day)
        user_names = ', '.join([u.name for u in us])
        df = pd.concat([df, pd.DataFrame({'Day of the Week': [day_name], 'Scheduled Users': [user_names]})], ignore_index=True)
    df_T = df.T
    df_T.to_excel('schedule.xlsx', index=False)

    print(agent.validating_schedule_result(schedule=sched))
    
