# Reset API - Emergency database connection recovery
import sys
import gc

def reset():
    """Reset database connections and clean up resources"""
    try:
        # Force garbage collection
        gc.collect()
        
        # Import and reset ORM cache
        import importlib
        if 'peewee' in sys.modules:
            del sys.modules['peewee']
        
        # Reimport fresh
        import peewee
        
        print({
            "status": 200,
            "message": "Connection pool reset initiated",
            "action": "Please wait 10 seconds and refresh the page",
            "gc": "Garbage collection completed"
        })
        
        wiz.response.status(200, status="reset", message="Connection pool reset initiated")
    except Exception as e:
        wiz.response.status(500, error=str(e))
