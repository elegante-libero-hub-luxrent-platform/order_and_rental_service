from config import get_connection
import os

def print_env():
    print("DB_HOST =", os.getenv("DB_HOST"))
    print("DB_USER =", os.getenv("DB_USER"))
    print("DB_NAME =", os.getenv("DB_NAME"))
    print("DB_PORT =", os.getenv("DB_PORT"))

def fetch_all(cursor, table):
    cursor.execute(f"SELECT * FROM {table}")
    return cursor.fetchall()

def main():
    print_env()

    conn = get_connection()
    cursor = conn.cursor()

    # --- Test DB connectivity ---
    cursor.execute("SELECT 1")
    print("[DB TEST] SELECT 1 →", cursor.fetchone())

    print("\n============================")
    print("TABLE: orders")
    print("============================")
    for row in fetch_all(cursor, "orders"):
        print(row)

    print("\n============================")
    print("TABLE: order_logs")
    print("============================")
    for row in fetch_all(cursor, "order_logs"):
        print(row)

    print("\n============================")
    print("TABLE: jobs")
    print("============================")
    for row in fetch_all(cursor, "jobs"):
        print(row)

    cursor.close()
    conn.close()

if __name__ == "__main__":
    main()
