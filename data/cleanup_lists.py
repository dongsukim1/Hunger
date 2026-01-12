import sqlite3

DB_PATH = "restaurants.db"

def cleanup_lists():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM ratings WHERE list_id IN (SELECT id FROM lists)")
    cursor.execute("DELETE FROM list_restaurants WHERE list_id IN (SELECT id FROM lists)")
    cursor.execute("DELETE FROM lists")
    conn.commit()
    conn.close()
    print("All lists cleaned up.")

def cleanup_invisible_ratings():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM lists WHERE user_id IS 1") 
    conn.commit()
    conn.close()

if __name__ == "__main__":
    # if input("Delete all lists? (yes/no): ").lower() == "yes":
    #     cleanup_lists()
    if input("Delete invisible rating? (yes/no): ").lower() == "yes":
        cleanup_invisible_ratings()