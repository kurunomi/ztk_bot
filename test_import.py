import sys
sys.path.insert(0, r"C:\Users\kurunomi\Desktop\ztk_bot")

try:
    from bot import main
    print("All imports OK")
except Exception as e:
    print(f"Import error: {e}")
    import traceback
    traceback.print_exc()
