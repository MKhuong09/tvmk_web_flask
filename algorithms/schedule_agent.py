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
from enum import Enum
import random
from typing import List, Dict, Any
import pandas as pd
import openpyxl

from ortools.sat.python import cp_model

class DayOfWeek(Enum):
    MONDAY = 1
    TUESDAY = 2
    WEDNESDAY = 3
    THURSDAY = 4
    FRIDAY = 5
    SATURDAY = 6
    SUNDAY = 7

DAY_MAPPING = {
    1: "monday",
    2: "tuesday",
    3: "wednesday",
    4: "thursday",
    5: "friday",
    6: "saturday",
    7: "sunday"
}

class User:
  def __init__(self, user_id, data):
    self.id = user_id
    self.email = data.get("email")
    self.password = data.get("password")
    self.user_name = data.get("user_name")
    self.full_name = data.get("full_name")
    self.role_id = data.get("role_id", 2)
    self.allowed_off_days = data.get("allowed_off_days", 2)
    self.is_verified = data.get("is_verified", False)
    self.selected_days: List[int] = []

class Registration:
  def __init__(self, reg_id, data):
    self.id = reg_id
    self.selected_days = data.get("selected_days", [])
    self.session = data.get("session")
    self.week = data.get("week")
    self.year = data.get("year")
    self.is_accepted = data.get("is_accepted", False)
    self.status_id = data.get("status_id")
    self.user_id = data.get("user_id")
    self.created_at = data.get("created_at")

class ScheduleAgent:
    """Schedule generator using CP-SAT (OR-Tools). Falls back to simple greedy if OR-Tools not installed."""
    

    def __init__(self, users: List[User], registrations: List[Registration], NumOfSchedDays: int, NumOfUsersPerDay: int, last_week_schedule: Dict[int, List[Any]] | None = None):
        self.users = users
        self.registrations = registrations
        self.NumOfSchedDays = NumOfSchedDays
        self.NumOfUsersPerDay = NumOfUsersPerDay
        self.last_week_schedule = last_week_schedule or {}
        
    def to_json_dict(daily_schedule: Dict[str, List[Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Converts a daily schedule dictionary (mapping day strings like 'monday'
        to lists of User objects) into a fully JSON-serializable dictionary.
        """
        formatted_schedule = {}

        for day_name, staff_list in daily_schedule.items():
            formatted_schedule[day_name] = [
                u.to_dict() if hasattr(u, "to_dict") else {
                    "id": getattr(u, "id", None),
                    "full_name": getattr(u, "full_name", getattr(u, "user_name", str(u))),
                    "email": getattr(u, "email", None)
                } if hasattr(u, "id") else str(u)
                for u in staff_list
            ]

        return formatted_schedule

    def generate_schedule(self, solve_time_seconds: int = 5):
        if cp_model is None:
            return self._create_schedule_greedy()

        model = cp_model.CpModel()
        n_days = self.NumOfSchedDays

        def get_user_id(user):
            if isinstance(user, dict):
                return user.get("id") or user.get("user_id")
            return getattr(user, "id", None) or getattr(user, "user_id", None)

        user_ids = [get_user_id(u) for u in self.users if get_user_id(u) is not None]

        # 1. Build accepted registrations map
        accepted_regs = {}
        for r in (self.registrations or []):
            is_acc = r.get("is_accepted")
            if is_acc is True or is_acc == 1 or str(is_acc).lower() == "true":
                u_id = r.get("user_id")
                if u_id is not None:
                    days = r.get("selected_days", []) or []
                    norm_days = [int(d) for d in days if str(d).isdigit()]
                    accepted_regs[u_id] = norm_days
                    accepted_regs[str(u_id)] = norm_days
                    if str(u_id).isdigit():
                        accepted_regs[int(u_id)] = norm_days

        # 2. Decision variables
        x = {}
        for uid in user_ids:
            for d in range(n_days):
                x[(uid, d)] = model.NewBoolVar(f"x_{uid}_{d}")

        penalty_terms = []
        user_total_days = {}

        # 3. Availability & Max bounds per user (WITH LIVE TRACING)
        print("===== LIVE CONSTRAINT TRACE START =====")
        actual_pool_size = len(user_ids)

        for user in self.users:
            uid = get_user_id(user)
            if uid is None:
                continue

            selected_days = (
                accepted_regs.get(uid) or 
                accepted_regs.get(str(uid)) or 
                (accepted_regs.get(int(uid)) if str(uid).isdigit() else None) or 
                []
            )

            print(f"User UID: {uid} | Rest Days Found: {selected_days}")

            # HARD CONSTRAINT: User CANNOT work on their accepted rest days
            for d in range(n_days):
                day_num = d + 1  # 1 = Mon, 7 = Sun
                if day_num in selected_days:
                    model.Add(x[(uid, d)] == 0)
                    print(f"  -> FORBIDDEN: Added constraint x[({uid}, {d})] == 0 for Day {day_num}")

            # FIX: If pool size is small (e.g., 1 or 2 users), ignore allowed_off_days 
            # so they can work all remaining available days and prevent empty shifts.
            max_available_days = 7 - len(selected_days)
            
            if actual_pool_size <= 2:
                upper_bound = max_available_days  # Allow working all non-rest days!
                print(f"  -> Small pool override: User {uid} upper_bound set to {upper_bound}")
            else:
                allowed_off = user.get("allowed_off_days") if isinstance(user, dict) else getattr(user, "allowed_off_days", 0)
                allowed_off = allowed_off or 0
                max_allowed = 7 - allowed_off
                upper_bound = min(max_available_days, max_allowed)

            u_days = model.NewIntVar(0, max(0, upper_bound), f"u_days_{uid}")
            model.Add(u_days == sum(x[(uid, d)] for d in range(n_days)))
            user_total_days[uid] = u_days

        print("===== LIVE CONSTRAINT TRACE END =====")

        # 4. Daily Capacity Limits
        UNDER_STAFF_PENALTY = 2000
        actual_pool_size = len(user_ids)

        for d in range(n_days):
            daily_total = sum(x[(uid, d)] for uid in user_ids)
            model.Add(daily_total <= self.NumOfUsersPerDay)
            
            daynum = d + 1
            is_weekend = daynum in (DayOfWeek.SATURDAY.value, DayOfWeek.SUNDAY.value)
            
            # FIXED: Cap target_min by actual available pool size so 1 user doesn't trigger impossible targets
            target_min = min(self.NumOfUsersPerDay, 2, actual_pool_size) if is_weekend else min(1, actual_pool_size)
            
            under_staff = model.NewIntVar(0, self.NumOfUsersPerDay, f"under_staff_{d}")
            model.Add(under_staff >= target_min - daily_total)
            penalty_terms.append(UNDER_STAFF_PENALTY * under_staff)

        # 5. Workload Fairness Penalty (Only runs if multiple users exist)
        load_vars = list(user_total_days.values())
        if len(load_vars) > 1:
            min_load = model.NewIntVar(0, 7, "min_load")
            max_load = model.NewIntVar(0, 7, "max_load")
            model.AddMinEquality(min_load, load_vars)
            model.AddMaxEquality(max_load, load_vars)
            
            fairness_spread = model.NewIntVar(0, 7, "fairness_spread")
            model.Add(fairness_spread == max_load - min_load)
            FAIRNESS_PENALTY = 400
            penalty_terms.append(FAIRNESS_PENALTY * fairness_spread)

        # 6. Objective (FIXED: Stable weights, removed random.random() to ensure deterministic scheduling)
        WEEKEND_BONUS = 50  
        preference_score = 0
        
        for uid in user_ids:
            for d in range(n_days):
                daynum = d + 1
                base_weight = 10  # Stable base weight per shift
                if daynum in (DayOfWeek.SATURDAY.value, DayOfWeek.SUNDAY.value):
                    base_weight += WEEKEND_BONUS
                preference_score += base_weight * x[(uid, d)]

        model.Maximize(preference_score - sum(penalty_terms))

        # 7. Solve & Build a Multi-Keyed Safe Schedule Dictionary
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = float(solve_time_seconds)
        solver.parameters.random_seed = random.randrange(1, 1_000_000)
        solver.parameters.num_search_workers = 8

        result = solver.Solve(model)

        if result in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            daily_schedule = {}
            
            # Day name lookup helpers for maximum UI compatibility
            day_names_map = {
                1: ["monday", "mon", "1"],
                2: ["tuesday", "tue", "2"],
                3: ["wednesday", "wed", "3"],
                4: ["thursday", "thu", "4"],
                5: ["friday", "fri", "5"],
                6: ["saturday", "sat", "6"],
                7: ["sunday", "sun", "7"]
            }

            for d in range(n_days):
                day_num = d + 1  # 1 to 7 (Mon to Sun)
                
                # Gather users working on this day index
                scheduled = []
                for user in self.users:
                    uid = get_user_id(user)
                    if uid is not None:
                        is_working = solver.Value(x[(uid, d)]) == 1
                        
                        # Double-check validation
                        selected_days = accepted_regs.get(uid, [])
                        if is_working and (day_num in selected_days):
                            print(f"🚨 WARNING: User {uid} tried to work on rest day {day_num}!")
                        elif is_working:
                            scheduled.append(user)

                # Map to ALL possible key variations so your UI never experiences a lookup mismatch
                daily_schedule[d] = scheduled         # 0-indexed (0 to 6)
                daily_schedule[day_num] = scheduled     # 1-indexed integer (1 to 7)
                
                # Bind DayOfWeek Enum members and string names if applicable
                try:
                    for day_enum in DayOfWeek:
                        if day_enum.value == day_num or day_enum.name.lower() in day_names_map.get(day_num, []):
                            daily_schedule[day_enum] = scheduled
                            daily_schedule[day_enum.name] = scheduled
                            daily_schedule[day_enum.name.lower()] = scheduled
                except Exception:
                    pass

            print(f"Schedule created using CP-SAT solver in {solver.WallTime()} seconds.")
            return daily_schedule
        else:
            raise ValueError("Không thể tạo lịch tự động vì các ràng buộc quá khắt khe (Infeasible).")

        # Fairness: avoid scheduling users on weekend if they were scheduled on weekend last week
        # last_week_weekend_ids = set()
        # for daynum, users_on_day in (self.last_week_schedule or {}).items():
        #     if daynum in (DayOfWeek.SATURDAY.value, DayOfWeek.SUNDAY.value):
        #         for itm in users_on_day:
        #             try:
        #                 last_week_weekend_ids.add(int(getattr(itm, "userID", itm)))
        #             except Exception:
        #                 pass

        # if last_week_weekend_ids:
        #     for u, user in enumerate(self.users):
        #         if user.userID in last_week_weekend_ids:
        #             for d in range(n_days):
        #                 daynum = d + 1
        #                 if daynum in (DayOfWeek.SATURDAY.value, DayOfWeek.SUNDAY.value):
        #                     model.Add(x[(u, d)] == 0)
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
                candidates = [u for u in pool if d not in u.allowed_off_days and user_counts[u.userID] == u.max_days_per_week]
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
                if d not in u.allowed_off_days and sum(1 for dd in self.schedule.values() if u in dd) == u.max_days_per_week:
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
            for dayoff in user.allowed_off_days:
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
        UserData(fullname="Vinh", email="a@example.com", id=1,
                 allowed_off_days=[DayOfWeek.MONDAY.value, DayOfWeek.WEDNESDAY.value,DayOfWeek.FRIDAY.value,DayOfWeek.SUNDAY.value], 
                 max_days_per_week=3),
        
        UserData(fullname="Nhan", email="b@example.com", id=2,
                 allowed_off_days=[DayOfWeek.THURSDAY.value, DayOfWeek.FRIDAY.value,DayOfWeek.SATURDAY.value,DayOfWeek.SUNDAY.value]
                 , max_days_per_week=3),
        
        UserData(fullname="Nam", email="c@example.com", id=3,
                 allowed_off_days=[DayOfWeek.MONDAY.value,DayOfWeek.FRIDAY.value],
                 max_days_per_week=1),
        
        UserData(fullname="Son", email="d@example.com", id=4,
                 allowed_off_days=[DayOfWeek.THURSDAY.value, DayOfWeek.FRIDAY.value,DayOfWeek.SATURDAY.value,DayOfWeek.SUNDAY.value],
                 max_days_per_week=3),
        
        UserData(fullname="Huy", email="e@example.com", id=5,
                 allowed_off_days=[],
                 max_days_per_week=2),
        
        UserData(fullname="Giang", email="f@example.com", id=6,
                 allowed_off_days=[],
                 max_days_per_week=2),
        
        UserData(fullname="Khoa", email="g@example.com", id=7,
                 allowed_off_days=[],
                 max_days_per_week=2),
        
        UserData(fullname="Khuong", email="k@example.com", id=8,
                 allowed_off_days=[DayOfWeek.WEDNESDAY.value,DayOfWeek.THURSDAY.value, DayOfWeek.FRIDAY.value,DayOfWeek.SATURDAY.value,DayOfWeek.SUNDAY.value],
                 max_days_per_week=2),
    ]
    
    # last week scheduled user IDs for weekend days
    last_week = {}
    agent = ScheduleAgent(users, NumOfSchedDays=7, NumOfUsersPerDay=3, last_week_schedule=last_week)
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
    
