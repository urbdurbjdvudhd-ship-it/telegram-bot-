import time

while True:
    try:
        print("✅ Bot starting...")
        import bot  # هذا يشغل bot.py تاعك
    except Exception as e:
        print("⚠️ Crash:", e)
        time.sleep(5)

if __name__ == "__main__":
    main()
