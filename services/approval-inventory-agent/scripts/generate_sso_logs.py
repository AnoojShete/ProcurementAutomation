import json
import random
import os
from datetime import datetime, timedelta

def generate_sso_logs():
    """Generate synthetic SSO login events for testing license utilisation scoring."""
    random.seed(42)
    apps = [
        "Microsoft 365 E3",
        "JetBrains All Products Pack",
        "Docker Pro",
        "Slack Enterprise",
        "Notion Team"
    ]
    
    logs = []
    end_date = datetime.now()
    start_date = end_date - timedelta(days=90)
    
    users = [f"user{i}@company.com" for i in range(1, 51)]
    
    for app in apps:
        active_users = users[:20]
        occasional_users = users[20:35]
        inactive_users = users[35:45]
        # never_logged_in = users[45:]
        
        for user in active_users:
            current = start_date
            while current < end_date:
                if random.random() < 0.8:  # 80% chance to login on a given day
                    logs.append({
                        "user_email": user,
                        "app_name": app,
                        "login_timestamp": (current + timedelta(hours=random.randint(8, 18))).isoformat(),
                        "session_duration_minutes": random.randint(30, 480)
                    })
                current += timedelta(days=1)
                
        for user in occasional_users:
            current = start_date
            while current < end_date:
                if random.random() < 0.1:  # 10% chance
                    logs.append({
                        "user_email": user,
                        "app_name": app,
                        "login_timestamp": (current + timedelta(hours=random.randint(8, 18))).isoformat(),
                        "session_duration_minutes": random.randint(15, 120)
                    })
                current += timedelta(days=1)
                
        for user in inactive_users:
            current = start_date
            # Only login in the first 30 days of the 90 day period
            while current < start_date + timedelta(days=30):
                if random.random() < 0.05:
                    logs.append({
                        "user_email": user,
                        "app_name": app,
                        "login_timestamp": (current + timedelta(hours=random.randint(8, 18))).isoformat(),
                        "session_duration_minutes": random.randint(10, 60)
                    })
                current += timedelta(days=1)
                
    output_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "synthetic-sso-logs")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "sso_login_events.json")
    
    # Sort logs by timestamp
    logs.sort(key=lambda x: x["login_timestamp"])
    
    with open(output_path, "w") as f:
        json.dump(logs, f, indent=2)
        
    print(f"Generated {len(logs)} SSO login events to {output_path}")
    print("Utilisation summary:")
    for app in apps:
        app_logs = [l for l in logs if l["app_name"] == app]
        unique_users_30d = set(
            l["user_email"] for l in app_logs 
            if datetime.fromisoformat(l["login_timestamp"]) > end_date - timedelta(days=30)
        )
        print(f"  {app}: {len(unique_users_30d)} unique users in last 30 days")

if __name__ == "__main__":
    generate_sso_logs()
