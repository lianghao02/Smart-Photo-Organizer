
import reverse_geocoder as rg

def test_gps():
    # Taipei 101 coordinates
    coords = (25.033964, 121.564468)
    print("Testing reverse_geocoder with Taipei 101 coordinates...")
    
    try:
        results = rg.search([coords], mode=2) # mode 2 is single threaded
        print("Results:", results)
        if results and results[0]['cc'] == 'TW':
            print("SUCCESS: Detected Taiwan")
        else:
            print("FAILURE: Country code mismatch")
    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    test_gps()
